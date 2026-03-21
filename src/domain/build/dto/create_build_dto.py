from pydantic import BaseModel

class CreateBuildDto(BaseModel):
    repo_id: str
    branch: str
    commit_title: str
    commit_description: str
    commit_sha: str
    pusher: str

