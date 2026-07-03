import logging
import json
import os
import time
from filelock import FileLock
import subprocess
import docker
from agent47.config.database import SessionLocal
from agent47.domain.contract.service import ContractService
from agent47.domain.repository.model import Repository
from agent47.domain.build.model import Build
from agent47.infra.queue import celery
from agent47.utils.docker_utils import detect_base_image

logger = logging.getLogger(__name__)

REPO_CACHE_ROOT = os.environ.get("REPO_CACHE_ROOT", "/tmp/repo_cache")


def prepare_repo(repo, build, clone_url: str) -> str:
    os.makedirs(REPO_CACHE_ROOT, exist_ok=True)
    cache_dir = os.path.abspath(os.path.join(REPO_CACHE_ROOT, str(repo.id)))
    branch = build.branch if build else (repo.default_branch or "main")

    def run_cmd(cmd, **kwargs):
        try:
            return subprocess.run(cmd, check=True, capture_output=True, **kwargs)
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            logger.error("Command %s failed: %s", cmd, err_msg)
            raise RuntimeError(f"Command failed: {err_msg}") from e

    lock_file = cache_dir + ".lock"
    with FileLock(lock_file):
        if os.path.exists(os.path.join(cache_dir, ".git")):
            logger.info("Repo %s already cached, pulling branch=%s", repo.full_name, branch)
            run_cmd(["git", "fetch", "origin"], cwd=cache_dir)
            run_cmd(["git", "checkout", branch], cwd=cache_dir)
            run_cmd(["git", "reset", "--hard", f"origin/{branch}"], cwd=cache_dir)
        else:
            logger.info("Shallow-cloning repo %s (branch=%s) to %s", repo.full_name, branch, cache_dir)
            os.makedirs(cache_dir, exist_ok=True)
            run_cmd(["git", "clone", "--depth", "1", "--branch", branch, clone_url, cache_dir])

        if build and build.commit_sha:
            logger.info("Fetching specific commit %s", build.commit_sha)
            run_cmd(["git", "fetch", "--depth", "1", "origin", build.commit_sha], cwd=cache_dir)
            run_cmd(["git", "checkout", build.commit_sha], cwd=cache_dir)

    build_dir = cache_dir
    if repo.root_directory:
        build_dir = os.path.join(cache_dir, repo.root_directory.strip("/"))

    return build_dir

NOISE_PATTERNS = {
    "node": [
        "npm notice", "npm warn", "vulnerability", "vulnerabilities",
        "funding", "npm fund", "audit", "packages are looking",
        "To address", "Run `npm", "New major version",
    ],
    "python": [
        "WARNING::", "DeprecationWarning", "PendingDeprecationWarning",
        "UserWarning", "pip is configured", "Requirement already satisfied",
    ],
    "go": [
        "go: downloading", "go: finding",
    ],
    "java": [
        "WARNING:", "Download from", "Downloading from",
        "Downloaded from", "Progress",
    ],
    "ruby": [
        "Fetching gem", "Installing gem", "Gem::", "Successfully installed",
    ],
    "php": [
        "Loading composer", "Updating dependencies", "Package operations",
    ],
}

ERROR_KEYWORDS = [
    "error", "Error", "ERROR",
    "failed", "Failed", "FAILED",
    "exception", "Exception", "EXCEPTION",
    "fatal", "Fatal", "FATAL",
    "traceback", "Traceback",
    "undefined", "cannot", "Cannot",
    "SyntaxError", "TypeError", "ValueError",
    "ImportError", "ModuleNotFoundError",
]

def extract_relevant_errors(logs: str, build_dir: str) -> str:
    from agent47.utils.docker_utils import detect_base_image
    
    base_image = detect_base_image(build_dir)
    
    # Map image to noise key
    noise_key = None
    if "node" in base_image:
        noise_key = "node"
    elif "python" in base_image:
        noise_key = "python"
    elif "golang" in base_image:
        noise_key = "go"
    elif "temurin" in base_image or "jdk" in base_image:
        noise_key = "java"
    elif "ruby" in base_image:
        noise_key = "ruby"
    elif "php" in base_image:
        noise_key = "php"
    
    noise = NOISE_PATTERNS.get(noise_key, []) if noise_key else []
    
    lines = logs.splitlines()
    relevant = [
        line for line in lines
        if any(kw in line for kw in ERROR_KEYWORDS)
        and not any(n in line for n in noise)
    ]
    
    if not relevant:
        relevant = lines[-20:]
    
    return "\n".join(relevant)

