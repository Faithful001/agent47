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
GITHUB_REDIRECT_URI = os.getenv(
    "GITHUB_REDIRECT_URI", "http://localhost:8000/auth/callback"
)

# --- Workspace ---
WORKSPACE_BASE_DIR = os.getenv("WORKSPACE_BASE_DIR", "/tmp/agent47_workspaces")

basic_model = init_chat_model(
    model="gemini-3-flash-preview",
    model_provider="google_genai",
    temperature=0.5,
    timeout=10,
    max_tokens=1000
)

advanced_model = init_chat_model(
    model="gemini-3.1-pro",
    model_provider="google_genai",
    temperature=0.5,
    timeout=10,
    max_tokens=1000
)
