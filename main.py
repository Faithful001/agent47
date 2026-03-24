from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infra.middleware.response_interceptor import ResponseInterceptor

from src.config.config import basic_model, advanced_model
from src.config.database import create_tables

from src.domain.auth.router import router as auth_router
from src.domain.repository.router import router as repo_router
from src.domain.webhook.router import router as webhook_router
from src.domain.contract.router import router as contract_router
from src.domain.build.router import router as build_router
from src.domain.websocket.router import router as websocket_router


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
    allow_origins=["http://localhost:3000", "https://595e-102-90-97-165.ngrok-free.app"],
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
    print("Agent47 initialized.")
    print(f"Handler model: {basic_model.model}")
    print(f"Operative model: {advanced_model.model}")
    
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
