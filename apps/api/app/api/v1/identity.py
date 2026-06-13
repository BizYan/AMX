"""Identity Domain API Router

FastAPI endpoints for authentication, tenant, user, role, policy, and audit management.
This module is the entry point registered in api_router.
"""

from app.domains.identity.router import router

__all__ = ["router"]