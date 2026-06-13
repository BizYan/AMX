# Avenir Matrix (AMX)

A comprehensive AI-powered workbench platform for consultants, enabling intelligent document management, knowledge retrieval, and workflow automation. Built with modern full-stack technologies including FastAPI, Next.js, and ARQ workers.

## Project Description

Avenir Matrix (AMX) is an enterprise-grade platform designed for consulting professionals to:

- **Manage Documents**: Create, edit, and organize client deliverables across 8 specialized document types (meeting notes, proposals, contracts, reports, etc.)
- **Knowledge Retrieval**: Leverage RAG (Retrieval-Augmented Generation) and GraphRAG for intelligent knowledge discovery
- **Workflow Automation**: Automate repetitive tasks through an agent-based workflow system with customizable skills and tools
- **Collaborate Effectively**: Work with team members with role-based access control and real-time collaboration features
- **Track Changes**: Maintain complete audit trails with change request management and traceability matrices

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **API** | FastAPI (Python 3.12+) | High-performance async REST API |
| **Frontend** | Next.js 14 + React 18 | Server-side rendered React UI |
| **Worker** | ARQ | Async job queue processing |
| **Database** | PostgreSQL 16 + pgvector | Relational + vector storage |
| **Cache** | Redis 7 | Caching and job queue |
| **Container** | Docker Compose | Local development & deployment |

## Prerequisites

Before running this project, ensure you have:

- **Docker Desktop** (v20.10+) with Docker Compose
- **pnpm** (v8+) for frontend package management
- **uv** for Python package management (installed automatically in containers)
- **Python 3.12+** (for local development outside Docker)
- **Node.js 20+** (for local frontend development)

## Quick Start

### 1. Clone and Configure

```bash
# Clone the repository
git clone https://github.com/BizYan/AMX.git
cd AMX

# Copy environment file
cp infra/env.example .env

# Edit .env with your configuration
```

### 2. Start with Docker Compose

```bash
cd infra
docker compose up -d
```

This starts all services:
- **PostgreSQL** on port 5432 (with pgvector extension)
- **Redis** on port 6379
- **API** on port 8000
- **Worker** (background job processing)
- **Web** on port 3000

### 3. Verify Deployment

```bash
# Check service health
docker compose ps

# View logs
docker compose logs -f api

# Run deployment check script
pwsh infra/scripts/check-deploy.ps1
```

## Environment Variables Reference

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string | postgresql+asyncpg://... |
| `REDIS_URL` | Yes | Redis connection string | redis://redis:6379/0 |
| `ARQ_REDIS_URL` | Yes | ARQ worker Redis URL | redis://redis:6379/1 |
| `JWT_SECRET_KEY` | Yes | Secret for JWT signing | - |
| `JWT_ALGORITHM` | No | JWT algorithm | HS256 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | No | Token expiry | 30 |
| `BOOTSTRAP_ADMIN_EMAIL` | Yes | Initial admin email | admin@consultant.local |
| `BOOTSTRAP_ADMIN_PASSWORD` | Yes | Initial admin password | - |
| `OPENAI_API_KEY` | Yes | LLM provider API key | - |
| `OPENAI_BASE_URL` | No | LLM provider base URL | https://api.minimax.chat/v1 |
| `CORS_ORIGINS` | No | Allowed CORS origins | localhost:3000 |
| `LOG_LEVEL` | No | Logging level | INFO |

## Directory Structure

```
AMX/
├── apps/
│   ├── api/                    # FastAPI backend
│   │   ├── app/
│   │   │   ├── api/v1/        # API routers (identity, projects, etc.)
│   │   │   ├── core/          # Settings, security, config
│   │   │   ├── db/             # Database sessions, bootstrap
│   │   │   ├── domains/        # Business logic domains
│   │   │   │   ├── agent/      # Agent runtime & workflows
│   │   │   │   ├── change/     # Change request management
│   │   │   │   ├── collaboration/ # Real-time collaboration
│   │   │   │   ├── documents/  # Document platform (8 types)
│   │   │   │   ├── export/     # Export handlers
│   │   │   │   ├── identity/   # Auth, users, tenants
│   │   │   │   ├── integrations/ # Third-party integrations
│   │   │   │   ├── knowledge/  # RAG, GraphRAG, lineage
│   │   │   │   ├── ops/        # Operations & monitoring
│   │   │   │   ├── projects/   # Project management
│   │   │   │   ├── providers/  # LLM provider gateway
│   │   │   │   └── templates/  # Document templates
│   │   │   ├── models/         # SQLAlchemy models
│   │   │   ├── services/       # External service clients
│   │   │   └── workers/        # ARQ worker setup
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   └── tests/              # Unit & integration tests
│   ├── web/                    # Next.js frontend
│   │   ├── src/
│   │   │   ├── app/            # Next.js App Router pages
│   │   │   ├── components/     # React components
│   │   │   └── lib/            # Utilities & API client
│   │   ├── Dockerfile
│   │   └── package.json
│   └── worker/                 # ARQ background worker
│       ├── app/
│       │   └── workers/        # Worker task definitions
│       ├── Dockerfile
│       └── pyproject.toml
├── packages/
│   ├── contracts/              # API schemas & type contracts
│   └── shared/                 # Shared utilities
├── infra/
│   ├── docker-compose.yml      # Full stack orchestration
│   ├── env.example             # Environment template
│   ├── init-db.sql             # Database initialization
│   └── scripts/               # Operational scripts
│       └── check-deploy.ps1    # Deployment verification
├── tests/
│   └── e2e/                    # End-to-end tests
├── docs/
│   └── superpowers/            # Feature documentation
├── pyproject.toml              # Python project config
└── README.md                   # This file
```

## OCI Ubuntu Deployment

### Prerequisites

- Ubuntu 20.04+ (tested on 22.04)
- Docker Engine 20.10+
- Docker Compose v2
- Minimum 4GB RAM, 40GB storage

### Deployment Steps

1. **Install Docker:**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

2. **Clone and configure:**
```bash
git clone https://github.com/BizYan/AMX.git
cd AMX
cp infra/env.example .env
sudo nano .env  # Configure all required variables
```

3. **Deploy:**
```bash
cd infra
docker compose up -d
```

4. **Verify:**
```bash
docker compose ps
curl http://localhost:8000/health
```

5. **Reverse Proxy (optional):**
```bash
# Install nginx
sudo apt install nginx

# Configure for reverse proxy on ports 80/443
sudo nano /etc/nginx/sites-available/consultant-ai
```

## API Documentation

Once running, access the API documentation at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Monitoring & Observability

The platform includes:

- **Health endpoints**: `/health` for container orchestration
- **Metrics**: Integrated with observability components
- **Quota management**: Per-user, per-tenant resource limits
- **Cache statistics**: Redis-based caching with circuit breakers

## License

No license is granted. All rights reserved. See `SECURITY.md` for security reporting.

## Support

For architecture, product, development, and operations documentation, see `/docs/`.
