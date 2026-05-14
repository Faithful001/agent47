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
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY"),
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0.5,
    max_tokens=8192,
    rate_limiter=rate_limiter
))

advanced_model = ThrottledChatModel(ChatOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",
    temperature=0.5,
    max_tokens=8192,
    rate_limiter=rate_limiter
))

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