def parse_issues_from_logs(log_sections: list) -> list:
    import re
    issues = []
    for section in log_sections:
        if not section.get("has_error"):
            continue
        for line in section.get("lines", []):
            match = re.match(r"^([^\(]+)\((\d+),(\d+)\):\s*error\s+(\w+):\s*(.*)$", line)
            if match:
                issues.append({
                    "title": f"TypeScript Error {match.group(4)}",
                    "description": match.group(5),
                    "severity": "critical",
                    "file": match.group(1).strip(),
                    "line": int(match.group(2))
                })
                continue
            
            # Fallback for execution errors/exceptions
            if any(kw in line.lower() for kw in ["error", "failed", "exception", "fatal"]) and len(line) > 10 and "npm err" not in line.lower():
                issues.append({
                    "title": "Execution Error",
                    "description": line.strip(),
                    "severity": "critical"
                })
    return issues

def parse_logs_into_sections(logs: str) -> list:
    sections = []
    current_phase = "setup"
    current_lines = []
    has_error = False

    for line in logs.splitlines():
        if "=== INSTALL_START ===" in line:
            if current_lines:
                sections.append({
                    "phase": current_phase,
                    "lines": current_lines,
                    "has_error": has_error,
                })
            current_phase = "install"
            current_lines = []
            has_error = False
            continue
        elif "=== BUILD_START ===" in line:
            if current_lines:
                sections.append({
                    "phase": current_phase,
                    "lines": current_lines,
                    "has_error": has_error,
                })
            current_phase = "build"
            current_lines = []
            has_error = False
            continue
        elif "=== TEST_START ===" in line:
            if current_lines:
                sections.append({
                    "phase": current_phase,
                    "lines": current_lines,
                    "has_error": has_error,
                })
            current_phase = "test"
            current_lines = []
            has_error = False
            continue

        line_lower = line.lower()
        if "error" in line_lower or "fail" in line_lower or "err!" in line_lower:
            has_error = True

        current_lines.append(line)

    if current_lines:
        sections.append({
            "phase": current_phase,
            "lines": current_lines,
            "has_error": has_error,
        })

    return sections


def get_commit_diff(repo_dir: str, commit_sha: str) -> dict:
    try:
        from git import Repo
        repo = Repo(repo_dir)
        commit = repo.commit(commit_sha)
        
        parent = commit.parents[0] if commit.parents else None
        diffs = parent.diff(commit, create_patch=True) if parent else commit.diff(None, create_patch=True)
        
        files_changed = []
        total_additions = 0
        total_deletions = 0
        
        for diff in diffs:
            patch_text = ""
            if diff.diff:
                patch_text = diff.diff.decode('utf-8', errors='ignore') if isinstance(diff.diff, bytes) else diff.diff
            
            hunks = []
            additions = 0
            deletions = 0
            
            current_hunk = None
            old_line_num = 0
            new_line_num = 0
            
            for line in patch_text.splitlines():
                if line.startswith('@@'):
                    parts = line.split(' ')
                    if len(parts) >= 3:
                        old_parts = parts[1].replace('-', '').split(',')
                        new_parts = parts[2].replace('+', '').split(',')
                        
                        old_start = int(old_parts[0]) if old_parts[0].replace('-', '').isdigit() else 1
                        old_count = int(old_parts[1]) if (len(old_parts) > 1 and old_parts[1].isdigit()) else 1
                        new_start = int(new_parts[0]) if new_parts[0].replace('+', '').isdigit() else 1
                        new_count = int(new_parts[1]) if (len(new_parts) > 1 and new_parts[1].isdigit()) else 1
                        
                        current_hunk = {
                            "old_start": old_start,
                            "old_count": old_count,
                            "new_start": new_start,
                            "new_count": new_count,
                            "lines": []
                        }
                        hunks.append(current_hunk)
                        old_line_num = old_start
                        new_line_num = new_start
                elif current_hunk is not None:
                    if line.startswith('+'):
                        additions += 1
                        current_hunk["lines"].append({
                            "type": "addition",
                            "content": line[1:],
                            "new_line_number": new_line_num
                        })
                        new_line_num += 1
                    elif line.startswith('-'):
                        deletions += 1
                        current_hunk["lines"].append({
                            "type": "deletion",
                            "content": line[1:],
                            "old_line_number": old_line_num
                        })
                        old_line_num += 1
                    else:
                        current_hunk["lines"].append({
                            "type": "context",
                            "content": line[1:] if line else "",
                            "old_line_number": old_line_num,
                            "new_line_number": new_line_num
                        })
                        old_line_num += 1
                        new_line_num += 1
                        
            status = "modified"
            if diff.new_file:
                status = "added"
            elif diff.deleted_file:
                status = "removed"
            elif diff.renamed:
                status = "renamed"
                
            total_additions += additions
            total_deletions += deletions
            
            files_changed.append({
                "filename": diff.b_path or diff.a_path,
                "status": status,
                "additions": additions,
                "deletions": deletions,
                "hunks": hunks,
                "old_filename": diff.a_path if diff.renamed else None
            })
            
        return {
            "files_changed": files_changed,
            "total_additions": total_additions,
            "total_deletions": total_deletions
        }
    except Exception as e:
        logger.exception("Failed to get commit diff details: %s", e)
        return {
            "files_changed": [],
            "total_additions": 0,
            "total_deletions": 0
        }


