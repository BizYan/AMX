"""Providers Domain API Router

Endpoints for provider management, versioning, health, and runs.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.domains.providers.models import (
    Provider,
    ProviderType,
    ProviderStatus,
    RunStatus,
    HealthStatus,
)
from app.domains.providers.schemas import (
    ProviderCreate,
    ProviderUpdate,
    ProviderResponse,
    ProviderVersionCreate,
    ProviderVersionResponse,
    ProviderRollbackRequest,
    ProviderTestRequest,
    ProviderTestResponse,
    ProviderReadinessSummary,
    PaginatedResponse,
)
from app.domains.providers.capability import (
    is_live_configured,
    is_sandbox_provider,
    provider_secret_value,
)
from app.domains.providers.credential_boundary import provider_runtime_config
from app.domains.providers.registry import ProviderRegistry
from app.domains.providers.readiness import build_provider_readiness_summary
from app.models.identity import User


router = APIRouter()


def _sandbox_test_response(
    data: ProviderTestRequest,
    latency_ms: int,
    *,
    configured: bool,
    allowed: bool,
) -> ProviderTestResponse:
    capability = data.capability_type
    output: dict[str, Any] = {
        "mode": "sandbox",
        "capability_type": capability,
        "note": "沙箱测试只验证配置形态，不代表生产能力可用。",
    }
    if capability == "text_generation":
        output["text"] = "Sandbox response: provider credentials are not production-ready."
        output["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    elif capability == "embedding":
        output["embeddings_count"] = 0
    elif capability == "graph_query":
        output["nodes_count"] = 0
        output["edges_count"] = 0
    elif capability in {"commits", "issues"}:
        output[f"{capability}_count"] = 0

    if allowed:
        return ProviderTestResponse(
            success=True,
            message="Sandbox provider test completed. This is not production readiness evidence.",
            latency_ms=latency_ms,
            output=output,
            status="sandbox",
            mode="sandbox",
            capability_type=capability,
            configured=configured,
            production_ready=False,
            sandbox_fallback=True,
        )

    status = "sandbox" if configured else "unconfigured"
    message = (
        "Provider is configured for sandbox/test use. Enable allow_sandbox only for non-production checks."
        if configured
        else (
            "Provider has no live credential reference configured. "
            "Add credential_ref/secret_ref before testing production readiness."
        )
    )
    return ProviderTestResponse(
        success=False,
        message=message,
        latency_ms=latency_ms,
        output=output,
        status=status,
        mode="sandbox",
        capability_type=capability,
        configured=configured,
        production_ready=False,
        sandbox_fallback=True,
    )


async def _record_provider_test_run(
    *,
    registry,
    tenant_id: UUID,
    provider: Provider,
    response: ProviderTestResponse,
) -> None:
    record_run = getattr(registry, "record_run", None)
    if not callable(record_run):
        return

    usage = (response.output or {}).get("usage") if isinstance(response.output, dict) else None
    input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
    output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
    if response.status == "timeout":
        run_status = RunStatus.TIMEOUT
    elif response.success and response.production_ready:
        run_status = RunStatus.SUCCESS
    else:
        run_status = RunStatus.FAILURE

    await record_run(
        tenant_id=tenant_id,
        provider_id=provider.id,
        version_id=getattr(provider, "current_version_id", None),
        capability_type=response.capability_type or "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=response.latency_ms,
        status=run_status,
        error_message=None if run_status == RunStatus.SUCCESS else response.message,
    )


async def get_current_user(
    authorization: str = Header(..., description="Bearer token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get current authenticated user."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:]

    try:
        from app.domains.identity.service import AuthService

        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


def get_registry(db: AsyncSession) -> ProviderRegistry:
    """Dependency to get provider registry."""
    return ProviderRegistry(db)


# Provider Endpoints
@router.get("", response_model=PaginatedResponse[ProviderResponse])
async def list_providers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    provider_type: ProviderType | None = None,
    status: ProviderStatus | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all providers for the current tenant.

    Args:
        pagination: Pagination parameters
        provider_type: Optional filter by provider type
        status: Optional filter by status
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of providers
    """
    registry = get_registry(db)

    providers, total = await registry.list_providers(
        tenant_id=current_user.tenant_id,
        provider_type=provider_type,
        status=status,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    has_more = (page * page_size) < total

    return PaginatedResponse(
        items=[ProviderResponse.model_validate(p) for p in providers],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get("/readiness", response_model=ProviderReadinessSummary)
async def get_provider_readiness(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get tenant-level provider production readiness."""
    registry = get_registry(db)
    providers, _ = await registry.list_providers(
        tenant_id=current_user.tenant_id,
        skip=0,
        limit=100,
    )
    return build_provider_readiness_summary(
        tenant_id=current_user.tenant_id,
        providers=providers,
    )


@router.post("", response_model=ProviderResponse, status_code=201)
async def register_provider(
    data: ProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a new provider.

    Args:
        data: Provider registration data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created provider
    """
    registry = get_registry(db)

    try:
        provider = await registry.register_provider(
            tenant_id=current_user.tenant_id,
            name=data.name,
            provider_type=data.provider_type,
            config=data.config,
            capabilities=data.capabilities,
        )
        return ProviderResponse.model_validate(provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a provider by ID.

    Args:
        provider_id: Provider UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Provider details

    Raises:
        HTTPException: If provider not found or access denied
    """
    registry = get_registry(db)
    provider = await registry.get_provider(provider_id, current_user.tenant_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    return ProviderResponse.model_validate(provider)


@router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: UUID,
    data: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a provider.

    Args:
        provider_id: Provider UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated provider
    """
    registry = get_registry(db)

    # Update config if provided
    if data.config is not None:
        provider = await registry.update_provider_config(
            provider_id=provider_id,
            tenant_id=current_user.tenant_id,
            config=data.config,
        )
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

    # Update status if provided
    if data.status is not None:
        provider = await registry.set_provider_status(
            provider_id=provider_id,
            tenant_id=current_user.tenant_id,
            status=data.status,
        )
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

    # Update name if provided
    if data.name is not None:
        provider = await registry.get_provider(provider_id, current_user.tenant_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        provider.name = data.name
        await db.flush()
        await db.refresh(provider)

    return ProviderResponse.model_validate(provider)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a provider (soft delete).

    Args:
        provider_id: Provider UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If provider not found
    """
    registry = get_registry(db)
    deleted = await registry.delete_provider(provider_id, current_user.tenant_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")


# Provider Version Endpoints
@router.post("/{provider_id}/versions", response_model=ProviderVersionResponse, status_code=201)
async def create_version(
    provider_id: UUID,
    data: ProviderVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new provider version.

    Args:
        provider_id: Provider UUID
        data: Version data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created version
    """
    registry = get_registry(db)

    # Verify provider exists and belongs to tenant
    provider = await registry.get_provider(provider_id, current_user.tenant_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    version = await registry.create_version(
        provider_id=provider_id,
        config=data.config,
        capabilities=data.capabilities,
        set_active=data.set_active,
    )
    return ProviderVersionResponse.model_validate(version)


@router.get("/{provider_id}/versions", response_model=list[ProviderVersionResponse])
async def list_versions(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all versions for a provider.

    Args:
        provider_id: Provider UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of versions
    """
    registry = get_registry(db)

    provider = await registry.get_provider(provider_id, current_user.tenant_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    return [ProviderVersionResponse.model_validate(v) for v in provider.versions]


@router.post("/{provider_id}/rollback", response_model=ProviderResponse)
async def rollback_provider(
    provider_id: UUID,
    data: ProviderRollbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rollback provider to a specific version.

    Args:
        provider_id: Provider UUID
        data: Rollback request with target version
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated provider with rollback status
    """
    registry = get_registry(db)

    provider = await registry.rollback_to_version(
        provider_id=provider_id,
        tenant_id=current_user.tenant_id,
        version_id=data.version_id,
    )

    if not provider:
        raise HTTPException(status_code=404, detail="Provider or version not found")

    return ProviderResponse.model_validate(provider)


# Health and Testing Endpoints
@router.get("/{provider_id}/health", response_model=dict)
async def get_provider_health(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get provider health status.

    Args:
        provider_id: Provider UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Health status information
    """
    registry = get_registry(db)

    provider = await registry.get_provider(provider_id, current_user.tenant_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    return {
        "provider_id": str(provider_id),
        "status": provider.status,
        "provider_type": provider.provider_type,
    }


@router.post("/{provider_id}/test", response_model=ProviderTestResponse)
async def test_provider(
    provider_id: UUID,
    data: ProviderTestRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test provider connection/capability.

    Args:
        provider_id: Provider UUID
        data: Optional test request with capability to test
        db: Database session
        current_user: Current authenticated user

    Returns:
        Test results
    """
    import time
    import asyncio

    if data is None:
        data = ProviderTestRequest(capability_type="text_generation")

    registry = get_registry(db)

    provider = await registry.get_provider(provider_id, current_user.tenant_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    start_time = time.time()

    if provider.status != ProviderStatus.ACTIVE.value:
        response = ProviderTestResponse(
            success=False,
            message="Provider is inactive and cannot be used for live capability tests.",
            latency_ms=int((time.time() - start_time) * 1000),
            output={"provider_status": provider.status},
            status="inactive",
            mode="live",
            capability_type=data.capability_type,
            configured=False,
            production_ready=False,
            sandbox_fallback=False,
        )
        await _record_provider_test_run(
            registry=registry,
            tenant_id=current_user.tenant_id,
            provider=provider,
            response=response,
        )
        return response

    sandbox_provider = is_sandbox_provider(provider)
    live_configured = is_live_configured(provider)

    if sandbox_provider:
        await asyncio.sleep(0.05)
        response = _sandbox_test_response(
            data,
            int((time.time() - start_time) * 1000),
            configured=True,
            allowed=data.allow_sandbox,
        )
        await _record_provider_test_run(
            registry=registry,
            tenant_id=current_user.tenant_id,
            provider=provider,
            response=response,
        )
        return response

    if not live_configured:
        response = ProviderTestResponse(
            success=False,
            message="Provider is missing live credentials or required production configuration.",
            latency_ms=int((time.time() - start_time) * 1000),
            output={"required": ["credential_ref/secret_ref", "active status"]},
            status="unconfigured",
            mode="live",
            capability_type=data.capability_type,
            configured=False,
            production_ready=False,
            sandbox_fallback=False,
        )
        await _record_provider_test_run(
            registry=registry,
            tenant_id=current_user.tenant_id,
            provider=provider,
            response=response,
        )
        return response

    async def finish(response: ProviderTestResponse) -> ProviderTestResponse:
        await _record_provider_test_run(
            registry=registry,
            tenant_id=current_user.tenant_id,
            provider=provider,
            response=response,
        )
        return response

    try:
        # Test based on provider type
        if provider.provider_type == ProviderType.LLM.value:
            from app.integrations.llm.minimax_gateway import MiniMaxGateway

            gateway = MiniMaxGateway(
                api_key=provider_secret_value(provider),
                base_url=provider.config_json.get("base_url", "https://api.minimax.chat/v1"),
                model=provider.config_json.get("model", "MiniMax-Text-01"),
            )

            if data.capability_type == "text_generation":
                response = await gateway.generate(
                    prompt="Hello, this is a test.",
                    params=data.params,
                )
                await gateway.close()

                return await finish(ProviderTestResponse(
                    success=True,
                    message="LLM generation successful",
                    latency_ms=int((time.time() - start_time) * 1000),
                    output={"text": response.text, "usage": response.usage},
                    status="connected",
                    mode="live",
                    capability_type=data.capability_type,
                    configured=True,
                    production_ready=True,
                    sandbox_fallback=False,
                ))
            elif data.capability_type == "embedding":
                response = await gateway.embed(texts=["test"])
                await gateway.close()

                return await finish(ProviderTestResponse(
                    success=True,
                    message="Embedding successful",
                    latency_ms=int((time.time() - start_time) * 1000),
                    output={"embeddings_count": len(response.embeddings)},
                    status="connected",
                    mode="live",
                    capability_type=data.capability_type,
                    configured=True,
                    production_ready=True,
                    sandbox_fallback=False,
                ))

        elif provider.provider_type == ProviderType.GRAPHIFY.value:
            from app.integrations.graphify.adapter import GraphifyProvider

            graphify = GraphifyProvider(
                config=provider_runtime_config(provider, credential_key="api_key")
            )

            if data.capability_type == "graph_query":
                response = await graphify.extract_graph(
                    document_id="test-doc",
                    content="This is a test document.",
                    params=data.params,
                )

                return await finish(ProviderTestResponse(
                    success=True,
                    message="Graph extraction successful",
                    latency_ms=int((time.time() - start_time) * 1000),
                    output={"nodes_count": len(response.nodes), "edges_count": len(response.edges)},
                    status="connected",
                    mode="live",
                    capability_type=data.capability_type,
                    configured=True,
                    production_ready=True,
                    sandbox_fallback=False,
                ))

        elif provider.provider_type == ProviderType.GITNEXUS.value:
            from app.integrations.gitnexus.adapter import GitNexusProvider

            gitnexus = GitNexusProvider(
                config=provider_runtime_config(provider, credential_key="service_key")
            )
            repo_url_param = data.params.get("repo_url")
            repo_url = repo_url_param.strip() if isinstance(repo_url_param, str) else None

            if data.capability_type == "health":
                response = await gitnexus.check_health()

                return await finish(ProviderTestResponse(
                    success=True,
                    message="GitNexus health check successful",
                    latency_ms=int((time.time() - start_time) * 1000),
                    output=response,
                    status="connected",
                    mode="live",
                    capability_type=data.capability_type,
                    configured=True,
                    production_ready=True,
                    sandbox_fallback=False,
                ))
            elif data.capability_type in {"commits", "issues"} and not repo_url:
                return await finish(ProviderTestResponse(
                    success=False,
                    message="GitNexus repository capability requires params.repo_url.",
                    latency_ms=int((time.time() - start_time) * 1000),
                    output={"required": ["repo_url"]},
                    status="invalid_request",
                    mode="live",
                    capability_type=data.capability_type,
                    configured=True,
                    production_ready=False,
                    sandbox_fallback=False,
                ))
            elif data.capability_type == "commits":
                response = await gitnexus.fetch_commits(repo_url=repo_url, params=data.params)

                return await finish(ProviderTestResponse(
                    success=True,
                    message="Commits fetch successful",
                    latency_ms=int((time.time() - start_time) * 1000),
                    output={"commits_count": len(response.data)},
                    status="connected",
                    mode="live",
                    capability_type=data.capability_type,
                    configured=True,
                    production_ready=True,
                    sandbox_fallback=False,
                ))
            elif data.capability_type == "issues":
                response = await gitnexus.fetch_issues(repo_url=repo_url, params=data.params)

                return await finish(ProviderTestResponse(
                    success=True,
                    message="Issues fetch successful",
                    latency_ms=int((time.time() - start_time) * 1000),
                    output={"issues_count": len(response.data)},
                    status="connected",
                    mode="live",
                    capability_type=data.capability_type,
                    configured=True,
                    production_ready=True,
                    sandbox_fallback=False,
                ))

        return await finish(ProviderTestResponse(
            success=False,
            message=f"Unknown capability: {data.capability_type}",
            latency_ms=int((time.time() - start_time) * 1000),
            status="unsupported",
            mode="live",
            capability_type=data.capability_type,
            configured=True,
            production_ready=False,
            sandbox_fallback=False,
        ))

    except Exception as e:
        return await finish(ProviderTestResponse(
            success=False,
            message=f"Test failed: {str(e)}",
            latency_ms=int((time.time() - start_time) * 1000),
            output={"error": str(e)},
            status="failed",
            mode="live",
            capability_type=data.capability_type,
            configured=True,
            production_ready=False,
            sandbox_fallback=False,
        ))


# Provider Runs Endpoints
@router.get("/{provider_id}/runs", response_model=PaginatedResponse)
async def list_provider_runs(
    provider_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List provider run history.

    Args:
        provider_id: Provider UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of runs
    """
    registry = get_registry(db)

    runs, total = await registry.get_runs(
        provider_id=provider_id,
        tenant_id=current_user.tenant_id,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    has_more = (page * page_size) < total

    from app.domains.providers.schemas import ProviderRunResponse

    return PaginatedResponse(
        items=[ProviderRunResponse.model_validate(r) for r in runs],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )
