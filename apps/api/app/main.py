"""Consultant AI Workbench - FastAPI Application Entry Point

This module initializes the FastAPI application with all middleware,
routers, and health checks configured.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.runtime_security import validate_runtime_security_settings
from app.core.settings import settings
from app.db.session import async_engine, AsyncSessionLocal
from app.db.bootstrap import create_bootstrap_admin
from app.db.init_schema import create_missing_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager.

    Handles startup and shutdown events.
    """
    validate_runtime_security_settings()

    # Startup: Alembic covers core migrations; create missing model tables for
    # domains whose migrations have not been materialized yet.
    await create_missing_tables()

    # Create bootstrap admin if configured
    if settings.BOOTSTRAP_ADMIN_EMAIL:
        async with AsyncSessionLocal() as db:
            await create_bootstrap_admin(db)

    yield

    # Shutdown: dispose engine connections
    await async_engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Configured FastAPI application
    """
    app = FastAPI(
        title=settings.APP_NAME,
        description="Backend API for the Consultant AI Workbench platform",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS middleware - read from environment variable
    cors_origins_str = os.getenv("CORS_ORIGINS", settings.CORS_ORIGINS)
    cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint for container orchestration."""
        return {"status": "healthy", "version": "1.0.0"}

    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint returning API information."""
        return {
            "name": settings.APP_NAME,
            "version": "1.0.0",
            "docs": "/docs",
        }

    # Include API v1 routers
    from app.api.v1 import api_router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


# Create app instance for uvicorn
app = create_app()
