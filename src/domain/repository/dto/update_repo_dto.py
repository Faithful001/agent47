from pydantic import BaseModel
class UpdateRepoDto(BaseModel):
    install_command: str | None = None
    build_command: str | None = None
    start_command: str | None = None
    env_vars: str | None = None
    root_directory: str | None = None