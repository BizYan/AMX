"""Tests for Controlled Backwrite Service

Tests for the controlled backwrite service that handles
document version creation, baseline management, and field patches.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from app.domains.change.service import ChangeService, ControlledBackwriteService
from app.domains.change.models import FieldPatch, PatchStatus, PatchType
from app.domains.documents.models import Document, DocumentVersion, DocumentBaseline


class TestChangeRequestActorContract:
    """Tests for change-request actor attribution requirements."""

    @pytest.mark.asyncio
    async def test_create_change_request_requires_requested_by(self):
        service = ChangeService(AsyncMock())

        with pytest.raises(ValueError, match="requested_by is required"):
            await service.create_change_request(
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                project_id=UUID("12345678-1234-1234-1234-123456789012"),
                source_doc_id=None,
                target_doc_id=None,
                change_type="dependency",
                description="Traceable requester is required.",
                requested_by=None,
            )


class TestCheckBaseVersionConflict:
    """Tests for check_base_version_conflict method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        """Create service with mock db."""
        return ControlledBackwriteService(mock_db)

    @pytest.mark.asyncio
    async def test_no_conflict_when_no_baselines(self, service, mock_db):
        """Test no conflict when document has no baselines."""
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=[])

        # Mock the result for scalars().all()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await service.check_base_version_conflict(
            document_id=UUID("12345678-1234-1234-1234-123456789012"),
            base_version_id=UUID("87654321-4321-4321-4321-210987654321"),
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_conflict_when_newer_baseline_exists(self, service, mock_db):
        """Test conflict detected when a newer baseline exists."""
        base_version_id = UUID("87654321-4321-4321-4321-210987654321")
        newer_version_id = UUID("87654321-4321-4321-4321-210987654322")

        mock_baseline = MagicMock()
        mock_baseline.version_id = newer_version_id

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_baseline]
        mock_db.execute.return_value = mock_result

        result = await service.check_base_version_conflict(
            document_id=UUID("12345678-1234-1234-1234-123456789012"),
            base_version_id=base_version_id,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        )

        assert result is True


class TestApplyFieldPatch:
    """Tests for apply_field_patch method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        """Create service with mock db."""
        return ControlledBackwriteService(mock_db)

    @pytest.mark.asyncio
    async def test_patch_not_found(self, service, mock_db):
        """Test error when patch not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Patch not found"):
            await service.apply_field_patch(
                patch_id=UUID("12345678-1234-1234-1234-123456789012"),
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            )

    @pytest.mark.asyncio
    async def test_patch_not_approved(self, service, mock_db):
        """Test error when patch is not approved."""
        mock_patch = MagicMock()
        mock_patch.status = PatchStatus.PENDING.value

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_patch
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Can only apply approved patches"):
            await service.apply_field_patch(
                patch_id=UUID("12345678-1234-1234-1234-123456789012"),
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            )

    @pytest.mark.asyncio
    async def test_approved_patch_requires_reviewer_before_apply(self, service, mock_db):
        """Test approved patches cannot apply without reviewer attribution."""
        mock_patch = MagicMock()
        mock_patch.id = UUID("12345678-1234-1234-1234-123456789012")
        mock_patch.status = PatchStatus.APPROVED.value
        mock_patch.reviewed_by = None

        mock_document = MagicMock()
        mock_document.id = UUID("87654321-4321-4321-4321-210987654321")
        mock_document.version = 3
        mock_document.content = "current content"

        patch_result = MagicMock()
        patch_result.scalar_one_or_none.return_value = mock_patch
        document_result = MagicMock()
        document_result.scalar_one_or_none.return_value = mock_document
        mock_db.execute.side_effect = [patch_result, document_result]

        with pytest.raises(ValueError, match="Approved patch reviewer is required"):
            await service.apply_field_patch(
                patch_id=mock_patch.id,
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            )


class TestCreateBaselineCandidate:
    """Tests for create_baseline_candidate method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        """Create service with mock db."""
        return ControlledBackwriteService(mock_db)

    @pytest.mark.asyncio
    async def test_document_not_found(self, service, mock_db):
        """Test error when document not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Document not found"):
            await service.create_baseline_candidate(
                document_id=UUID("12345678-1234-1234-1234-123456789012"),
                version_id=UUID("87654321-4321-4321-4321-210987654321"),
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                baseline_name="Test Baseline",
            )

    @pytest.mark.asyncio
    async def test_version_not_found(self, service, mock_db):
        """Test error when version not found."""
        mock_document = MagicMock()
        mock_document.id = UUID("12345678-1234-1234-1234-123456789012")

        # First call returns document, second returns None for version
        mock_results = [MagicMock(), MagicMock()]
        mock_results[0].scalar_one_or_none.return_value = mock_document
        mock_results[1].scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = mock_results

        with pytest.raises(ValueError, match="Version not found"):
            await service.create_baseline_candidate(
                document_id=UUID("12345678-1234-1234-1234-123456789012"),
                version_id=UUID("87654321-4321-4321-4321-210987654321"),
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                baseline_name="Test Baseline",
            )


