"""API v1 Router Module

Aggregates all v1 API routers under /api/v1 prefix.
"""

from fastapi import APIRouter

api_router = APIRouter()

# Import and include sub-routers
from app.api.v1.identity import router as identity_router  # noqa: E402
from app.domains.projects.router import router as projects_router  # noqa: E402
from app.domains.providers.router import router as providers_router  # noqa: E402
from app.domains.knowledge.router import router as knowledge_router  # noqa: E402
from app.domains.documents.router import router as documents_router  # noqa: E402
from app.domains.change.router import router as change_router  # noqa: E402
from app.domains.agent.router import router as agent_router  # noqa: E402
from app.domains.export.router import router as export_router  # noqa: E402
from app.domains.integrations.router import router as integrations_router  # noqa: E402
from app.domains.collaboration.router import router as collaboration_router  # noqa: E402
from app.domains.ops.router import router as ops_router  # noqa: E402
from app.domains.config.router import router as config_router  # noqa: E402
from app.domains.templates.router import router as templates_router  # noqa: E402
from app.domains.notifications.router import router as notifications_router  # noqa: E402

api_router.include_router(identity_router, prefix="/identity", tags=["identity"])
api_router.include_router(projects_router, prefix="/projects", tags=["projects"])
api_router.include_router(providers_router, prefix="/providers", tags=["providers"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(change_router, prefix="/change", tags=["change"])
api_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_router.include_router(export_router, prefix="/exports", tags=["exports"])
api_router.include_router(integrations_router, prefix="/integrations", tags=["integrations"])
api_router.include_router(collaboration_router, prefix="", tags=["collaboration"])
api_router.include_router(ops_router, prefix="/ops", tags=["ops"])
api_router.include_router(config_router, prefix="/config", tags=["config"])
api_router.include_router(templates_router, prefix="/templates", tags=["templates"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
