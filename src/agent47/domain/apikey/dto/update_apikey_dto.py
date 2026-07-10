from pydantic import BaseModel

class UpdateApiKeyRequestDto(BaseModel):
    name: str | None = None
    key: str | None = None