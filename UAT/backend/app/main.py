"""FastAPI application factory."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .database import engine, Base, SessionLocal

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Create all database tables
    from .models.audit_log import AuditLog  # noqa: F401 -- ensure table registered
    from .models.alert_rule import AlertRule  # noqa: F401 -- ensure table registered
    from .models.notification_log import NotificationLog  # noqa: F401 -- ensure table registered
    from .models.version_check import VersionCheckResult  # noqa: F401 -- ensure table registered
    from .models.escalation_state import EscalationState  # noqa: F401 -- ensure table registered
    from .models.escalation_log import EscalationLog  # noqa: F401 -- ensure table registered
    from .models.controlm_settings import ControlMSettings  # noqa: F401 -- ensure table registered
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")

    # Migrate: add columns to existing tables if missing (create_all only creates tables)
    from sqlalchemy import text, inspect
    db_migrate = SessionLocal()
    try:
        inspector = inspect(engine)
        existing_cols = {col["name"] for col in inspector.get_columns("alert_rules")}
        migrations = [
            ("notify_controlm", "ALTER TABLE alert_rules ADD COLUMN notify_controlm INTEGER NOT NULL DEFAULT 0"),
            ("critical", "ALTER TABLE alert_rules ADD COLUMN critical INTEGER NOT NULL DEFAULT 0"),
        ]
        for col_name, sql in migrations:
            if col_name not in existing_cols:
                db_migrate.execute(text(sql))
                db_migrate.commit()
                logger.info("Migrated: added column '%s' to alert_rules.", col_name)
    except Exception as exc:
        logger.warning("Migration check skipped or failed: %s", exc)
    finally:
        db_migrate.close()

    # Seed default admin user
    from .services.auth_service import seed_admin
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()

    # Start background notification scheduler
    from .services.background_scheduler import scheduler
    await scheduler.start()

    # Restore ControlM escalation state from database
    from .services.controlm_escalation_service import escalation_service
    await escalation_service.restore_state_on_startup()
    logger.info("ControlM escalation state restored.")

    logger.info("APISIX Dashboard backend started.")
    yield
    logger.info("APISIX Dashboard backend shutting down.")

    # Stop background notification scheduler
    await scheduler.stop()


app = FastAPI(
    title="APISIX Dashboard API",
    version="0.1.0",
    description="Custom APISIX management dashboard backend",
    root_path=settings.ROOT_PATH,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers (imported here to avoid circular imports)
from .routers import auth, proxy, metrics, pods, users, system, audit, backup  # noqa: E402
from .routers import notifications  # noqa: E402
from .routers import escalation  # noqa: E402
from .routers import logs  # noqa: E402
from .routers import ssl_upload  # noqa: E402

app.include_router(auth.router, prefix="/api")
app.include_router(proxy.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(pods.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(escalation.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(ssl_upload.router, prefix="/api")


@app.get("/health", tags=["health"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "apisix-dashboard"}
