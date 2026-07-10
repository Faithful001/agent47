import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import time
import threading
# from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
# from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chat_models import init_chat_model
from langchain_core.globals import set_llm_cache
from langchain_community.cache import SQLiteCache
from langchain_openai import ChatOpenAI
from langchain_core.rate_limiters import InMemoryRateLimiter

# --- LLM Caching ---
cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "llm_cache.db")
os.makedirs(os.path.dirname(cache_path), exist_ok=True)
set_llm_cache(SQLiteCache(database_path=cache_path))

# --- Rate Limiting (Throttling) ---
class ThrottledChatModel:
    """Wrapper that ensures a minimum delay between requests to avoid 429s."""
    _last_call_time = 0
    _lock = threading.Lock()
    _min_delay = 8.0  # Seconds (Safe for 5 RPM limit)
    _request_count = 0  # Track total LLM requests

    def __init__(self, model):
        self.model = model

    def invoke(self, *args, **kwargs):
        with self._lock:
            self.__class__._request_count += 1
            print(f"[ThrottledChatModel] Initiating LLM Request #{self.__class__._request_count}")
            
            elapsed = time.time() - self._last_call_time
            if elapsed < self._min_delay:
                wait_time = self._min_delay - elapsed
                print(f"[ThrottledChatModel] Rate limiting: waiting {wait_time:.2f}s before sending request...")
                time.sleep(wait_time)
            
            result = self.model.invoke(*args, **kwargs)
            self.__class__._last_call_time = time.time()
            return result

    def __getattr__(self, name):
        return getattr(self.model, name)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- GitHub OAuth ---
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
WEBHOOK_CALLBACK_URL = os.getenv(
    "WEBHOOK_CALLBACK_URL", "http://localhost:8000/webhooks/github"
)
GITHUB_REDIRECT_URI = os.getenv(
    "GITHUB_REDIRECT_URI", "http://localhost:8000/auth/callback"
)

# --- Workspace ---
WORKSPACE_BASE_DIR = os.getenv("WORKSPACE_BASE_DIR", "/tmp/agent47_workspaces")

# --- JWT / Auth ---
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_EXPIRY_DAYS = int(os.getenv("JWT_EXPIRY_DAYS", "7"))

# --- Frontend ---
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.25,  # 15 RPM
    check_every_n_seconds=0.1,
    max_bucket_size=5,
)

basic_model = ThrottledChatModel(ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    model="deepseek/deepseek-chat",
    temperature=0.0,
    max_tokens=8192,
    rate_limiter=rate_limiter
))

advanced_model = ThrottledChatModel(ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    model="deepseek/deepseek-chat",
    temperature=0.0,
    max_tokens=8192,
    rate_limiter=rate_limiter
))

def get_user_models(
    user_api_key: str | None = None,
    user_id: str | None = None
) -> tuple[ThrottledChatModel, ThrottledChatModel]:
    """Dynamically get LLM models. If user_id is provided, loads the active key (is_active=True)
    from the database and instantiates the chat model with its configured model and temperature."""
    
    # Defaults
    provider = "openrouter"
    model_name = "gemini-1.5-pro"
    temp = 0.2
    resolved_key = None

    if user_id:
        from agent47.config.database import SessionLocal
        from agent47.domain.apikey.model import ApiKey
        from agent47.utils.crypto import decrypt_value

        with SessionLocal() as db:
            # 1. Look for active key
            active_key = db.query(ApiKey).filter(ApiKey.user_id == user_id, ApiKey.is_active == True).first()
            
            # 2. If no active key found, fall back to first key
            if not active_key:
                active_key = db.query(ApiKey).filter(ApiKey.user_id == user_id).first()
                
            if active_key:
                provider = active_key.name.lower()
                model_name = active_key.model or "gemini-1.5-pro"
                temp = active_key.temperature if active_key.temperature is not None else 0.2
                try:
                    resolved_key = decrypt_value(active_key.key)
                except Exception:
                    pass

    # Fallback to legacy raw user_api_key if no user_id / active key found
    if not resolved_key and user_api_key:
        provider = "openrouter"
        model_name = "deepseek-coder"
        temp = 0.0
        resolved_key = user_api_key

    # Resolve system fallback keys only if no user_id was provided (e.g. system default tasks)
    if not resolved_key and not user_id:
        if provider == "openrouter":
            resolved_key = os.getenv("OPENROUTER_API_KEY")
        elif provider == "google":
            resolved_key = os.getenv("GOOGLE_API_KEY")
        elif provider == "openai":
            resolved_key = os.getenv("OPENAI_API_KEY")
        elif provider == "anthropic":
            resolved_key = os.getenv("ANTHROPIC_API_KEY")
        elif provider == "groq":
            resolved_key = os.getenv("GROQ_API_KEY")

    # If still no key, fall back to global default models
    if not resolved_key:
        return basic_model, advanced_model

    # 3. Instantiate LangChain model based on provider
    try:
        if provider == "openrouter":
            # Map frontend model ID to OpenRouter model path
            model_map = {
                "gemini-1.5-pro": "google/gemini-pro-1.5",
                "claude-3-5-sonnet": "anthropic/claude-3.5-sonnet",
                "gpt-4o": "openai/gpt-4o",
                "deepseek-coder": "deepseek/deepseek-coder",
            }
            resolved_model_id = model_map.get(model_name, "deepseek/deepseek-chat")
            
            chat_model = ChatOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=resolved_key,
                model=resolved_model_id,
                temperature=temp,
                max_tokens=8192,
                rate_limiter=rate_limiter
            )
        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            resolved_model_id = "gemini-1.5-pro" if model_name == "gemini-1.5-pro" else "gemini-1.5-flash"
            chat_model = ChatGoogleGenerativeAI(
                model=resolved_model_id,
                google_api_key=resolved_key,
                temperature=temp,
                rate_limiter=rate_limiter
            )
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            resolved_model_id = "claude-3-5-sonnet-20240620"
            chat_model = ChatAnthropic(
                model=resolved_model_id,
                anthropic_api_key=resolved_key,
                temperature=temp,
                rate_limiter=rate_limiter
            )
        elif provider == "openai":
            chat_model = ChatOpenAI(
                model="gpt-4o",
                api_key=resolved_key,
                temperature=temp,
                rate_limiter=rate_limiter
            )
        elif provider == "groq":
            chat_model = ChatOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=resolved_key,
                model="llama3-70b-8192" if model_name == "gemini-1.5-pro" else "llama3-8b-8192",
                temperature=temp,
                rate_limiter=rate_limiter
            )
        else:
            return basic_model, advanced_model

        throttled = ThrottledChatModel(chat_model)
        return throttled, throttled

    except Exception as e:
        print(f"Error initializing user custom model ({provider}): {e}. Falling back to default system models.")
        return basic_model, advanced_model

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
