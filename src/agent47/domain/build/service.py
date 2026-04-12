from sqlalchemy.orm import Session
from agent47.domain.build.dto.create_build_dto import CreateBuildDto
from agent47.domain.build.model import Build
from datetime import datetime

class BuildService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: CreateBuildDto, user_id: str):
        new_build = Build(
            **payload.model_dump(),
            user_id=user_id
        )
        self.db.add(new_build)
        self.db.commit()
        self.db.refresh(new_build)
        return new_build
    
    def get_build(self, build_id: str, user_id: str):
        build = self.db.get(Build, build_id)
        if not build:
            raise ValueError("Build not found")
        if build.user_id != user_id:
            raise ValueError("You are not authorized to get this build")
        return build
    
    def get_builds(self, repo_id: str, user_id: str):
        return self.db.query(Build).filter(Build.repo_id == repo_id, Build.user_id == user_id).all()
    
    def get_builds_by_branch(self, repo_id: str, branch: str, user_id: str):
        return self.db.query(Build).filter(Build.repo_id == repo_id, Build.branch == branch, Build.user_id == user_id).all()
    
    def get_builds_by_commit_title(self, repo_id: str, commit_title: str, user_id: str):
        return self.db.query(Build).filter(Build.repo_id == repo_id, Build.commit_title == commit_title, Build.user_id == user_id).all()
    
    def get_builds_by_commit_sha(self, repo_id: str, commit_sha: str, user_id: str):
        return self.db.query(Build).filter(Build.repo_id == repo_id, Build.commit_sha == commit_sha, Build.user_id == user_id).all()
    
    def get_builds_by_created_at(self, repo_id: str, created_at: datetime, user_id: str):
        return self.db.query(Build).filter(Build.repo_id == repo_id, Build.created_at == created_at, Build.user_id == user_id).all()

    def delete_build(self, id: str, user_id: str):
        build = self.get_build(id)
        if not build:
            raise ValueError("Build not found")
        if build.user_id != user_id:
            raise ValueError("You are not authorized to delete this build")
        self.db.delete(build)
        self.db.commit()

    