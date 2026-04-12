from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent47.common.middleware.response_interceptor import ResponseInterceptor

from agent47.config.config import basic_model, advanced_model
from agent47.config.database import create_tables

from agent47.domain.auth.router import router as auth_router
from agent47.domain.repository.router import router as repo_router
from agent47.domain.webhook.router import router as webhook_router
from agent47.domain.contract.router import router as contract_router
from agent47.domain.build.router import router as build_router
from agent47.domain.websocket.router import router as websocket_router
import logging
import os

# --- Configure Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Create database tables on startup."""
    create_tables()
    yield


app = FastAPI(
    title="Agent47 API",
    description=(
        "Agent47: A multi-agent system that autonomously finds, "
        "reproduces, and fixes bugs via GitHub integration."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

webhook_url = os.getenv("WEBHOOK_CALLBACK_URL").replace("/webhooks/github", "")

# CORS — allow the React frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", webhook_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standardize all JSON responses
app.add_middleware(ResponseInterceptor)

# --- Register domain routers ---
app.include_router(auth_router)
app.include_router(repo_router)
app.include_router(webhook_router)
app.include_router(contract_router)
app.include_router(build_router)
app.include_router(websocket_router)


@app.get("/")
def root():
    """Health check / welcome endpoint."""
    return {
        "name": "Agent47",
        "status": "online",
        "message": "The bug assassin is ready for contract.",
    }


if __name__ == "__main__":
    logger.info("Agent47 initialized.")
    
    basic_model_name = getattr(basic_model, 'model_id', getattr(basic_model, 'model', 'Unknown'))
    advanced_model_name = getattr(advanced_model, 'model_id', getattr(advanced_model, 'model', 'Unknown'))
    
    logger.info(f"Handler model: {basic_model_name}")
    logger.info(f"Operative model: {advanced_model_name}")
    
    import uvicorn
    uvicorn.run("agent47.main:app", host="127.0.0.1", port=8000, reload=True)
