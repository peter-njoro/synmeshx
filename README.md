# SynMeshX

SynMeshX is a sophisticated platform for seamless data and context synchronization between AI agents, tools, and projects through a secure, modular protocol. It provides a centralized hub where multiple AI systems can coordinate, share state, and maintain synchronized context across distributed environments.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Running the Application](#running-the-application)
- [API Documentation](#api-documentation)
- [Database Schema](#database-schema)
- [Development](#development)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

## Overview

SynMeshX solves the problem of coordination and state synchronization in multi-agent AI systems. In complex scenarios where multiple AI agents, LLMs, and tools need to work together, maintaining consistent context and coordinating their actions becomes challenging. SynMeshX provides:

- **Centralized Project Management**: Create and organize projects that serve as containers for synchronized data
- **Real-time Mesh Synchronization**: Use Redis pub/sub for low-latency updates across connected agents
- **Secure Authentication**: JWT-based authentication with role-based access control
- **RESTful API**: Clean, well-documented endpoints for project and sync management
- **Web Dashboard**: Next.js-based frontend for managing projects and monitoring sync status

## Key Features

### 1. **Project Management**
- Create, read, update, and delete projects
- Organize AI agents and tools within project contexts
- Track project metadata and configurations
- Manage project-specific resources and permissions

### 2. **Real-time Synchronization**
- Redis-backed pub/sub system for instant mesh updates
- Event-driven architecture for efficient state propagation
- Configurable sync policies and conflict resolution
- Automatic mesh manifest generation

### 3. **Security & Authentication**
- JWT token-based authentication
- Password hashing with bcrypt
- Secure API endpoints with role-based authorization
- Email validation for user accounts

### 4. **Vector Support**
- pgvector integration for semantic search and embeddings
- Support for AI-powered similarity queries
- Scalable vector storage and retrieval

### 5. **Monitoring & Logging**
- Real-time mesh listener for tracking updates
- Comprehensive logging and debugging support
- Health checks for all system components

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                      │
│              React UI + TailwindCSS + Shadcn-UI             │
│          - Project Dashboard                                │
│          - Sync Timeline Visualization                      │
│          - Real-time Status Monitoring                      │
└─────────────────┬───────────────────────────────────────────┘
                  │ HTTP/HTTPS
┌─────────────────▼───────────────────────────────────────────┐
│                   FastAPI Backend                            │
├─────────────────────────────────────────────────────────────┤
│ API Routes                                                  │
│  ├─ /api/v1/auth         - Authentication & Authorization   │
│  ├─ /api/v1/projects     - Project CRUD Operations          │
│  └─ /api/v1/sync         - Mesh Synchronization             │
├─────────────────────────────────────────────────────────────┤
│ Core Services                                               │
│  ├─ MeshManager         - Mesh manifest generation          │
│  ├─ MeshListener        - Real-time update monitoring       │
│  └─ Security            - Auth & encryption                 │
├─────────────────────────────────────────────────────────────┤
│ Data Layer                                                  │
│  ├─ SQLAlchemy ORM      - PostgreSQL interface              │
│  ├─ Alembic             - Database migrations               │
│  └─ Pydantic Schemas    - Data validation                   │
└──┬──────────────┬────────────────────────┬──────────────────┘
   │              │                        │
   ▼              ▼                        ▼
┌─────────┐  ┌──────────┐            ┌──────────┐
│PostgreSQL│  │  Redis   │            │ pgvector │
│Database  │  │  Pub/Sub │            │Embeddings│
└─────────┘  └──────────┘            └──────────┘
```

## Technology Stack

### Backend
- **Framework**: FastAPI 0.100+
- **Server**: Uvicorn (ASGI)
- **Database**: PostgreSQL 16 + pgvector
- **ORM**: SQLAlchemy 2.0+
- **Migrations**: Alembic
- **Real-time**: Redis 7 (Async pub/sub)
- **Auth**: Python-Jose + Passlib + Bcrypt
- **LLM Integration**: LangChain
- **API Validation**: Pydantic

### Frontend
- **Framework**: Next.js 14.2.3
- **UI**: React 18.2 + TypeScript
- **Styling**: TailwindCSS
- **Components**: Shadcn-UI
- **HTTP**: Axios
- **Animations**: Framer Motion
- **Charts**: Recharts

### DevOps
- **Containerization**: Docker + Docker Compose
- **Python Package Manager**: uv (modern, fast)
- **CI/CD**: Ready for GitHub Actions integration

## Project Structure

```
synmeshx/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI application entry
│   │   ├── models/                 # SQLAlchemy ORM models
│   │   │   ├── user.py
│   │   │   ├── project.py
│   │   │   └── sync.py
│   │   ├── schemas/                # Pydantic validation schemas
│   │   │   ├── user.py
│   │   │   ├── project.py
│   │   │   └── sync.py
│   │   ├── api/
│   │   │   └── routes/             # API endpoint definitions
│   │   │       ├── auth.py         # Authentication endpoints
│   │   │       ├── projects.py     # Project management
│   │   │       ├── sync.py         # Synchronization
│   │   │       └── context.py      # Context operations
│   │   ├── core/
│   │   │   ├── config.py           # Configuration management
│   │   │   ├── database.py         # Database connection
│   │   │   ├── redis.py            # Redis client setup
│   │   │   ├── security.py         # Auth & encryption
│   │   │   └── mesh_manager.py     # Mesh manifest generation
│   │   ├── services/
│   │   │   └── mesh_listener.py    # Real-time update listener
│   │   └── utils/
│   │       ├── embeddings.py       # Vector embedding utilities
│   │       └── redis_utils.py      # Redis helper functions
│   ├── alembic/                    # Database migration scripts
│   │   ├── env.py
│   │   ├── versions/               # Migration files
│   │   └── script.py.mako
│   ├── pyproject.toml              # Python dependencies (uv)
│   ├── requirements.txt            # Alternative requirements file
│   ├── Dockerfile                  # Container image definition
│   ├── entrypoint.sh              # Container startup script
│   └── alembic.ini                # Alembic configuration
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx          # Root layout component
│   │   │   ├── page.tsx            # Home page
│   │   │   └── projects/
│   │   │       └── page.tsx        # Projects page
│   │   └── components/
│   │       ├── ProjectCard.tsx     # Project display component
│   │       └── SyncTimeline.tsx    # Sync timeline visualization
│   ├── package.json                # Node dependencies
│   ├── tsconfig.json               # TypeScript configuration
│   ├── next.config.mjs             # Next.js configuration
│   └── Dockerfile                  # Frontend container image
│
├── docker-compose.yml              # Multi-container orchestration
├── .env.example                    # Environment variables template
└── README.md                        # This file
```

## Getting Started

### Prerequisites

- **Docker** and **Docker Compose** (recommended for full setup)
- Or manually:
  - Python 3.11+
  - Node.js 18+
  - PostgreSQL 16
  - Redis 7

### Installation

#### Option 1: Docker Compose (Recommended)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/peter-njoro/synmeshx.git
   cd synmeshx
   ```

2. **Create environment file**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Build and start services**:
   ```bash
   docker compose up --build
   ```

4. **Access the application**:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

#### Option 2: Manual Setup

**Backend**:
```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# or with uv:
uv sync

# Run migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --reload
```

**Frontend**:
```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### Configuration

Create a `.env` file in the project root with the following variables:

```env
# Database
POSTGRES_USER=synmeshx
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=synmeshx
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# Security
SECRET_KEY=your-super-secret-key-change-this-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Application
DEBUG=False
PROJECT_NAME=SynMeshX
API_V1_STR=/api/v1
```

### Running the Application

**With Docker Compose**:
```bash
docker compose up
```

**Without Docker** (with services running locally):

Terminal 1 - Backend:
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Terminal 2 - Frontend:
```bash
cd frontend
npm run dev
```

## API Documentation

### Authentication

#### Register User
```
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secure_password",
  "username": "username"
}
```

#### Login
```
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=user@example.com&password=secure_password
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### Projects

#### Create Project
```
POST /api/v1/projects
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "My AI Project",
  "description": "Project description",
  "config": {}
}
```

#### List Projects
```
GET /api/v1/projects
Authorization: Bearer <token>
```

#### Get Project Details
```
GET /api/v1/projects/{project_id}
Authorization: Bearer <token>
```

#### Update Project
```
PUT /api/v1/projects/{project_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Updated Name",
  "description": "Updated description"
}
```

#### Delete Project
```
DELETE /api/v1/projects/{project_id}
Authorization: Bearer <token>
```

### Sync

#### Trigger Mesh Sync
```
POST /api/v1/sync/trigger
Authorization: Bearer <token>
Content-Type: application/json

{
  "project_id": "uuid",
  "data": {}
}
```

Full API documentation is available at `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc` (ReDoc).

## Database Schema

The database includes the following main tables:

- **users**: User accounts with authentication credentials
- **projects**: Project containers for mesh synchronization
- **syncs**: Synchronization events and state snapshots
- **embeddings**: Vector embeddings for semantic search

Database migrations are managed by Alembic and can be found in `backend/alembic/versions/`.

## Development

### Backend Development

**Running Tests**:
```bash
cd backend
pytest
```

**Code Formatting**:
```bash
# Install development tools
pip install black flake8 isort

# Format code
black app/
isort app/

# Check code quality
flake8 app/
```

**Database Migrations**:
```bash
# Create a new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Frontend Development

**Build for Production**:
```bash
cd frontend
npm run build
npm start
```

**Code Quality**:
```bash
npm run lint
```

## Deployment

### Production Deployment with Docker

1. **Build production images**:
   ```bash
   docker compose build
   ```

2. **Update environment variables** for production (secure secrets, appropriate hosts)

3. **Deploy** to your hosting platform (AWS, DigitalOcean, Heroku, etc.)

### Environment Considerations

- Set `DEBUG=False` in production
- Use strong, randomly generated `SECRET_KEY`
- Configure CORS origins appropriately
- Use HTTPS/TLS for all communications
- Set up proper logging and monitoring
- Configure database backups
- Use managed Redis service or secure Redis deployment

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under a Proprietary License. See the LICENSE file for details.
