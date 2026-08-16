"""
Brack API — Main application factory
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.config.settings import get_settings
from app.api.v1 import router as api_v1_router
from app.database import engine, Base
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.logging import LoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown events."""
    settings = get_settings()
    
    # Create database tables (handled by Alembic in production)
    # In dev, create tables directly for convenience
    if settings.BRACK_ENV == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Cleanup
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Brack API",
        description="Brack — Personal Git Hosting & AI Coding Platform",
        version="1.0.0",
        docs_url="/api/docs" if settings.BRACK_ENV == "development" else None,
        redoc_url="/api/redoc" if settings.BRACK_ENV == "development" else None,
        openapi_url="/api/openapi.json" if settings.BRACK_ENV == "development" else None,
        lifespan=lifespan,
    )

    # ── Middleware (order matters — outermost first) ──────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(LoggingMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(api_v1_router, prefix="/api/v1")

    # ── Health endpoints ──────────────────────────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health():
        return {"status": "ok", "service": "brack-api"}

    @app.get("/ready", tags=["System"])
    async def ready():
        return {"status": "ready"}

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        import logging
        logging.getLogger("brack").exception("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred. Please try again."},
        )

    return app


app = create_app()
