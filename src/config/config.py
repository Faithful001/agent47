import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from langchain.chat_models import init_chat_model


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

basic_model = init_chat_model(
    model="gemini-3-flash-preview",
    model_provider="google_genai",
    temperature=0.5,
    timeout=60,
    max_tokens=8192
)

advanced_model = init_chat_model(
    model="gemini-3-flash-preview",
    model_provider="google_genai",
    temperature=0.5,
    timeout=120,
    max_tokens=8192
)

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "uE_jK_d-zU2-nQqzYgV06b9N3m-B5QO__6rC_oXl1h0=")
