# Agent47: Autonomous Multi-Agent Bug Assassin

Agent47 is an autonomous multi-agent system built to monitor GitHub repositories, catch CI/CD build failures, reproduce issues, and execute targeted code fixes inside isolated Docker sandboxes.

When a build fails or a developer mentions `@agent47` in a pull request comment, Agent47 analyzes the failure, identifies affected files, makes minimal precise code edits, runs tests, and pushes a fix branch with a complete pull request.

---

## Key Features

- **Multi-Agent Orchestration**: Built with LangGraph, combining a triage agent (The Handler) and a ReAct coding agent (The Operative).
- **Secure Docker Sandboxing**: Automatically packages projects using Railpack or base image detection to run code edits and unit tests in complete isolation.
- **GitHub Webhook Integration**: Listens for `check_suite`, `check_run`, `workflow_run`, and PR comment triggers (such as `@agent47`).
- **Bring Your Own Key (BYOK)**: Supports OpenRouter, Google Gemini, OpenAI, Anthropic Claude, and Groq with encrypted user key storage and custom model selection.
- **Custom Repository Guidelines**: Load per-repo constraints and custom test commands using a `.agent47.yaml` file in target repositories.
- **Real-Time Streaming**: Real-time progress updates and build logs streamed via WebSockets and backed by a Celery and Redis task queue.
- **LLM Throttling & Caching**: Smart request throttling and local SQLite caching to prevent API rate limits and reduce redundant calls.

---

## Architecture & Workflow

Agent47 runs a structured multi-stage state machine:

```mermaid
graph TD
    A[GitHub Event / Manual Contract] --> B[Setup Sandbox Container]
    B --> C[Handler Agent: Triage & File Detection]
    C --> D[Operative Agent: ReAct Code Edits & Test Execution]
    D -->|Tests Fail & Attempts < 5| D
    D -->|Tests Pass or Max Attempts| E[Sync Files Back to Workspace]
    E --> F[Teardown Sandbox]
    F --> G[Push Fix Branch & Report Outcome]
```

1. **Setup Sandbox**: Spins up an isolated Docker container with the target repository copied into `/workspace`.
2. **The Handler (Diana Burnwood)**: Uses a fast LLM model to examine the bug report or error log, scan repository file listings, and pinpoint relevant files.
3. **The Operative (Agent 47)**: A ReAct agent equipped with sandbox file inspection, string replacement, and command execution tools. It inspects code, applies targeted edits, runs verification commands, and evaluates output.
4. **Retry Loop**: If tests fail, the Operative analyzes the new error output and adjusts its approach (up to 5 attempts).
5. **Sync & Cleanup**: Once verified, modified files sync back to the local workspace, the sandbox container is safely destroyed, and a fix branch is created.

---

## Repository Structure

```text
agent47/
├── src/agent47/
│   ├── agents/            # LangGraph workflow, Handler, and Operative definitions
│   │   ├── graph.py       # Main state machine and node definitions
│   │   ├── handler.py     # Triage agent logic (Diana)
│   │   └── operative.py   # ReAct coding agent logic (Agent 47)
│   ├── common/            # Custom FastAPI middleware (response interceptor)
│   ├── config/            # Configuration, database connection, Redis, and model factories
│   ├── domain/            # Core business domains (auth, apikey, build, contract, repo, user, webhook, websocket)
│   ├── infra/             # Infrastructure components (Docker sandbox, Git service, Celery queue, WebSockets)
│   ├── utils/             # Encryption, Docker helpers, and class-based view utilities
│   ├── main.py            # FastAPI application entry point
│   └── state.py           # ContractState type definition for LangGraph
├── tests/                 # Unit tests for sandbox, API keys, and agent routines
├── docker-compose.yml     # Local services for PostgreSQL and Redis
├── nixpacks.toml          # Nixpacks environment configuration
├── pyproject.toml         # Poetry project configuration
├── requirements.txt       # Python package dependencies
└── start.sh               # Container entrypoint script launching Celery and Uvicorn
```

---

## Repository Customization with `.agent47.yaml`

Target repositories can include a `.agent47.yaml` file in their root directory to configure custom testing commands and project guidelines.

Example `.agent47.yaml`:

```yaml
test_command: "npm test"
rules:
  - "Do not modify files under the legacy/ directory."
  - "Always keep existing code formatting conventions intact."
  - "Do not add third-party dependencies without prior review."
```

---

## Getting Started

### Prerequisites

- **Python**: 3.11 or higher
- **Docker**: Docker Desktop or Docker Engine running locally
- **PostgreSQL**: Version 15 or higher
- **Redis**: Version 6 or higher

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/agent47.git
cd agent47
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory:

```env
# Database & Redis Configuration
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5435/agent47
REDIS_URL=redis://localhost:6380/0

# Security Secrets
JWT_SECRET_KEY=your-super-secret-jwt-key
ENCRYPTION_KEY=your-32-byte-fernet-encryption-key

# GitHub Integration
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
GITHUB_WEBHOOK_SECRET=your-github-webhook-secret
WEBHOOK_CALLBACK_URL=http://localhost:8000/api/v1/webhooks/github
GITHUB_REDIRECT_URI=http://localhost:8000/api/v1/auth/callback

# Default LLM Provider Keys
OPENROUTER_API_KEY=your-openrouter-api-key
GOOGLE_API_KEY=your-google-api-key

# Frontend Client URL
FRONTEND_URL=http://localhost:3000
```

### 3. Install Dependencies

Using Poetry:

```bash
poetry install
```

Or using pip:

```bash
pip install -r requirements.txt
```

### 4. Start Local Services

Start PostgreSQL and Redis containers using Docker Compose:

```bash
docker compose up -d
```

### 5. Run the Application

You can start the background Celery worker and FastAPI web server using the startup script:

```bash
chmod +x start.sh
./start.sh
```

Alternatively, run the processes in separate terminal sessions:

```bash
# Terminal 1: Celery Worker
PYTHONPATH=src celery -A agent47.infra.queue worker --loglevel=info --concurrency=1 --pool=solo

# Terminal 2: FastAPI Web Server
PYTHONPATH=src uvicorn agent47.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## API Documentation

Once the server is running, interactive API documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Key Endpoints

- **Authentication**: `/api/v1/auth/github` for GitHub OAuth login flow
- **Repositories**: `/api/v1/repositories/` to manage connected GitHub repositories
- **Contracts**: `/api/v1/contracts/` to submit and view bug repair contracts
- **Builds**: `/api/v1/builds/` to inspect detailed build logs and results
- **Webhooks**: `/api/v1/webhooks/github` for automated GitHub event handling
- **API Keys**: `/api/v1/apikeys/` to manage BYOK provider configurations
- **WebSockets**: `/api/v1/ws/contracts/{contract_id}` for streaming real-time progress updates

---

## Running Tests

Execute unit test suites using `pytest`:

```bash
pytest
```

---

## License

This project is licensed under the MIT License.
