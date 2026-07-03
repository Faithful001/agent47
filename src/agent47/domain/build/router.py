from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from agent47.config.database import get_db
from agent47.domain.build.service import BuildService
from agent47.domain.build.dto.create_build_dto import CreateBuildDto
from agent47.domain.auth.router import get_current_user
from agent47.domain.user.model import User

router = APIRouter(prefix="/builds", tags=["builds"])

@router.post("/", response_model=dict)
def create_build(payload: CreateBuildDto, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = BuildService(db)
    build = service.create(payload, user.id)
    return {
        "id": build.id,
        "repo_id": build.repo_id,
        "branch": build.branch,
        "commit_sha": build.commit_sha,
        "commit_title": build.commit_title,
        "created_at": build.created_at.isoformat()
    }

@router.get("/{build_id}")
def get_build(build_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = BuildService(db)
    build = service.get_build(build_id, user.id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    # Query matching contract to fetch pr_url & status
    from agent47.domain.contract.model import Contract
    contract = db.query(Contract).filter(
        Contract.commit_sha == build.commit_sha,
        Contract.user_id == user.id
    ).order_by(Contract.created_at.desc()).first()

    build_dict = {
        "id": build.id,
        "repo_id": build.repo_id,
        "user_id": build.user_id,
        "branch": build.branch,
        "commit_title": build.commit_title,
        "commit_description": build.commit_description,
        "commit_sha": build.commit_sha,
        "pusher": build.pusher,
        "created_at": build.created_at.isoformat() if build.created_at else None,
        "status": build.status,
        "files_changed": build.files_changed,
        "log_sections": build.log_sections,
        "fix_summary": build.fix_summary,
        "identified_issues": build.identified_issues,
        "total_additions": build.total_additions,
        "total_deletions": build.total_deletions,
        "duration_ms": build.duration_ms,
        "pr_url": contract.pr_url if contract else None,
        "contract_status": contract.status if contract else None,
    }
    return build_dict

@router.get("/")
def get_builds(
    repo_id: str,
    branch: Optional[str] = None,
    commit_sha: Optional[str] = None,
    commit_title: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    service = BuildService(db)
    
    if not branch and not commit_sha and not commit_title:
        paginated_data = service.get_builds_paginated(repo_id, user.id, page, limit)
        return paginated_data
        
    if branch:
        items = service.get_builds_by_branch(repo_id, branch, user.id)
    elif commit_sha:
        items = service.get_builds_by_commit_sha(repo_id, commit_sha, user.id)
    elif commit_title:
        items = service.get_builds_by_commit_title(repo_id, commit_title, user.id)
    else:
        items = service.get_builds(repo_id, user.id)
        
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "limit": len(items),
        "has_more": False
    }

@router.delete("/{build_id}")
def delete_build(build_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = BuildService(db)
    try:
        service.delete_build(build_id, user.id)
        return {"message": "Build deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
