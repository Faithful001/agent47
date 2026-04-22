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

logger = logging.getLogger(__name__)

REPO_CACHE_ROOT = os.environ.get("REPO_CACHE_ROOT", "/tmp/repo_cache")


def detect_base_image(build_dir: str) -> str:
    """Detect the appropriate base Docker image based on repo contents."""
    files = os.listdir(build_dir)

    if "package.json" in files:
        return "node:20-slim"
    if "requirements.txt" in files or "pyproject.toml" in files or "Pipfile" in files:
        return "python:3.12-slim"
    if "go.mod" in files:
        return "golang:1.22-slim"
    if "pom.xml" in files or "build.gradle" in files:
        return "eclipse-temurin:21-jdk-slim"
    if "Gemfile" in files:
        return "ruby:3.3-slim"
    if "composer.json" in files:
        return "php:8.3-cli"

    logger.warning("Could not detect tech stack, falling back to ubuntu:22.04")
    return "ubuntu:22.04"

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


@celery.task(name="run_ci_task")
def run_ci_task(build_id: str, repo_id: str):
    logger.info("Starting custom CI pipeline for build %s", build_id)
    db = SessionLocal()
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
        base_image = detect_base_image(build_dir)
        logger.info("Detected base image: %s for repo %s", base_image, repo.full_name)

        script = f"""
        cd /app
        {install_cmd}
        {build_cmd}
        {test_cmd}
        """

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
                    container.reload()
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
            except Exception:
                try:
                    container.kill()
                except Exception:
                    pass
                raise
            finally:
                container.remove(force=True)

        except docker.errors.ContainerError as e:
            logger.warning("CI pipeline FAILED for %s", build.commit_sha)
            error_logs = e.stderr.decode('utf-8') if e.stderr else str(e)

            contract_svc = ContractService(db)
            contract = contract_svc.create_contract(
                repo_id=repo.full_name,
                user_id=repo.user_id,
                trigger_event="push_ci_failure",
                error_message=f"Custom CI failed:\n{error_logs[-2000:]}",
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
        db.close()