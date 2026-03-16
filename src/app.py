"""
Agent47 FastAPI Application.

Run with: uvicorn src.app:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.database import create_tables
from src.domain.auth.router import router as auth_router
from src.domain.auth.session import Session as _Session  # noqa: F401 — registers the model with Base
from src.domain.repositories.router import router as repos_router
from src.domain.webhooks.router import router as webhooks_router
from src.domain.contracts.router import router as contracts_router


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

# CORS — allow the React frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://595e-102-90-97-165.ngrok-free.app"],  # Tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Register domain routers ---
app.include_router(auth_router)
app.include_router(repos_router)
app.include_router(webhooks_router)
app.include_router(contracts_router)


@app.get("/")
def root():
    """Health check / welcome endpoint."""
    return {
        "name": "Agent47",
        "status": "online",
        "message": "The bug assassin is ready for contracts.",
    }