@celery.task(name="run_ci_task")
def run_ci_task(build_id: str, repo_id: str):
    logger.info("Starting custom CI pipeline for build %s", build_id)
    db = SessionLocal()
    railpack_image_name = None  # track railpack-built images for cleanup

    try:
        build = db.query(Build).filter(Build.id == build_id).first()
        repo = db.query(Repository).filter(Repository.id == repo_id).first()

        if not repo or not build:
            logger.error("Build or Repo not found")
            return

        build.status = "in_progress"
        db.commit()
        start_time = time.time()


        install_cmd = repo.install_command or "echo 'No install command provided'"
        build_cmd = repo.build_command or "echo 'No build command provided'"
        test_cmd = repo.test_command or "echo 'No test command provided'"

        env_vars = {}
        if repo.env_vars:
            from agent47.utils.crypto import decrypt_value
            decrypted = decrypt_value(repo.env_vars)
            try:
                env_vars = json.loads(decrypted)
            except Exception:
                try:
                    env_vars = dict(
                        line.split("=", 1)
                        for line in decrypted.strip().splitlines()
                        if "=" in line and not line.startswith("#")
                    )
                except Exception:
                    logger.warning("Failed to parse env vars for repo %s", repo.full_name)

        user = repo.user
        github_token = user.github_access_token if user else ""
        clone_url = f"https://oauth2:{github_token}@github.com/{repo.full_name}.git"

        client = docker.from_env(timeout=900)

        build_dir = prepare_repo(repo, build, clone_url)

        candidate_image_name = f"ci_image_{build_id}"
        logger.info("Building base image with Railpack: %s from %s", candidate_image_name, build_dir)

        try:
            # # To use Railpack in production, uncomment this block:
            # subprocess.run(
            #     ["railpack", "build", "--name", candidate_image_name, build_dir],
            #     check=True,
            #     capture_output=True,
            #     text=True,
            # )

            base_image = detect_base_image(build_dir)
            try:
                client.images.get(candidate_image_name)
                base_image = candidate_image_name
                railpack_image_name = candidate_image_name  # mark for post-run cleanup
                logger.info("Railpack image verified in Docker daemon: %s", base_image)
            except docker.errors.ImageNotFound:
                logger.warning(
                    "Railpack reported success but image '%s' not found in Docker daemon. "
                    "Falling back to heuristic detection.",
                    candidate_image_name,
                )
                base_image = detect_base_image(build_dir)
                logger.info("Fallback base image detected: %s", base_image)

        except subprocess.CalledProcessError as e:
            logger.warning("Railpack build failed: %s. Falling back to heuristic detection.", e.stderr)
            base_image = detect_base_image(build_dir)
            logger.info("Fallback base image detected: %s", base_image)
        except FileNotFoundError:
            logger.warning("Railpack CLI not found. Falling back to heuristic detection.")
            base_image = detect_base_image(build_dir)
            logger.info("Fallback base image detected: %s", base_image)

        logger.info("Base image resolved: %s", base_image)

        script = f"""
        cd /app
        echo "=== INSTALL_START ==="
        {install_cmd}
        echo "=== BUILD_START ==="
        {build_cmd}
        echo "=== TEST_START ==="
        {test_cmd}
        """

        ci_error: Exception | None = None

        try:
            container = client.containers.run(
                image=base_image,
                command=["/bin/bash", "-c", script],
                environment=env_vars,
                volumes={build_dir: {"bind": "/app", "mode": "rw"}},
                working_dir="/app",
                network_disabled=False,
                detach=True,
            )

            try:
                deadline = time.time() + 900
                while time.time() < deadline:
                    try:
                        container.reload()
                    except docker.errors.APIError as reload_err:
                        logger.warning(
                            "Docker API error during container.reload() for build %s: %s. "
                            "Treating as container failure.",
                            build_id, reload_err,
                        )
                        try:
                            logs = container.logs(stderr=True).decode("utf-8")
                        except Exception:
                            logs = f"Container lost during execution: {reload_err}"
                        raise docker.errors.ContainerError(
                            container, 1, script, base_image, logs.encode()
                        ) from reload_err
                    if container.status in ("exited", "dead"):
                        break
                    time.sleep(5)
                else:
                    raise TimeoutError(
                        f"Container did not finish within 900s for build {build_id}"
                    )

                exit_code = container.attrs["State"]["ExitCode"]
                if exit_code != 0:
                    logs = container.logs(stderr=True).decode("utf-8")
                    raise docker.errors.ContainerError(
                        container, exit_code, script, base_image, logs.encode()
                    )

                logger.info("CI pipeline succeeded for %s", build.commit_sha)

                # Fetch full logs and save success result
                try:
                    logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
                except Exception:
                    logs = "CI succeeded but logs could not be retrieved."

                diff_info = get_commit_diff(build_dir, build.commit_sha)
                build.status = "success"
                build.log_sections = parse_logs_into_sections(logs)
                build.files_changed = diff_info["files_changed"]
                build.total_additions = diff_info["total_additions"]
                build.total_deletions = diff_info["total_deletions"]
                build.duration_ms = int((time.time() - start_time) * 1000)
                build.identified_issues = []
                build.fix_summary = "Build completed successfully with no compilation errors."
                db.commit()

            except Exception as exc:
                ci_error = exc
                try:
                    container.kill()
                except Exception:
                    pass
                raise
            finally:
                container.remove(force=True)

        except (docker.errors.ContainerError, TimeoutError) as exc:
            logger.warning("CI pipeline FAILED for %s: %s", build.commit_sha, exc)

            if isinstance(exc, TimeoutError):
                error_logs = str(exc)
            else:
                error_logs = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)

            diff_info = get_commit_diff(build_dir, build.commit_sha)
            build.status = "failed"
            build.log_sections = parse_logs_into_sections(error_logs)
            build.files_changed = diff_info["files_changed"]
            build.total_additions = diff_info["total_additions"]
            build.total_deletions = diff_info["total_deletions"]
            build.duration_ms = int((time.time() - start_time) * 1000)
            
            # Parse issues and recommended resolution summary
            parsed_issues = parse_issues_from_logs(build.log_sections)
            build.identified_issues = parsed_issues
            if parsed_issues:
                summary_lines = []
                for issue in parsed_issues:
                    file_info = issue.get("file", "")
                    if issue.get("line"):
                        file_info += f":{issue['line']}"
                    summary_lines.append(
                        f"### {issue['title']}\n"
                        f"- **File**: `{file_info}`\n"
                        f"- **Details**: {issue['description']}"
                    )
                build.fix_summary = "## Recommended Action\n\nResolve the following compilation issues detected in the logs:\n\n" + "\n\n".join(summary_lines)
            else:
                build.fix_summary = "Custom CI compilation/execution failed. Review build logs."
            db.commit()

            contract_svc = ContractService(db)
            contract = contract_svc.create_contract(
                repo_id=repo.full_name,
                user_id=repo.user_id,
                trigger_event="push_ci_failure",
                error_message=f"Custom CI failed:\n{extract_relevant_errors(error_logs, build_dir)}",
                source_branch=build.branch,
                commit_sha=build.commit_sha,
                pr_number=None,
            )

            from agent47.infra.queue.tasks.run_pipeline import run_pipeline_task
            run_pipeline_task.delay(
                contract_id=contract.id,
                user_id=repo.user_id,
                repo_url=f"https://oauth2:{github_token}@github.com/{repo.full_name}.git",
            )


    except Exception:
        logger.exception("run_ci_task failed completely for build %s", build_id)
    finally:
        # Remove the Railpack-built image from the daemon after the run.
        # Heuristic fallback images (node:20-slim etc.) are shared, so leave those alone.
        if railpack_image_name:
            try:
                client.images.remove(railpack_image_name, force=True)
                logger.info("Removed Railpack image %s", railpack_image_name)
            except Exception as e:
                logger.warning("Could not remove Railpack image %s: %s", railpack_image_name, e)
        db.close()