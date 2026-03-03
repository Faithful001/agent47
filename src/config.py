"""
Shared configuration and model initialization for Agent47.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from langchain.chat_models import init_chat_model


GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# The Handler's model — fast and cheap, used for routing and analysis
basic_model = init_chat_model(
    model="gemini-3-flash-preview",
    model_provider="google_genai",
    temperature=0.5,
    timeout=10,
    max_tokens=1000
)

# The Operative's model — smarter, used for writing code fixes
advanced_model = init_chat_model(
    model="gemini-3.1-pro",
    model_provider="google_genai",
    temperature=0.5,
    timeout=10,
    max_tokens=1000
)
