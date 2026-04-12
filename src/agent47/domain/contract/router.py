"""
Contracts router — view and manage bug-fix contracts.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agent47.config.database import get_db
from agent47.domain.auth.router import get_current_user
from agent47.domain.user.model import User
from agent47.domain.contract.service import ContractService


router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.get("/")
def list_contracts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all contracts for the authenticated user."""
    contracts = ContractService(db).list_contracts(user.id)
    return [
                {
                    "id": c.id,
                    "repo_id": c.repo_id,
                    "status": c.status,
                    "attempts": c.attempts,
                    "pr_url": c.pr_url,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in contracts
        ]


@router.get("/{contract_id}")
def get_contract(
    contract_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get details for a specific contract."""
    contract = ContractService(db).get_contract(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Ensure the contract belongs to the authenticated user
    if contract.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your contract")

    return {
        "id": contract.id,
        "repo_id": contract.repo_id,
        "user_id": contract.user_id,
        "trigger_event": contract.trigger_event,
        "error_message": contract.error_message,
        "source_branch": contract.source_branch,
        "fix_branch": contract.fix_branch,
        "status": contract.status,
        "attempts": contract.attempts,
        "pr_url": contract.pr_url,
        "fix_summary": contract.fix_summary,
        "created_at": contract.created_at.isoformat() if contract.created_at else None,
        "completed_at": (
            contract.completed_at.isoformat() if contract.completed_at else None
        ),
    }
