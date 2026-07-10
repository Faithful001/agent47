from pydantic import BaseModel

class CreateApiKeyRequestDto(BaseModel):
    name: str
    key: str