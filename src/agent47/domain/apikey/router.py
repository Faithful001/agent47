from agent47.domain.apikey.dto.update_apikey_dto import UpdateApiKeyRequestDto
from agent47.domain.auth.router import get_current_user
from agent47.domain.user.model import User
from fastapi import Depends, HTTPException
from agent47.domain.apikey.service import ApiKeyService, validate_key_format
from fastapi.routing import APIRouter
from sqlalchemy.orm import Session
from agent47.config.database import get_db
from agent47.domain.apikey.model import ApiKey
from pydantic import BaseModel
from agent47.utils.crypto import decrypt_value, encrypt_value

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class ApiKeyResponseDto(BaseModel):
    id: str
    name: str
    key: str
    user_id: str
    model: str | None = None
    temperature: float | None = None
    is_active: bool = False

    model_config = {"from_attributes": True}


class UpdateActiveKeySettingsDto(BaseModel):
    active_provider: str
    model: str
    temperature: float


def mask_key(key: str) -> str:
    if not key:
        return ""
    if "..." in key:
        return key
    if len(key) <= 8:
        return "********"
    return f"{key[:6]}...{key[-4:]}"


def map_to_response(api_key: ApiKey) -> ApiKeyResponseDto:
    decrypted = decrypt_value(api_key.key)
    return ApiKeyResponseDto(
        id=api_key.id,
        name=api_key.name,
        key=mask_key(decrypted),
        user_id=api_key.user_id,
        model=api_key.model,
        temperature=api_key.temperature,
        is_active=api_key.is_active
    )


@router.put("/settings", response_model=ApiKeyResponseDto)
def update_active_settings(
    request: UpdateActiveKeySettingsDto,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = ApiKeyService(db)
    try:
        key = service.activate_key(
            user_id=user.id,
            provider_name=request.active_provider,
            model=request.model,
            temperature=request.temperature
        )
        return map_to_response(key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@router.get("/", response_model=list[ApiKeyResponseDto])
def get_apikeys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = ApiKeyService(db)
    try:
        keys = service.get_apikeys(user.id)
        return [map_to_response(k) for k in keys]
    except ValueError:
        return []


@router.get("/{id}", response_model=ApiKeyResponseDto)
def get_apikey(id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = ApiKeyService(db)
    try:
        key = service.get_apikey(id)
        if key.user_id != user.id:
            raise HTTPException(status_code=404, detail="API key not found")
        return map_to_response(key)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{id}", response_model=ApiKeyResponseDto)
def update_apikey(id: str, request: UpdateApiKeyRequestDto, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = ApiKeyService(db)
    try:
        key = service.update(id, user.id, request.name, request.key)
        return map_to_response(key)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{id}")
def delete_apikey(id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = ApiKeyService(db)
    try:
        service.delete(id, user.id)
        return {"message": "API key deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class SaveApiKeysRequest(BaseModel):
    api_keys: dict[str, str]
    active_provider: str
    model: str
    temperature: float


@router.post("/", response_model=list[ApiKeyResponseDto])
def save_apikeys(
    request: SaveApiKeysRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = ApiKeyService(db)
    
    # 1. Fetch existing keys
    existing_keys = db.query(ApiKey).filter(ApiKey.user_id == user.id).all()
    existing_keys_map = {k.name.lower(): k for k in existing_keys}
    
    try:
        # 2. Process create / update / delete for each provider in payload
        for provider, val in request.api_keys.items():
            provider_lower = provider.lower()
            val_stripped = val.strip()
            
            if not val_stripped:
                # Delete key if exists
                if provider_lower in existing_keys_map:
                    db.delete(existing_keys_map[provider_lower])
            else:
                # Masked keys shouldn't trigger updates/validations
                if "..." in val_stripped or "*" in val_stripped:
                    continue
                    
                if provider_lower in existing_keys_map:
                    # Update
                    validate_key_format(provider_lower, val_stripped)
                    existing_keys_map[provider_lower].key = encrypt_value(val_stripped)
                else:
                    # Create new deactivated key (will activate later if specified)
                    validate_key_format(provider_lower, val_stripped)
                    new_key = ApiKey(
                        name=provider_lower,
                        key=encrypt_value(val_stripped),
                        user_id=user.id,
                        is_active=False
                    )
                    db.add(new_key)
        
        db.commit()
        
        # 3. Activate provider and apply model/temperature settings
        service.activate_key(
            user_id=user.id,
            provider_name=request.active_provider,
            model=request.model,
            temperature=request.temperature
        )
        
        final_keys = db.query(ApiKey).filter(ApiKey.user_id == user.id).all()
        return [map_to_response(k) for k in final_keys]
        
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))