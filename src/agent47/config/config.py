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

# --- LLM Caching ---
# Prevents redundant API calls by storing responses in a local SQLite DB.
cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "llm_cache.db")
os.makedirs(os.path.dirname(cache_path), exist_ok=True)
set_llm_cache(SQLiteCache(database_path=cache_path))

# --- Rate Limiting (Throttling) ---
class ThrottledChatModel:
    """Wrapper that ensures a minimum delay between requests to avoid 429s."""
    _last_call_time = 0
    _lock = threading.Lock()
    _min_delay = 8.0  # Seconds (Safe for 5 RPM limit)

    def __init__(self, model):
        self.model = model

    def invoke(self, *args, **kwargs):
        with self._lock:
            elapsed = time.time() - self._last_call_time
            if elapsed < self._min_delay:
                wait_time = self._min_delay - elapsed
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

# In config.py

# Option 1: Groq (very fast)
basic_model = ChatOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",   # or "qwen3-72b" etc.
    temperature=0.5,
    max_tokens=8192,
)

# Option 2: OpenRouter (best for free + fallback)
advanced_model = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    model="openrouter/free",                    # auto-selects best free model
    # or specific: "deepseek/deepseek-r1:free", "meta-llama/llama-3.3-70b-instruct:free"
    temperature=0.5,
)

# basic_model = ThrottledChatModel(init_chat_model(
#     model="gemini-2.5-flash",
#     model_provider="google_genai",
#     temperature=0.5,
#     timeout=60,
#     max_tokens=8192
# ))

# advanced_model = ThrottledChatModel(init_chat_model(
#     model="gemini-2.5-flash",
#     model_provider="google_genai",
#     temperature=0.5,
#     timeout=120,
#     max_tokens=8192
# ))

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "uE_jK_d-zU2-nQqzYgV06b9N3m-B5QO__6rC_oXl1h0=")
