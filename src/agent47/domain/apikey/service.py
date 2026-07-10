from sqlalchemy.orm import Session
from .model import ApiKey
from agent47.utils.crypto import encrypt_value, decrypt_value


def validate_key_format(name: str, key: str) -> None:
    name_lower = name.lower()
    # Masked keys shouldn't trigger validation
    if "..." in key or "*" in key:
        return
    if name_lower == "openrouter" and not key.startswith("sk-or-v1-"):
        raise ValueError("Invalid OpenRouter key format. It should start with 'sk-or-v1-'.")
    elif name_lower == "google" and not key.startswith("AIzaSy"):
        raise ValueError("Invalid Google API key format. It should start with 'AIzaSy'.")
    elif name_lower == "anthropic" and not key.startswith("sk-ant-"):
        raise ValueError("Invalid Anthropic API key format. It should start with 'sk-ant-'.")
    elif name_lower == "openai" and not (key.startswith("sk-proj-") or key.startswith("sk-")):
        raise ValueError("Invalid OpenAI API key format. It should start with 'sk-proj-' or 'sk-'.")
    elif name_lower == "groq" and not key.startswith("gsk_"):
        raise ValueError("Invalid Groq API key format. It should start with 'gsk_'.")


class ApiKeyService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str, key: str, user_id: str) -> ApiKey:
        validate_key_format(name, key)
        
        # If this is the first key being added, or there are no active keys, default it to active.
        has_active = self.db.query(ApiKey).filter(ApiKey.user_id == user_id, ApiKey.is_active == True).first()
        is_active = not bool(has_active)

        api_key = ApiKey(
            name=name,
            key=encrypt_value(key),
            user_id=user_id,
            is_active=is_active
        )

        self.db.add(api_key)
        self.db.commit()
        self.db.refresh(api_key)
        return api_key

    def get_apikey(self, id: str)-> ApiKey:
        api_key = self.db.get(ApiKey, id)
        if not api_key:
            raise ValueError("Apikey not found")
        return api_key

    def get_apikeys(self, user_id: str)-> list[ApiKey]:
        api_keys = self.db.query(ApiKey).filter(ApiKey.user_id == user_id).all()
        if not api_keys:
            raise ValueError("Apikeys for user_id not found")
        return api_keys

    def get_user_api_key(self, user_id: str) -> str | None:
        """Retrieves and decrypts the user's API key. Attempts to find OpenRouter first."""
        keys = self.db.query(ApiKey).filter(ApiKey.user_id == user_id).all()
        if not keys:
            return None
        for key in keys:
            if key.name.upper() in ("OPENROUTER", "OPENROUTER_API_KEY"):
                return decrypt_value(key.key)
        return decrypt_value(keys[0].key)

    def activate_key(
        self,
        user_id: str,
        provider_name: str,
        model: str,
        temperature: float,
    ) -> ApiKey:
        """Sets the selected provider's key as active, updates model and temperature, and deactivates other keys."""
        keys = self.db.query(ApiKey).filter(ApiKey.user_id == user_id).all()
        active_key = None
        
        for key in keys:
            if key.name.lower() == provider_name.lower():
                key.is_active = True
                key.model = model
                key.temperature = temperature
                active_key = key
            else:
                key.is_active = False
                
        if not active_key:
            raise ValueError(f"You must add the {provider_name} API key under API Keys before selecting it as active.")
            
        self.db.commit()
        return active_key

    def update(self, id: str, user_id: str, name: str = None, key: str = None) -> ApiKey:
        api_key = self.get_apikey(id)
        if not api_key:
            raise ValueError("Apikey not found")
        if api_key.user_id != user_id:
            raise ValueError("Apikey not found")
        if name:
            api_key.name = name
        if key:
            validate_key_format(api_key.name, key)
            api_key.key = encrypt_value(key)
        self.db.commit()
        return api_key

    def delete(self, id: str, user_id: str)-> bool:
        api_key = self.get_apikey(id)
        if not api_key:
            raise ValueError("Api Key not found")
        if api_key.user_id != user_id:
            raise ValueError("Api Key not found")

        self.db.delete(api_key)
        self.db.commit()
        return True


        
    

        