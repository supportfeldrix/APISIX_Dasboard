# APISIX Dashboard — UAT

A custom dashboard for managing Apache APISIX routes, services, upstreams, consumers, plugins, SSL certificates, and monitoring pod metrics. Built with FastAPI (backend) and React + Vite (frontend).

---

## Prerequisites

| Tool       | Minimum Version |
|------------|-----------------|
| Python     | 3.11+           |
| Node.js    | 18+             |
| npm        | 9+              |
| Docker     | 24+ (optional, for containerised deployment) |

---

## Backend Setup

```bash
cd backend

# Create a virtual environment (recommended)
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and fill in the required values (see Environment Variables below)

# Run the development server
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

The frontend will be available at `http://localhost:5173`. The Vite dev server proxies `/api` requests to `http://localhost:8000` automatically.

---

## Environment Variables

All environment variables are defined in `backend/.env.example`. Copy it to `backend/.env` and fill in the values:

| Variable                  | Required | Description                                              |
|---------------------------|----------|----------------------------------------------------------|
| `JWT_SECRET`              | **Yes**  | Secret key for signing JWT tokens                        |
| `JWT_ALGORITHM`           | No       | JWT algorithm (default: `HS256`)                         |
| `JWT_EXPIRY_MINUTES`      | No       | Token expiry in minutes (default: `30`)                  |
| `APISIX_ADMIN_BASE_URL`   | **Yes**  | Base URL of the APISIX Admin API (e.g. `https://apisix-admin:9180`) |
| `APISIX_ADMIN_KEY`        | **Yes**  | API key for APISIX Admin API authentication              |
| `APISIX_ADMIN_VERIFY_SSL` | No       | Set to `false` to disable TLS verification (default: `true`) |
| `APISIX_ADMIN_TIMEOUT`    | No       | Timeout in seconds for Admin API calls (default: `10`)   |
| `APISIX_METRICS_URL`      | **Yes**  | URL of the Prometheus metrics endpoint                   |
| `APISIX_METRICS_TIMEOUT`  | No       | Timeout in seconds for metrics fetch (default: `10`)     |
| `DATABASE_URL`            | No       | SQLAlchemy database URL (default: `sqlite:///./apisix_dashboard.db`) |
| `CORS_ORIGINS`            | No       | Comma-separated allowed origins (default: `http://localhost:5173`) |
| `ROOT_PATH`               | No       | Root path prefix for reverse-proxy deployments           |
| `LOG_LEVEL`               | No       | Logging level (default: `INFO`)                          |

---

## Running Tests

### Backend Tests

```bash
cd backend
pytest
```

Run only property-based tests:

```bash
cd backend
pytest -m property
```

Run with the CI Hypothesis profile (100 examples):

```bash
cd backend
pytest --hypothesis-profile=ci
```

### Frontend Tests

```bash
cd frontend
npm test -- --run
```

---

## Docker Deployment

Build and start all services using Docker Compose:

```bash
docker-compose up --build
```

This starts:
- **backend** on port `8000`
- **frontend** (nginx) on port `8080`

To stop:

```bash
docker-compose down
```

---

## Login Credentials

On first startup, the backend seeds a default admin user:

| Username | Password    | Role  |
|----------|-------------|-------|
| `admin`  | `N03ntry#`  | admin |

> **Important:** Change the default password after first login in production environments.

---

## Project Structure

```
UAT/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI application entry point
│   │   ├── config.py          # Pydantic settings
│   │   ├── database.py        # SQLAlchemy setup
│   │   ├── models/            # ORM models
│   │   ├── schemas/           # Pydantic request/response models
│   │   ├── routers/           # API route handlers
│   │   ├── services/          # Business logic
│   │   └── utils/             # Helpers (YAML converter, PEM validator)
│   ├── tests/                 # pytest unit & property-based tests
│   ├── requirements.txt       # Python dependencies
│   ├── .env.example           # Environment variable template
│   └── Dockerfile             # Backend container image
├── frontend/
│   ├── src/
│   │   ├── api/               # Axios client
│   │   ├── components/        # Shared UI components
│   │   ├── hooks/             # Custom React hooks
│   │   ├── pages/             # Page components
│   │   ├── store/             # Zustand state management
│   │   └── App.jsx            # Router and layout
│   ├── package.json           # Node.js dependencies
│   └── vite.config.js         # Vite configuration with API proxy
├── nginx/
│   └── nginx.conf             # Nginx config for production frontend
├── docker-compose.yml         # Multi-service orchestration
└── README.md                  # This file
```

---

## Key Files Verification

All required project files have been verified to exist:

- ✅ `backend/requirements.txt` — Python dependencies (FastAPI, SQLAlchemy, httpx, etc.)
- ✅ `backend/.env.example` — Environment variable template with all required keys
- ✅ `backend/Dockerfile` — Python 3.11-slim based container image
- ✅ `docker-compose.yml` — Backend + Frontend service definitions
- ✅ `frontend/package.json` — React, Vite, Tailwind, Zustand, Recharts, Monaco Editor
- ✅ `frontend/vite.config.js` — Vite dev server with `/api` proxy to localhost:8000
