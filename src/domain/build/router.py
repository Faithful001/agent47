from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.config.database import get_db
from src.domain.build.service import BuildService
from src.domain.build.dto.create_build_dto import CreateBuildDto
from src.domain.auth.router import get_current_user
from src.domain.user.model import User

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
    return build

@router.get("/")
def get_builds(
    repo_id: str,
    branch: Optional[str] = None,
    commit_sha: Optional[str] = None,
    commit_title: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    service = BuildService(db)
    if branch:
        return service.get_builds_by_branch(repo_id, branch, user.id)
    if commit_sha:
        return service.get_builds_by_commit_sha(repo_id, commit_sha, user.id)
    if commit_title:
        return service.get_builds_by_commit_title(repo_id, commit_title, user.id)
    return service.get_builds(repo_id, user.id)

@router.delete("/{build_id}")
def delete_build(build_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = BuildService(db)
    try:
        service.delete_build(build_id, user.id)
        return {"message": "Build deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