class TestBackwriteWithNewVersion:
    """Tests for backwrite_with_new_version method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        """Create service with mock db."""
        return ControlledBackwriteService(mock_db)

    @pytest.mark.asyncio
    async def test_document_not_found(self, service, mock_db):
        """Test error when document not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Document not found"):
            await service.backwrite_with_new_version(
                document_id=UUID("12345678-1234-1234-1234-123456789012"),
                patches=[],
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                user_id=UUID("00000000-0000-0000-0000-000000000002"),
            )

    @pytest.mark.asyncio
    async def test_no_approved_patches(self, service, mock_db):
        """Test error when no approved patches provided."""
        mock_document = MagicMock()
        mock_document.id = UUID("12345678-1234-1234-1234-123456789012")
        mock_document.version = 1
        mock_document.content = '{"title": "Test"}'
        mock_document.project_id = UUID("00000000-0000-0000-0000-000000000003")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_document
        mock_db.execute.return_value = mock_result

        # Only pending patches
        mock_pending_patch = MagicMock()
        mock_pending_patch.status = PatchStatus.PENDING.value

        with pytest.raises(ValueError, match="No approved patches to apply"):
            await service.backwrite_with_new_version(
                document_id=UUID("12345678-1234-1234-1234-123456789012"),
                patches=[mock_pending_patch],
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                user_id=UUID("00000000-0000-0000-0000-000000000002"),
            )

    @pytest.mark.asyncio
    async def test_creates_new_version_with_baseline(self, service, mock_db):
        """Test that backwrite creates new version and baseline candidate."""
        mock_document = MagicMock()
        mock_document.id = UUID("12345678-1234-1234-1234-123456789012")
        mock_document.version = 1
        mock_document.content = '{"title": "Test"}'
        mock_document.project_id = UUID("00000000-0000-0000-0000-000000000003")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_document
        mock_db.execute.return_value = mock_result

        mock_approved_patch = MagicMock()
        mock_approved_patch.status = PatchStatus.APPROVED.value
        mock_approved_patch.patch_type = PatchType.REPLACE.value
        mock_approved_patch.field_path = "title"
        mock_approved_patch.new_value = "Updated Title"

        # Track what gets added to the session
        added_items = []
        mock_db.add = lambda item: added_items.append(item)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        new_version, baseline = await service.backwrite_with_new_version(
            document_id=UUID("12345678-1234-1234-1234-123456789012"),
            patches=[mock_approved_patch],
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            create_baseline_candidate_flag=True,
        )

        assert baseline is not None
        # Check that DocumentVersion and DocumentBaseline were added
        assert any(isinstance(item, DocumentVersion) for item in added_items)
        assert any(isinstance(item, DocumentBaseline) for item in added_items)


class TestApplyPatchToContent:
    """Tests for _apply_patch_to_content helper method."""

    @pytest.fixture
    def service(self):
        """Create service with real (non-async) instance."""
        mock_db = MagicMock()
        return ControlledBackwriteService(mock_db)

    def test_apply_replace_patch_to_json(self, service):
        """Test applying a replace patch to JSON content."""
        content = '{"title": "Original", "description": "Desc"}'
        result = service._apply_patch_to_content(content, "title", "New Title")

        import json
        data = json.loads(result)
        assert data["title"] == "New Title"
        assert data["description"] == "Desc"

    def test_apply_replace_patch_to_nested_json(self, service):
        """Test applying a replace patch to nested JSON content."""
        content = '{"section": {"title": "Original", "body": "Body"}}'
        result = service._apply_patch_to_content(content, "section.title", "New Title")

        import json
        data = json.loads(result)
        assert data["section"]["title"] == "New Title"
        assert data["section"]["body"] == "Body"

    def test_apply_replace_patch_to_array_element(self, service):
        """Test applying a replace patch to array element."""
        content = '{"items": ["first", "second", "third"]}'
        result = service._apply_patch_to_content(content, "items.1", "SECOND")

        import json
        data = json.loads(result)
        assert data["items"][1] == "SECOND"

    def test_apply_remove_patch(self, service):
        """Test applying a remove patch removes the field."""
        content = '{"title": "Title", "description": "Desc"}'
        result = service._apply_patch_to_content(content, "description", None)

        import json
        data = json.loads(result)
        assert "description" not in data
        assert data["title"] == "Title"

    def test_plain_text_content_passthrough(self, service):
        """Test that plain text content passes through unchanged."""
        content = "This is plain text content without JSON structure."
        result = service._apply_patch_to_content(content, "title", "New Title")

        assert result == content

    def test_apply_replace_patch_to_markdown_section_content(self, service):
        """Test applying a replace patch to a Markdown section body."""
        content = "# Delivery Plan\n\n## Scope\nOld scope\n\n## Risks\nOld risks\n"
        result = service._apply_patch_to_content(
            content,
            "sections.0.content",
            "New scope\n- Confirmed owner",
        )

        assert "Old scope" not in result
        assert "## Scope\n\nNew scope\n- Confirmed owner" in result
        assert "## Risks\nOld risks" in result

    def test_apply_replace_patch_to_markdown_section_title(self, service):
        """Test applying a replace patch to a Markdown section heading."""
        content = "# Delivery Plan\n\n## Scope\nCurrent scope\n\n## Risks\nOpen risks\n"
        result = service._apply_patch_to_content(
            content,
            "sections.1.title",
            "Accepted Risks",
        )

        assert "## Risks" not in result
        assert "## Accepted Risks\nOpen risks" in result
