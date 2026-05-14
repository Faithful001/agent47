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
    
    return "\n".join(relevant).strip()


@celery.task(name="run_ci_task")
def run_ci_task(build_id: str, repo_id: str):
    logger.info("Starting custom CI pipeline for build %s", build_id)
    db = SessionLocal()
    railpack_image_name = None  # track railpack-built images for cleanup

    try:
        build = db.query(Build).filter(Build.id == build_id).first()
        repo = db.query(Repository).filter(Repository.id == repo_id).first()

        if not repo:
            logger.error("Build or Repo not found")
            return

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
        {install_cmd}
        {build_cmd}
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
                        # Container is gone or Docker daemon errored — get whatever logs we can
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
                    # Timed out — treat identically to a non-zero exit so the
                    # failure pipeline fires instead of silently swallowing the error.
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
            # Both a non-zero exit and a timeout should trigger the fix pipeline.
            logger.warning("CI pipeline FAILED for %s: %s", build.commit_sha, exc)

            if isinstance(exc, TimeoutError):
                error_logs = str(exc)
            else:
                error_logs = exc.stderr.decode("utf-8") if exc.stderr else str(exc)

            contract_svc = ContractService(db)
            contract = contract_svc.create_contract(
                repo_id=repo.full_name,
                user_id=repo.user_id,
                trigger_event="push_ci_failure",
                # error_message=f"Custom CI failed:\n{error_logs[-2000:]}",
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