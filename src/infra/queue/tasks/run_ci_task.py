import logging
import json
import docker
from src.config.database import SessionLocal
from src.domain.contract.service import ContractService
from src.domain.repository.model import Repository
from src.domain.build.model import Build
from src.infra.queue import celery

logger = logging.getLogger(__name__)

@celery.task(name="run_ci_task")
def run_ci_task(build_id: str, repo_id: str):
    print("TASK STARTED", build_id, repo_id)
    logger.info("Starting custom CI pipeline for build %s", build_id)
    db = SessionLocal()
    try:
        build = db.query(Build).filter(Build.id == build_id).first()
        repo = db.query(Repository).filter(Repository.id == repo_id).first()

        if not build or not repo:
            logger.error("Build or Repo not found")
            return

        install_cmd = repo.install_command or "echo 'No install command provided'"
        start_cmd = repo.start_command or "echo 'No start/test command provided'"
        build_cmd = repo.build_command or "echo 'No build command provided'"
        
        env_vars = {}
        if repo.env_vars:
            from src.utils.crypto import decrypt_value
            decrypted = decrypt_value(repo.env_vars)
            try:
                env_vars = json.loads(decrypted)
            except Exception:
                pass

        # Use the user's GitHub token to clone private repos
        user = repo.user
        github_token = user.github_access_token if user else ""
        
        # Construct clone URL with token for auth
        clone_url = f"https://oauth2:{github_token}@github.com/{repo.full_name}.git"

        # Docker client
        client = docker.from_env()
        image_name = f"agent47-ci-{build.commit_sha}"

        import tempfile
        import subprocess
        import os

        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info("Cloning repo to %s", temp_dir)
            subprocess.run(["git", "clone", clone_url, temp_dir], check=True, capture_output=True)
            subprocess.run(["git", "checkout", build.commit_sha], cwd=temp_dir, check=True, capture_output=True)

            logger.info("Building dynamic container image with Railpack for %s", repo.full_name)
            
            build_dir = temp_dir
            if repo.root_directory:
                build_dir = os.path.join(temp_dir, repo.root_directory.strip('/'))

            try:
                # Railpack will auto-detect the tech stack and create a Docker image
                # MAKE SURE RAILPACK IS INSTALLED ON THE HOST: curl -sSL https://railpack.com/install.sh | bash
                subprocess.run(
                    ["railpack", "build", build_dir, "--name", image_name],
                    check=True,
                    capture_output=True,
                )
            except FileNotFoundError:
                logger.error("Railpack CLI is not installed on the system.")
                return
            except subprocess.CalledProcessError as e:
                stdout = e.stdout.decode('utf-8') if e.stdout else ""
                stderr = e.stderr.decode('utf-8') if e.stderr else ""
                logger.error("Railpack build failed stdout: %s", stdout)
                logger.error("Railpack build failed stderr: %s", stderr)
                return

            # The environment is built! Now we execute the user's specific test commands in it
            # Railpack places the built code in /app by default
            script = f"""
            cd /app
            {install_cmd}
            {build_cmd}
            {start_cmd}
            """

            try:
                logger.info("Executing custom CI test commands inside Railpack container")
                logs = client.containers.run(
                    image=image_name,
                    command=["/bin/bash", "-c", script],
                    environment=env_vars,
                    remove=True,
                    network_disabled=False,
                )
                logger.info("CI pipeline succeeded for %s", build.commit_sha)

            except docker.errors.ContainerError as e:
                logger.warning("CI pipeline FAILED for %s", build.commit_sha)
                error_logs = e.stderr.decode('utf-8') if e.stderr else str(e)
                
                # Since the custom CI failed, let's create a Contract so Agent 47 can fix it
                contract_svc = ContractService(db)
                contract = contract_svc.create_contract(
                    repo_id=repo.full_name,
                    user_id=repo.user_id,
                    trigger_event="push_ci_failure",
                    error_message=f"Custom CI failed:\n{error_logs[-2000:]}", # capture the last 2000 chars of stderr
                    source_branch=build.branch,
                    commit_sha=build.commit_sha,
                    pr_number=None,
                    delivery_id=build.id,
                )
                
                # Trigger the standard Agent 47 autonomous fixer pipeline
                from src.infra.queue.tasks.run_pipeline import run_pipeline_task
                repo_url_with_token = f"https://oauth2:{github_token}@github.com/{repo.full_name}.git"
                run_pipeline_task.delay(
                    contract_id=contract.id,
                    user_id=repo.user_id,
                    repo_url=repo_url_with_token,
                )
            
    except Exception as exc:
        logger.exception("run_ci_task failed completely")
    finally:
        db.close()
