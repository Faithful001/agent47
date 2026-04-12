import logging

from agent47.config.database import SessionLocal
from agent47.domain.contract.service import ContractService
from agent47.domain.user.service import UserService
from agent47.infra.queue import celery

logger = logging.getLogger(__name__)

@celery.task(name="run_pipeline_task")
def run_pipeline_task(contract_id: str, user_id: str, repo_url: str):
    logger.info("Received Celery task to run pipeline for contract %s", contract_id)
    
    db = SessionLocal()
    try:
        contract = ContractService(db).get_contract(contract_id)
        user = UserService(db).get_user(user_id)

        if not contract or not user:
            logger.error("Contract or user not found for background task")
            return

        contract_svc = ContractService(db)
        
        contract_svc.run_contract(contract, user, repo_url)
        
        logger.info(
            "Contract %s completed: status=%s, pr=%s",
            contract.id, contract.status, contract.pr_url,
        )
    except Exception:
        logger.exception(
            "Background pipeline failed for contract %s", contract_id
        )
    finally:
        db.close()
