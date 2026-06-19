"""Document Domain Service

Business logic for document management, versioning, baselines, and quality assessment.
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.placeholders import extract_placeholders, substitute_placeholders
from app.core.settings import settings
from app.integrations.llm.gateway import LLMGateway, GatewayFactory
from app.domains.documents.models import (
    Document,
    DocumentEntity,
    DocumentVersion,
    DocumentBaseline,
    DocumentGenerationSection,
    DocumentGenerationSession,
    DocumentGenerationStep,
    QualityResult,
    DocumentStatus,
    DocumentType,
    GenerationSectionStatus,
    GenerationSessionStatus,
    QualityType,
)
from app.domains.documents.schemas import (
    DocumentCreate,
    DocumentUpdate,
    DocumentVersionCreate,
    DocumentBaselineCreate,
    DocumentStatusUpdate,
    DocumentGenerateRequest,
)
from app.domains.documents.document_types import (
    DOCUMENT_TYPE_SCHEMAS,
    get_schema_for_doc_type,
)
from app.domains.projects.lifecycle import (
    DEFAULT_TRANSITIONS,
    ProjectDocumentLifecyclePolicyService,
    default_document_lifecycle_policy,
)
from app.domains.projects.schemas import DocumentLifecyclePolicyResponse
from app.domains.providers.credential_boundary import sanitize_error_message
from app.domains.providers.models import CapabilityType, ProviderRun, RunStatus

FORMAL_DELIVERY_STATES = {
    DocumentStatus.PENDING_REVIEW.value,
    DocumentStatus.REVIEW.value,
    DocumentStatus.IN_REVIEW.value,
    DocumentStatus.APPROVED.value,
    DocumentStatus.PUBLISHED.value,
}

NON_DELIVERABLE_GENERATION_STATUSES = {"placeholder", "failed", "partial"}

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    status: set(targets) for status, targets in DEFAULT_TRANSITIONS.items()
}

FULL_DELIVERY_CAPABILITY_PACKS: dict[str, list[dict[str, Any]]] = {
    DocumentType.URS.value: [
        {
            "section_key": "urs.business_objectives",
            "title": "业务目标与范围",
            "content_requirement": "说明项目背景、业务目标、范围边界、成功口径和提出方。",
            "prompt": "先澄清为什么要做、谁提出、覆盖哪些业务范围，以及如何判断成功。",
            "required_inputs": ["business_objectives", "scope", "success_criteria"],
            "quality_rules": [{"rule": "目标必须可追溯到明确业务场景", "severity": "high"}],
            "first_question": "请先说明这次项目或需求的业务目标、覆盖范围，以及谁是主要提出方。",
            "upstream_dependencies": [],
            "skill_labels": ["业务澄清", "结构化写入", "质量评审"],
        },
        {
            "section_key": "urs.user_personas",
            "title": "用户画像与使用场景",
            "content_requirement": "识别用户角色、使用场景、痛点、期望收益和权限边界。",
            "prompt": "围绕真实用户、具体场景和当前问题逐步追问。",
            "required_inputs": ["user_personas", "scenarios", "pain_points"],
            "quality_rules": [{"rule": "每个用户画像必须包含角色、目标和痛点", "severity": "high"}],
            "first_question": "请列出会使用或受影响的主要用户角色，并说明他们当前在哪些场景下遇到问题。",
            "upstream_dependencies": [],
            "skill_labels": ["用户研究", "业务澄清", "结构化写入"],
        },
        {
            "section_key": "urs.functional_requirements",
            "title": "功能与非功能需求",
            "content_requirement": "记录功能需求、非功能需求、约束、假设和验收口径。",
            "prompt": "把用户语言转成可验收需求，缺失指标必须标记待确认。",
            "required_inputs": ["functional_requirements", "non_functional_requirements", "constraints"],
            "quality_rules": [{"rule": "每条需求必须有验收标准或待确认标记", "severity": "high"}],
            "first_question": "请说明用户最希望系统提供哪些能力，以及是否有性能、安全、合规或时间约束。",
            "upstream_dependencies": [],
            "skill_labels": ["需求澄清", "结构化写入", "质量评审"],
        },
    ],
    DocumentType.BRD.value: [
        {
            "section_key": "brd.background_goals",
            "title": "背景与目标",
            "content_requirement": "记录业务痛点、核心目标、预期收益，并保持痛点到目标的可追溯关系。",
            "prompt": "先澄清业务背景、当前痛点、目标状态和可验证收益；缺失事实不得编造。",
            "required_inputs": ["pain_points", "core_objectives", "expected_benefits"],
            "quality_rules": [{"rule": "每个目标必须能追溯到明确痛点", "severity": "high"}],
            "first_question": "请先用一句话说明当前业务痛点、希望改善的目标，以及这次 BRD 覆盖的业务范围。",
            "upstream_dependencies": ["urs"],
            "skill_labels": ["BRD 深度澄清", "结构化写入", "质量评审"],
        },
        {
            "section_key": "brd.stakeholders",
            "title": "干系人与业务角色",
            "content_requirement": "定义业务角色、职责边界、参与流程和角色期望。",
            "prompt": "围绕谁参与、谁审批、谁使用、谁负责异常处理进行澄清。",
            "required_inputs": ["business_roles", "role_expectations"],
            "quality_rules": [{"rule": "每个角色必须说明职责或期望", "severity": "high"}],
            "first_question": "请说明本流程涉及哪些业务角色，例如经办人、复核人、主管、财务或外部客户。",
            "upstream_dependencies": ["urs"],
            "skill_labels": ["业务澄清", "结构化写入", "质量评审"],
        },
        {
            "section_key": "brd.business_flows",
            "title": "现状与目标业务流程",
            "content_requirement": "描述 As-Is 与 To-Be 流程、关键节点、责任角色、输入输出和异常路径。",
            "prompt": "先确认流程骨架，再逐节点补充角色、输入、输出、状态和异常。",
            "required_inputs": ["as_is_flow", "to_be_flow", "exceptions"],
            "quality_rules": [{"rule": "目标流程必须回应现状痛点", "severity": "high"}],
            "first_question": "请按顺序描述当前流程和期望流程，先给出主要节点即可。",
            "upstream_dependencies": ["urs"],
            "skill_labels": ["流程梳理", "结构化写入", "质量评审"],
        },
        {
            "section_key": "brd.requirement_modules",
            "title": "核心需求模块",
            "content_requirement": "拆分需求模块，记录模块编码、标题、前置条件、触发条件、预期结果和异常规则。",
            "prompt": "需求模块必须来自业务目标和流程，不凭空扩展。",
            "required_inputs": ["module_candidates", "preconditions", "triggers", "expected_results"],
            "quality_rules": [{"rule": "每个模块必须包含触发条件和预期结果", "severity": "high"}],
            "first_question": "请列出必须支持的核心业务模块，或说明最重要的业务动作。",
            "upstream_dependencies": ["urs"],
            "skill_labels": ["需求拆解", "结构化写入", "质量评审"],
        },
        {
            "section_key": "brd.non_functional",
            "title": "非功能需求",
            "content_requirement": "记录性能、合规、安全、审计、可用性和数据留痕要求。",
            "prompt": "只写已确认的非功能要求；不确定的指标必须标记待确认。",
            "required_inputs": ["performance", "compliance_security", "auditability"],
            "quality_rules": [{"rule": "不可编造 SLA、并发量或提升比例", "severity": "high"}],
            "first_question": "请说明性能、安全、审计、合规或可用性方面是否有硬性要求。",
            "upstream_dependencies": ["urs"],
            "skill_labels": ["非功能澄清", "结构化写入", "质量评审"],
        },
    ],
    DocumentType.PRD.value: [
        {
            "section_key": "prd.traceability",
            "title": "上游需求映射",
            "content_requirement": "建立 URS/BRD 到产品模块、页面和功能点的追溯关系。",
            "prompt": "PRD 内容必须来自上游需求；新增内容需要显式标记。",
            "required_inputs": ["linked_brd", "linked_urs", "requirement_mapping"],
            "quality_rules": [{"rule": "每个功能点必须有上游来源或新增标记", "severity": "high"}],
            "first_question": "请提供上游 URS/BRD 摘要，或说明 PRD 需要承接的业务痛点和模块。",
            "upstream_dependencies": ["urs", "brd"],
            "skill_labels": ["血缘映射", "产品规划", "质量评审"],
        },
        {
            "section_key": "prd.module_architecture",
            "title": "产品模块与页面架构",
            "content_requirement": "定义产品模块、页面、功能点和全局规则。",
            "prompt": "先生成骨架，待用户确认后再扩展详细功能。",
            "required_inputs": ["modules", "pages", "global_rules"],
            "quality_rules": [{"rule": "模块和页面必须可追溯到上游映射", "severity": "high"}],
            "first_question": "请说明产品模块和主要页面，或确认是否由系统根据上游需求先推断骨架。",
            "upstream_dependencies": ["brd"],
            "skill_labels": ["产品骨架规划", "结构化写入", "质量评审"],
        },
        {
            "section_key": "prd.feature_specs",
            "title": "功能规格与验收",
            "content_requirement": "每个功能包含流程、界面元素、前置条件、正常流程、异常处理和数据流。",
            "prompt": "按功能逐项展开，不一次性生成未经确认的大段内容。",
            "required_inputs": ["feature_list", "flows", "exceptions", "acceptance_criteria"],
            "quality_rules": [{"rule": "每个功能必须包含验收或异常处理", "severity": "high"}],
            "first_question": "请选择本轮要展开的功能，或说明最高优先级的用户任务。",
            "upstream_dependencies": ["brd"],
            "skill_labels": ["功能规格", "验收设计", "质量评审"],
        },
        {
            "section_key": "prd.metrics_release",
            "title": "指标、埋点与发布条件",
            "content_requirement": "定义埋点事件、监控指标、发布条件和上线后验证计划。",
            "prompt": "指标必须可观测，缺失口径标记待确认。",
            "required_inputs": ["tracking_events", "monitoring_metrics", "release_criteria"],
            "quality_rules": [{"rule": "发布条件必须可验证", "severity": "medium"}],
            "first_question": "请说明上线验收、监控指标、埋点或发布审批方面的要求。",
            "upstream_dependencies": ["brd"],
            "skill_labels": ["指标设计", "发布门禁", "质量评审"],
        },
    ],
    DocumentType.USER_STORY.value: [
        {
            "section_key": "user_story.role_goal_benefit",
            "title": "角色、目标与收益",
            "content_requirement": "按 As a / I want / So that 结构描述用户故事。",
            "prompt": "用户故事必须来自 PRD 功能或上游需求。",
            "required_inputs": ["user_type", "goal", "benefit"],
            "quality_rules": [{"rule": "每条故事必须包含角色、目标和收益", "severity": "high"}],
            "first_question": "请说明这个用户故事面向哪个角色、他想完成什么目标，以及带来什么收益。",
            "upstream_dependencies": ["prd"],
            "skill_labels": ["用户故事拆分", "结构化写入", "质量评审"],
        },
        {
            "section_key": "user_story.acceptance",
            "title": "验收标准",
            "content_requirement": "记录 Given/When/Then 或等价可验证验收条件。",
            "prompt": "验收标准必须可执行、可观察。",
            "required_inputs": ["acceptance_criteria", "priority"],
            "quality_rules": [{"rule": "验收标准必须可验证", "severity": "high"}],
            "first_question": "请说明这个用户故事做到什么程度算完成，最好给出正常路径和异常路径。",
            "upstream_dependencies": ["prd"],
            "skill_labels": ["验收设计", "质量评审"],
        },
        {
            "section_key": "user_story.dependencies",
            "title": "优先级与依赖",
            "content_requirement": "记录优先级、估算、依赖关系和上游需求编号。",
            "prompt": "依赖必须指向清晰的需求、功能或故事。",
            "required_inputs": ["priority", "dependencies", "linked_requirements"],
            "quality_rules": [{"rule": "依赖关系必须可追溯", "severity": "medium"}],
            "first_question": "请说明这个用户故事的优先级，以及它依赖哪些需求、功能或其他故事。",
            "upstream_dependencies": ["prd"],
            "skill_labels": ["依赖分析", "血缘映射", "质量评审"],
        },
    ],
    DocumentType.DETAILED_DESIGN.value: [
        {
            "section_key": "detailed_design.module_overview",
            "title": "模块职责与设计边界",
            "content_requirement": "说明模块目标、职责、边界、输入输出和关联 PRD 功能。",
            "prompt": "设计必须承接 PRD，不把未确认业务需求写成设计事实。",
            "required_inputs": ["module_name", "overview", "linked_user_stories"],
            "quality_rules": [{"rule": "设计模块必须能追溯到 PRD 或用户故事", "severity": "high"}],
            "first_question": "请说明要设计的模块名称、职责边界，以及对应的 PRD 功能或用户故事。",
            "upstream_dependencies": ["prd", "user_story"],
            "skill_labels": ["技术设计", "血缘映射", "质量评审"],
        },
        {
            "section_key": "detailed_design.architecture_flow",
            "title": "架构、时序与数据流",
            "content_requirement": "记录组件关系、关键时序、状态流转和数据流。",
            "prompt": "先确认关键交互链路，再展开类图、时序图或状态图。",
            "required_inputs": ["class_diagram", "sequence_diagrams", "data_flow"],
            "quality_rules": [{"rule": "关键流程必须覆盖正常和异常路径", "severity": "high"}],
            "first_question": "请描述该模块最关键的一条业务或系统交互链路，包括参与组件和输入输出。",
            "upstream_dependencies": ["prd"],
            "skill_labels": ["架构设计", "流程建模", "质量评审"],
        },
        {
            "section_key": "detailed_design.error_security",
            "title": "错误处理与安全约束",
            "content_requirement": "定义错误处理、权限、安全、审计、降级和观测策略。",
            "prompt": "异常、安全和审计要求必须与上游约束保持一致。",
            "required_inputs": ["error_handling", "security_considerations", "observability"],
            "quality_rules": [{"rule": "错误处理和安全约束必须可验证", "severity": "high"}],
            "first_question": "请说明这个模块需要处理哪些异常、安全、权限、审计或降级场景。",
            "upstream_dependencies": ["prd"],
            "skill_labels": ["安全设计", "异常设计", "质量评审"],
        },
    ],
    DocumentType.INTERFACE.value: [
        {
            "section_key": "interface.contract",
            "title": "接口契约与认证",
            "content_requirement": "定义接口名称、认证方式、版本策略、调用方和服务方。",
            "prompt": "接口说明必须来自设计或 PRD，不凭空生成外部契约。",
            "required_inputs": ["api_name", "authentication", "versioning_strategy"],
            "quality_rules": [{"rule": "接口认证和版本策略必须明确", "severity": "high"}],
            "first_question": "请说明接口名称、调用方、服务方、认证方式和版本策略。",
            "upstream_dependencies": ["prd", "detailed_design"],
            "skill_labels": ["接口设计", "结构化写入", "质量评审"],
        },
        {
            "section_key": "interface.endpoints",
            "title": "端点、请求与响应",
            "content_requirement": "记录端点、方法、路径、请求参数、响应结构和示例。",
            "prompt": "逐个端点确认，不批量编造字段。",
            "required_inputs": ["endpoints", "request_schema", "response_schema"],
            "quality_rules": [{"rule": "每个端点必须包含方法、路径、请求和响应", "severity": "high"}],
            "first_question": "请先说明本接口包含哪些端点，或选择一个端点开始细化。",
            "upstream_dependencies": ["detailed_design"],
            "skill_labels": ["接口建模", "结构化写入", "质量评审"],
        },
        {
            "section_key": "interface.errors_limits",
            "title": "错误码、限流与兼容",
            "content_requirement": "记录错误码、限流、幂等、重试和兼容策略。",
            "prompt": "错误和限流规则必须明确触发条件和调用方处理方式。",
            "required_inputs": ["error_codes", "rate_limits", "idempotency"],
            "quality_rules": [{"rule": "错误码和限流策略必须可执行", "severity": "medium"}],
            "first_question": "请说明这个接口有哪些错误码、限流、重试、幂等或兼容要求。",
            "upstream_dependencies": ["detailed_design"],
            "skill_labels": ["异常设计", "接口治理", "质量评审"],
        },
    ],
    DocumentType.DATA_DICTIONARY.value: [
        {
            "section_key": "data_dictionary.tables",
            "title": "表与实体定义",
            "content_requirement": "定义表、实体、业务含义、主键和来源文档。",
            "prompt": "数据字典必须承接设计和接口，不凭空扩展表。",
            "required_inputs": ["tables", "entities", "primary_keys"],
            "quality_rules": [{"rule": "每张表必须有业务含义和主键", "severity": "high"}],
            "first_question": "请列出需要纳入数据字典的核心表或业务实体，并说明它们的业务含义。",
            "upstream_dependencies": ["detailed_design", "interface"],
            "skill_labels": ["数据建模", "结构化写入", "质量评审"],
        },
        {
            "section_key": "data_dictionary.fields_indexes",
            "title": "字段、索引与关系",
            "content_requirement": "记录字段名、类型、口径、是否必填、索引和表关系。",
            "prompt": "字段口径必须清晰，缺失类型或含义时标记待确认。",
            "required_inputs": ["columns", "indexes", "relationships"],
            "quality_rules": [{"rule": "字段必须包含类型、含义和必填口径", "severity": "high"}],
            "first_question": "请选择一张表，说明字段、类型、含义、必填规则、索引和关联关系。",
            "upstream_dependencies": ["detailed_design", "interface"],
            "skill_labels": ["字段建模", "数据治理", "质量评审"],
        },
        {
            "section_key": "data_dictionary.retention",
            "title": "数据保留与治理",
            "content_requirement": "记录数据保留、脱敏、审计、归档和删除策略。",
            "prompt": "治理策略必须回应安全、合规或业务审计要求。",
            "required_inputs": ["data_retention_policy", "audit_rules", "privacy_rules"],
            "quality_rules": [{"rule": "数据保留和脱敏要求必须有依据或待确认标记", "severity": "medium"}],
            "first_question": "请说明这些数据是否有保留期限、审计、脱敏、归档或删除要求。",
            "upstream_dependencies": ["brd", "detailed_design"],
            "skill_labels": ["数据治理", "合规检查", "质量评审"],
        },
    ],
    DocumentType.TEST_CASE.value: [
        {
            "section_key": "test_case.scope_strategy",
            "title": "测试范围与策略",
            "content_requirement": "定义测试套件、测试范围、优先级和覆盖目标。",
            "prompt": "测试用例必须承接 PRD、设计或接口，不脱离上游验收标准。",
            "required_inputs": ["test_suite", "scope", "priority"],
            "quality_rules": [{"rule": "测试范围必须对应上游功能或设计", "severity": "high"}],
            "first_question": "请说明要测试的功能、模块或接口，以及测试优先级和覆盖目标。",
            "upstream_dependencies": ["prd", "detailed_design", "interface"],
            "skill_labels": ["测试设计", "血缘映射", "质量评审"],
        },
        {
            "section_key": "test_case.steps_data",
            "title": "前置条件、步骤与数据",
            "content_requirement": "记录前置条件、测试步骤、测试数据和预期结果。",
            "prompt": "每个步骤必须有动作和可观察预期结果。",
            "required_inputs": ["precondition", "test_steps", "test_data"],
            "quality_rules": [{"rule": "每个测试步骤必须有预期结果", "severity": "high"}],
            "first_question": "请描述一个核心测试场景的前置条件、操作步骤、测试数据和预期结果。",
            "upstream_dependencies": ["prd"],
            "skill_labels": ["测试步骤设计", "结构化写入", "质量评审"],
        },
        {
            "section_key": "test_case.coverage_automation",
            "title": "覆盖关系与自动化",
            "content_requirement": "记录关联用户故事、详细设计、覆盖矩阵和自动化可行性。",
            "prompt": "覆盖关系必须可追溯，自动化标记必须说明依据。",
            "required_inputs": ["linked_user_story", "linked_detailed_design", "automated"],
            "quality_rules": [{"rule": "测试用例必须能追溯到需求或设计", "severity": "high"}],
            "first_question": "请说明该测试用例关联的用户故事、设计文档，以及是否适合自动化。",
            "upstream_dependencies": ["user_story", "detailed_design"],
            "skill_labels": ["测试覆盖", "自动化评估", "质量评审"],
        },
    ],
}


class DocumentService:
    """Service for document management operations.

    Handles CRUD operations for documents, versioning, baselines,
    and quality assessments.
    """

    def __init__(self, db: AsyncSession):
        """Initialize document service.

        Args:
            db: Async database session
        """
        self.db = db

    async def create_document(
        self,
        tenant_id: UUID,
        project_id: UUID,
        doc_type: str,
        title: str,
        content: str = "",
        created_by: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        """Create a new document.

        Args:
            tenant_id: Tenant UUID
            project_id: Project UUID
            doc_type: Document type (e.g., 'urs', 'brd')
            title: Document title
            content: Initial content
            created_by: User ID of creator
            metadata: Additional metadata

        Returns:
            Created Document
        """
        if created_by is None:
            raise ValueError("created_by is required")

        document = Document(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=doc_type,
            title=title,
            content=content,
            status=DocumentStatus.DRAFT.value,
            version=1,
            created_by=created_by,
            metadata_json=metadata,
        )
        self.db.add(document)
        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def get_document(
        self,
        document_id: UUID,
        tenant_id: UUID | None = None,
        include_deleted: bool = False,
    ) -> Document | None:
        """Get document by ID.

        Args:
            document_id: Document UUID
            tenant_id: Optional tenant filter
            include_deleted: Whether to include soft-deleted documents

        Returns:
            Document if found, None otherwise
        """
        query = select(Document).where(Document.id == document_id)
        if not include_deleted:
            query = query.where(Document.deleted_at.is_(None))
        if tenant_id is not None:
            query = query.where(Document.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_document_with_entities(
        self,
        document_id: UUID,
        tenant_id: UUID | None = None,
    ) -> Document | None:
        """Get document by ID with entities loaded.

        Args:
            document_id: Document UUID
            tenant_id: Optional tenant filter

        Returns:
            Document with entities if found, None otherwise
        """
        query = (
            select(Document)
            .options(selectinload(Document.entities))
            .where(Document.id == document_id)
            .where(Document.deleted_at.is_(None))
        )
        if tenant_id is not None:
            query = query.where(Document.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        tenant_id: UUID,
        project_id: UUID | None = None,
        doc_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 20,
        include_placeholders: bool = False,
    ) -> tuple[list[Document], int]:
        """List documents for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID
            project_id: Optional project filter
            doc_type: Optional document type filter
            status: Optional status filter
            skip: Number of records to skip
            limit: Maximum number of records to return
            include_placeholders: If False, exclude placeholder documents from results

        Returns:
            Tuple of (list of Documents, total count)
        """
        base_query = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )

        if project_id is not None:
            base_query = base_query.where(Document.project_id == project_id)
        if doc_type is not None:
            base_query = base_query.where(Document.doc_type == doc_type)
        if status is not None:
            base_query = base_query.where(Document.status == status)
        if not include_placeholders and hasattr(Document, "generation_status"):
            base_query = base_query.where(
                (Document.generation_status != "placeholder")
                | (Document.generation_status.is_(None))
            )

        # Count total
        count_query = select(func.count(Document.id)).select_from(base_query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            base_query
            .offset(skip)
            .limit(limit)
            .order_by(Document.updated_at.desc())
        )
        documents = list(result.scalars().all())

        return documents, total

    async def update_document(
        self,
        document_id: UUID,
        tenant_id: UUID | None = None,
        updates: DocumentUpdate | None = None,
        status_update: DocumentStatusUpdate | None = None,
    ) -> Document | None:
        """Update a document.

        Args:
            document_id: Document UUID
            tenant_id: Optional tenant filter
            updates: Update data
            status_update: Status update data

        Returns:
            Updated Document if found, None otherwise
        """
        document = await self.get_document(document_id, tenant_id)
        if not document:
            return None

        if updates:
            if updates.title is not None:
                document.title = updates.title
            if updates.content is not None:
                document.content = updates.content
            if updates.status is not None:
                document.status = updates.status
            if updates.metadata is not None:
                document.metadata_json = updates.metadata

        if status_update:
            # Block incomplete AI-generated documents from entering formal delivery states.
            metadata = document.metadata_json or {}
            generation_status = metadata.get("generation_status")
            formal_delivery_states = [
                DocumentStatus.REVIEW.value,
                DocumentStatus.APPROVED.value,
                DocumentStatus.PUBLISHED.value,
            ]
            if (
                generation_status in NON_DELIVERABLE_GENERATION_STATUSES
                and status_update.status in formal_delivery_states
            ):
                raise ValueError(
                    f"Cannot transition {generation_status} document to '{status_update.status}'. "
                    "Document must be successfully regenerated with LLM before it can enter review/approval flow."
                )

            document.status = status_update.status
            if status_update.approved_by is not None:
                document.approved_by = status_update.approved_by

        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def transition_status(
        self,
        document_id: UUID,
        tenant_id: UUID | None,
        status_update: DocumentStatusUpdate,
        changed_by: UUID | None = None,
    ) -> Document | None:
        """Transition a document through the controlled review flow."""
        document = await self.get_document(document_id, tenant_id)
        if not document:
            return None

        current_status = document.status or DocumentStatus.DRAFT.value
        next_status = status_update.status

        if current_status == next_status:
            return document

        policy = await self.get_document_lifecycle_policy(document)
        if next_status in policy.require_reason_for and not (status_update.reason or "").strip():
            raise ValueError(f"A reason is required to transition a document to '{next_status}'")

        blockers = await self.get_status_transition_blockers(document, next_status, policy)
        if blockers:
            raise ValueError(blockers[0])

        metadata = dict(document.metadata_json or {})
        unresolved_comment_count = 0
        document.status = next_status
        metadata["status"] = next_status
        if next_status == DocumentStatus.APPROVED.value:
            document.approved_by = status_update.approved_by or changed_by
        elif status_update.approved_by is not None:
            document.approved_by = status_update.approved_by

        document.metadata_json = self._append_status_history(
            metadata=metadata,
            from_status=current_status,
            to_status=next_status,
            status_update=status_update,
            changed_by=changed_by,
            unresolved_comment_count=unresolved_comment_count,
            policy_revision=policy.revision,
        )

        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def get_status_transition_blockers(
        self,
        document: Document,
        next_status: str,
        policy: DocumentLifecyclePolicyResponse | None = None,
    ) -> list[str]:
        """Return workflow blockers without mutating the document."""
        current_status = document.status or DocumentStatus.DRAFT.value
        policy = policy or await self.get_document_lifecycle_policy(document)
        enabled_statuses = {status.key for status in policy.statuses}
        allowed_transitions = {
            (transition.from_status, transition.to_status)
            for transition in policy.transitions
        }

        if current_status == next_status:
            return []
        if next_status not in enabled_statuses:
            return [f"Document status '{next_status}' is not enabled for this project"]
        if (
            next_status == DocumentStatus.PUBLISHED.value
            and policy.publish_gates.require_approved
            and current_status != DocumentStatus.APPROVED.value
        ):
            return ["Document must be approved before it can be published"]
        if (current_status, next_status) not in allowed_transitions:
            return [f"Invalid status transition from '{current_status}' to '{next_status}'"]

        metadata = dict(document.metadata_json or {})
        generation_status = metadata.get("generation_status")
        if generation_status in NON_DELIVERABLE_GENERATION_STATUSES and next_status in FORMAL_DELIVERY_STATES:
            return [
                f"Cannot transition {generation_status} document to '{next_status}'. "
                "Document must be successfully regenerated with LLM before it can enter review/approval flow."
            ]

        if next_status == DocumentStatus.PUBLISHED.value:
            unresolved_placeholders = sorted(set(extract_placeholders(getattr(document, "content", ""))))
            if policy.publish_gates.require_resolved_placeholders and unresolved_placeholders:
                return [
                    "Document contains unresolved template placeholders and cannot be published: "
                    + ", ".join(unresolved_placeholders)
                ]
            delivery_readiness = self._get_delivery_readiness_blocker(metadata)
            if delivery_readiness:
                return [delivery_readiness]
            if policy.publish_gates.require_resolved_comments:
                unresolved_comment_count = await self.count_unresolved_comments(
                    document.id,
                    document.tenant_id,
                )
                if unresolved_comment_count > 0:
                    return [
                        f"Document has {unresolved_comment_count} unresolved comments and cannot be published"
                    ]

        return []

    def _get_delivery_readiness_blocker(self, metadata: dict[str, Any]) -> str | None:
        """Return a publish blocker from document delivery readiness metadata."""
        delivery = metadata.get("delivery") if isinstance(metadata, dict) else None
        if not isinstance(delivery, dict):
            return None
        readiness = delivery.get("delivery_readiness")
        if not isinstance(readiness, dict) or readiness.get("ready") is not False:
            return None

        blockers = [str(item) for item in readiness.get("blockers") or [] if str(item).strip()]
        unresolved_sections = [
            str(item)
            for item in readiness.get("unresolved_sections") or []
            if str(item).strip()
        ]
        low_quality_sections = [
            str(item)
            for item in readiness.get("low_quality_sections") or []
            if str(item).strip()
        ]
        if not blockers and unresolved_sections:
            blockers.append("unresolved sections: " + ", ".join(unresolved_sections))
        if not blockers and low_quality_sections:
            blockers.append("low quality sections: " + ", ".join(low_quality_sections))
        if not blockers:
            blockers.append("delivery readiness is not complete")
        return "Document delivery readiness blocks publish: " + "; ".join(blockers)

    async def get_document_lifecycle_policy(
        self,
        document: Document,
    ) -> DocumentLifecyclePolicyResponse:
        """Return the effective lifecycle policy for a document's project."""
        project_id = getattr(document, "project_id", None)
        if project_id is None:
            return default_document_lifecycle_policy()
        return await ProjectDocumentLifecyclePolicyService(self.db).get_policy(project_id)

    async def list_status_history(
        self,
        document_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """List persisted status transition history for a document."""
        document = await self.get_document(document_id, tenant_id)
        if not document:
            return []

        metadata = document.metadata_json or {}
        review_flow = metadata.get("review_flow") or {}
        return self._status_history_with_transition_ids(review_flow.get("status_history") or [])

    async def count_unresolved_comments(
        self,
        document_id: UUID,
        tenant_id: UUID | None = None,
    ) -> int:
        """Count unresolved review comments for publish gating."""
        from app.domains.collaboration.models import DocumentComment

        query = select(func.count(DocumentComment.id)).where(
            DocumentComment.document_id == document_id,
            DocumentComment.resolved.is_(False),
            DocumentComment.deleted_at.is_(None),
        )
        if tenant_id is not None:
            query = query.where(DocumentComment.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return int(result.scalar() or 0)

    def _append_status_history(
        self,
        metadata: dict[str, Any],
        from_status: str,
        to_status: str,
        status_update: DocumentStatusUpdate,
        changed_by: UUID | None,
        unresolved_comment_count: int,
        policy_revision: int,
    ) -> dict[str, Any]:
        review_flow = dict(metadata.get("review_flow") or {})
        history = list(review_flow.get("status_history") or [])
        history.append(
            {
                "transition_id": str(uuid4()),
                "from_status": from_status,
                "to_status": to_status,
                "action": status_update.action or "status_transition",
                "reason": status_update.reason,
                "changed_by": str(changed_by) if changed_by is not None else None,
                "changed_at": datetime.now(timezone.utc).isoformat(),
                "unresolved_comment_count": unresolved_comment_count,
                "policy_revision": policy_revision,
            }
        )
        review_flow["status_history"] = history
        metadata["review_flow"] = review_flow
        return metadata

    def _status_history_with_transition_ids(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched_history: list[dict[str, Any]] = []
        for index, item in enumerate(history):
            enriched_item = dict(item)
            if not enriched_item.get("transition_id"):
                payload = json.dumps(enriched_item, sort_keys=True, default=str, ensure_ascii=False)
                digest = hashlib.sha256(f"{index}:{payload}".encode("utf-8")).hexdigest()[:16]
                enriched_item["transition_id"] = f"legacy-{digest}"
            enriched_history.append(enriched_item)
        return enriched_history

    async def delete_document(
        self,
        document_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Soft delete a document.

        Args:
            document_id: Document UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        document = await self.get_document(document_id, tenant_id)
        if not document:
            return False

        document.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def create_version(
        self,
        document_id: UUID,
        tenant_id: UUID | None,
        content: str,
        changes_summary: str | None = None,
        created_by: UUID | None = None,
    ) -> DocumentVersion | None:
        """Create a new document version.

        Args:
            document_id: Document UUID
            tenant_id: Optional tenant filter
            content: Version content
            changes_summary: Summary of changes
            created_by: User ID

        Returns:
            Created DocumentVersion if document found, None otherwise
        """
        document = await self.get_document(document_id, tenant_id)
        if not document:
            return None

        next_version = document.version + 1

        # Create a baselineable version for the newly saved document content.
        new_version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document_id,
            version=next_version,
            content=content,
            changes_summary=changes_summary or f"Version {next_version}",
            created_by=created_by or document.created_by,
        )
        self.db.add(new_version)

        # Update document with new content and increment version
        document.content = content
        document.version = next_version

        await self.db.flush()
        await self.db.refresh(new_version)
        return new_version

    async def create_baseline(
        self,
        document_id: UUID,
        version_id: UUID,
        tenant_id: UUID,
        baseline_name: str,
        reason: str | None = None,
        approved_by: UUID | None = None,
    ) -> DocumentBaseline | None:
        """Create a baseline for a document version.

        Args:
            document_id: Document UUID
            version_id: Version UUID to baseline
            tenant_id: Tenant UUID
            baseline_name: Name for the baseline
            reason: Reason for creating baseline
            approved_by: User ID who approved

        Returns:
            Created DocumentBaseline if successful, None otherwise
        """
        document = await self.get_document(document_id, tenant_id)
        if not document:
            return None

        # Verify version exists
        version_result = await self.db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
        )
        version = version_result.scalar_one_or_none()
        if not version:
            return None

        baseline = DocumentBaseline(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            baseline_name=baseline_name,
            baseline_reason=reason,
            approved_by=approved_by,
            approved_at=datetime.now(timezone.utc) if approved_by else None,
        )
        self.db.add(baseline)
        await self.db.flush()
        await self.db.refresh(baseline)
        return baseline

    async def get_version_history(
        self,
        document_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[DocumentVersion]:
        """Get version history for a document.

        Args:
            document_id: Document UUID
            tenant_id: Optional tenant filter

        Returns:
            List of DocumentVersion records
        """
        query = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.tenant_id == tenant_id,
        )

        result = await self.db.execute(
            query.order_by(DocumentVersion.version.desc())
        )
        return list(result.scalars().all())

    async def rollback_to_baseline(
        self,
        baseline_id: UUID,
        tenant_id: UUID | None = None,
    ) -> Document | None:
        """Rollback document to a baseline.

        Args:
            baseline_id: Baseline UUID
            tenant_id: Optional tenant filter

        Returns:
            Updated Document if baseline found, None otherwise
        """
        baseline_result = await self.db.execute(
            select(DocumentBaseline).where(
                DocumentBaseline.id == baseline_id,
                DocumentBaseline.tenant_id == tenant_id,
            )
        )
        baseline = baseline_result.scalar_one_or_none()
        if not baseline:
            return None

        if tenant_id is not None and baseline.tenant_id != tenant_id:
            return None

        document = await self.get_document(baseline.document_id, tenant_id)
        if not document:
            return None

        # Get the baseline version content
        version_result = await self.db.execute(
            select(DocumentVersion).where(DocumentVersion.id == baseline.version_id)
        )
        version = version_result.scalar_one_or_none()
        if not version:
            return None

        # Create current version as a new version record
        current_version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document.id,
            version=document.version,
            content=document.content,
            changes_summary=f"Before rollback to baseline '{baseline.baseline_name}'",
            created_by=document.created_by,
        )
        self.db.add(current_version)

        # Rollback document content
        document.content = version.content
        document.version = document.version + 1

        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def assess_quality(
        self,
        document_id: UUID,
        tenant_id: UUID,
        quality_type: str,
        version_id: UUID | None = None,
        llm_gateway: LLMGateway | None = None,
    ) -> QualityResult:
        """Assess document quality.

        Args:
            document_id: Document UUID
            tenant_id: Tenant UUID
            quality_type: Type of quality check (consistency, completeness, mece, citation)
            version_id: Optional specific version to check
            llm_gateway: Optional LLM gateway for AI-powered assessment

        Returns:
            QualityResult with score and issues
        """
        document = await self.get_document(document_id, tenant_id)
        if not document:
            raise ValueError("Document not found")

        content = document.content
        if version_id:
            version_result = await self.db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.id == version_id,
                    DocumentVersion.document_id == document_id,
                )
            )
            version = version_result.scalar_one_or_none()
            if version:
                content = version.content

        # Perform quality assessment
        if llm_gateway:
            score, issues = await self._assess_quality_with_llm(
                content,
                quality_type,
                document.doc_type,
                llm_gateway,
            )
        else:
            score, issues = self._assess_quality_heuristic(content, quality_type)

        # Create quality result
        quality_result = QualityResult(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            quality_type=quality_type,
            score=score,
            issues_json=issues,
            checked_at=datetime.now(timezone.utc),
        )
        self.db.add(quality_result)

        # Update document quality score (average of recent checks)
        await self._update_document_quality_score(document)

        await self.db.flush()
        await self.db.refresh(quality_result)
        return quality_result

    async def _assess_quality_with_llm(
        self,
        content: str,
        quality_type: str,
        doc_type: str,
        llm_gateway: LLMGateway,
    ) -> tuple[float, dict[str, Any]]:
        """Assess quality using LLM.

        Args:
            content: Document content
            quality_type: Type of quality check
            doc_type: Document type
            llm_gateway: LLM gateway

        Returns:
            Tuple of (score, issues dict)
        """
        prompts = {
            QualityType.CONSISTENCY.value: f"""Assess the consistency of this {doc_type} document.
Check for:
- Internal contradictions
- Inconsistent terminology
- Gaps in logic flow

Document Content:
{content[:4000]}

Respond with a JSON object containing:
{{"score": 0.0-1.0, "issues": ["list of issues found"], "recommendations": ["list of recommendations"]}}
""",
            QualityType.COMPLETENESS.value: f"""Assess the completeness of this {doc_type} document.
Check for:
- Missing required sections
- Incomplete descriptions
- Unresolved placeholders

Document Content:
{content[:4000]}

Respond with a JSON object containing:
{{"score": 0.0-1.0, "issues": ["list of issues found"], "recommendations": ["list of recommendations"]}}
""",
            QualityType.MECE.value: f"""Assess the MECE (Mutually Exclusive, Collectively Exhaustive) compliance of this {doc_type} document.
Check for:
- Overlapping categories or requirements
- Missing categories or requirements
- Gaps in coverage

Document Content:
{content[:4000]}

Respond with a JSON object containing:
{{"score": 0.0-1.0, "issues": ["list of issues found"], "recommendations": ["list of recommendations"]}}
""",
            QualityType.CITATION.value: f"""Assess the citation coverage of this {doc_type} document.
Check for:
- Claims that lack supporting citations
- Missing references to sources
- Unattributed data or statements

Document Content:
{content[:4000]}

Respond with a JSON object containing:
{{"score": 0.0-1.0, "issues": ["list of issues found"], "recommendations": ["list of recommendations"]}}
""",
        }

        prompt = prompts.get(quality_type, prompts[QualityType.CONSISTENCY.value])

        try:
            response = await llm_gateway.generate(prompt, {"temperature": 0.3, "max_tokens": 2048})
            result_text = response.text

            # Parse JSON from response
            import re
            json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                score = float(result.get("score", 0.5))
                issues = {
                    "issues": result.get("issues", []),
                    "recommendations": result.get("recommendations", []),
                }
            else:
                score = 0.5
                issues = {"issues": ["Could not parse LLM response"], "recommendations": []}
        except Exception as e:
            score = 0.5
            issues = {"issues": [f"LLM assessment failed: {str(e)}"], "recommendations": []}

        return score, issues

    def _assess_quality_heuristic(
        self,
        content: str,
        quality_type: str,
    ) -> tuple[float, dict[str, Any]]:
        """Simple heuristic quality assessment (fallback when no LLM).

        Args:
            content: Document content
            quality_type: Type of quality check

        Returns:
            Tuple of (score, issues dict)
        """
        issues = []
        recommendations = []

        content_lower = content.lower()
        word_count = len(content.split())

        # Basic checks
        if word_count < 50:
            issues.append("Document content is very short")
            recommendations.append("Expand document with more detailed content")

        if quality_type == QualityType.COMPLETENESS.value:
            score = min(1.0, word_count / 500)  # Score based on length
            if word_count < 100:
                issues.append("Document appears incomplete")
        elif quality_type == QualityType.CONSISTENCY.value:
            # Simple check for repeated phrases (could indicate copy-paste issues)
            score = 0.8 if word_count > 50 else 0.5
        elif quality_type == QualityType.MECE.value:
            # Heuristic: check for list structures
            has_lists = any(marker in content for marker in ["- ", "* ", "1. ", "• "])
            score = 0.9 if has_lists else 0.7
            if not has_lists:
                recommendations.append("Consider using structured lists for better coverage")
        elif quality_type == QualityType.CITATION.value:
            # Check for reference markers
            has_citations = any(marker in content for marker in ["[", "(cite", "footnote"])
            score = 0.8 if has_citations else 0.5
            if not has_citations:
                recommendations.append("Add citations and references to support claims")
        else:
            score = 0.7

        return score, {"issues": issues, "recommendations": recommendations}

    async def _update_document_quality_score(self, document: Document) -> None:
        """Update document's average quality score.

        Args:
            document: Document to update
        """
        result = await self.db.execute(
            select(func.avg(QualityResult.score))
            .where(QualityResult.document_id == document.id)
        )
        avg_score = result.scalar()
        if avg_score is not None:
            document.quality_score = round(float(avg_score), 2)


class DocumentGenerationService:
    """Service for AI-powered document generation.

    Uses LLM Gateway with fallback routing to generate documents based on schemas
    and context.
    """

    def __init__(self, db: AsyncSession, llm_gateway: LLMGateway | None = None):
        """Initialize document generation service.

        Args:
            db: Async database session
            llm_gateway: Optional LLM gateway for generation
        """
        self.db = db
        self._llm_gateway = llm_gateway

    INTERACTIVE_CAPABILITY_PACKS: dict[str, list[dict[str, Any]]] = {
        DocumentType.BRD.value: [
            {
                "section_key": "brd.background_goals",
                "title": "背景与目标",
                "content_requirement": "记录业务痛点、核心目标、预期收益，并保持痛点到目标的可追溯关系。",
                "prompt": "先澄清业务背景、当前痛点、目标状态和可验证收益；缺失事实不得编造。",
                "required_inputs": ["pain_points", "core_objectives", "expected_benefits"],
                "quality_rules": [
                    {"rule": "每个目标必须能追溯到明确痛点", "severity": "high"},
                    {"rule": "缺失量化数据时标记为待确认", "severity": "medium"},
                ],
                "first_question": "请先用一句话说明当前业务痛点、希望改善的目标，以及这次 BRD 覆盖的业务范围。",
            },
            {
                "section_key": "brd.stakeholders",
                "title": "干系人与业务角色",
                "content_requirement": "定义业务角色、职责边界、参与流程和角色期望。",
                "prompt": "围绕谁参与、谁审批、谁使用、谁负责异常处理进行澄清。",
                "required_inputs": ["business_roles", "role_expectations"],
                "quality_rules": [{"rule": "每个角色必须说明职责或期望", "severity": "high"}],
                "first_question": "请说明本流程涉及哪些业务角色，例如仓管员、复核员、主管、财务或外部客户。",
            },
            {
                "section_key": "brd.business_flows",
                "title": "现状与目标业务流程",
                "content_requirement": "描述 As-Is 与 To-Be 流程、关键节点、责任角色、输入输出和异常路径。",
                "prompt": "先确认流程骨架，再逐节点补充角色、输入、输出、状态和异常。",
                "required_inputs": ["as_is_flow", "to_be_flow", "exceptions"],
                "quality_rules": [{"rule": "目标流程必须回应现状痛点", "severity": "high"}],
                "first_question": "请按顺序描述当前流程和期望流程，先给出主要节点即可。",
            },
            {
                "section_key": "brd.requirement_modules",
                "title": "核心需求模块",
                "content_requirement": "拆分需求模块，记录模块编码、标题、前置条件、触发条件、预期结果和异常规则。",
                "prompt": "需求模块必须来自业务目标和流程，不凭空扩展。",
                "required_inputs": ["module_candidates", "preconditions", "triggers", "expected_results"],
                "quality_rules": [{"rule": "每个模块必须包含触发条件和预期结果", "severity": "high"}],
                "first_question": "请列出你认为必须支持的核心业务模块，或说明最重要的业务动作。",
            },
            {
                "section_key": "brd.non_functional",
                "title": "非功能需求",
                "content_requirement": "记录性能、合规、安全、审计、可用性和数据留痕要求。",
                "prompt": "只写已确认的非功能要求；不确定的指标必须标记待确认。",
                "required_inputs": ["performance", "compliance_security", "auditability"],
                "quality_rules": [{"rule": "不可编造 SLA、并发量或提升比例", "severity": "high"}],
                "first_question": "请说明性能、安全、审计、合规或可用性方面是否有硬性要求。",
            },
        ],
        DocumentType.PRD.value: [
            {
                "section_key": "prd.traceability",
                "title": "BRD 血缘映射",
                "content_requirement": "建立痛点、业务需求、产品模块、页面和功能点的追踪关系。",
                "prompt": "PRD 内容必须来自上游 BRD；新增内容需显式标记。",
                "required_inputs": ["linked_brd", "pain_points", "requirement_modules"],
                "quality_rules": [{"rule": "每个功能点必须有 BRD 来源或新增标记", "severity": "high"}],
                "first_question": "请提供上游 BRD 摘要或说明 PRD 需要承接的业务痛点和模块。",
            },
            {
                "section_key": "prd.module_architecture",
                "title": "产品模块与页面架构",
                "content_requirement": "定义模块、页面、功能点和全局规则。",
                "prompt": "先生成骨架，待用户确认后再扩展详细功能。",
                "required_inputs": ["modules", "pages", "global_rules"],
                "quality_rules": [{"rule": "模块和页面必须可追溯到血缘映射", "severity": "high"}],
                "first_question": "请说明产品模块和主要页面，或确认是否由系统根据 BRD 先推断骨架。",
            },
            {
                "section_key": "prd.feature_specs",
                "title": "功能规格",
                "content_requirement": "每个功能包含流程、界面元素、前置条件、正常流程、异常处理和数据流。",
                "prompt": "按功能逐项展开，不一次性生成未经确认的大段内容。",
                "required_inputs": ["feature_list", "flows", "exceptions", "data_flow"],
                "quality_rules": [{"rule": "每个功能必须包含验收或异常处理", "severity": "high"}],
                "first_question": "请选择本轮要展开的功能，或说明最高优先级的用户任务。",
            },
            {
                "section_key": "prd.metrics_release",
                "title": "埋点、指标与发布",
                "content_requirement": "定义埋点事件、监控指标、发布条件和上线后验证计划。",
                "prompt": "指标必须可观测，缺失口径标记待确认。",
                "required_inputs": ["tracking_events", "monitoring_metrics", "release_criteria"],
                "quality_rules": [{"rule": "发布条件必须可验证", "severity": "medium"}],
                "first_question": "请说明上线验收、监控指标、埋点或发布审批方面的要求。",
            },
        ],
    }

    def _get_legacy_interactive_specs(self, doc_type: str) -> list[dict[str, Any]]:
        """Return legacy BRD/PRD section specs retained for compatibility."""
        return self.INTERACTIVE_CAPABILITY_PACKS.get(doc_type, [
            {
                "section_key": f"{doc_type}.overview",
                "title": "文档概述",
                "content_requirement": "记录当前已确认的文档目标、范围和待确认事项。",
                "prompt": "逐步澄清并生成结构化项目文档。",
                "required_inputs": ["requirements"],
                "quality_rules": [{"rule": "必须标记待确认事项", "severity": "medium"}],
                "first_question": "请先说明本次文档需要覆盖的业务范围、目标和关键约束。",
            }
        ])

    def _get_interactive_specs(self, doc_type: str) -> list[dict[str, Any]]:
        """Return full delivery workbench section specs for interactive generation."""
        if doc_type in FULL_DELIVERY_CAPABILITY_PACKS:
            return FULL_DELIVERY_CAPABILITY_PACKS[doc_type]
        if doc_type in self.INTERACTIVE_CAPABILITY_PACKS:
            return self.INTERACTIVE_CAPABILITY_PACKS[doc_type]
        return [
            {
                "section_key": f"{doc_type}.overview",
                "title": "文档概述",
                "content_requirement": "记录当前已确认的文档目标、范围和待确认事项。",
                "prompt": "逐步澄清并生成结构化项目文档。",
                "required_inputs": ["requirements", "scope", "pending_confirmations"],
                "quality_rules": [{"rule": "必须标记待确认事项", "severity": "medium"}],
                "first_question": "请先说明本次文档需要覆盖的业务范围、目标和关键约束。",
                "upstream_dependencies": [],
                "skill_labels": ["业务澄清", "结构化写入", "质量评审"],
            },
            {
                "section_key": f"{doc_type}.details",
                "title": "详细内容",
                "content_requirement": "记录用户确认过的核心事实、规则和验收口径。",
                "prompt": "只写确认事实，缺口标记待确认。",
                "required_inputs": ["confirmed_facts", "rules", "acceptance"],
                "quality_rules": [{"rule": "详细内容必须来自用户确认", "severity": "high"}],
                "first_question": "请补充这份文档必须包含的核心事实、业务规则或验收标准。",
                "upstream_dependencies": [],
                "skill_labels": ["结构化写入", "质量评审"],
            },
            {
                "section_key": f"{doc_type}.readiness",
                "title": "交付准备",
                "content_requirement": "记录评审、导出、追溯和协同交付准备度。",
                "prompt": "确认正式交付前的阻塞项和责任人。",
                "required_inputs": ["review_readiness", "export_readiness", "owner"],
                "quality_rules": [{"rule": "交付阻塞项必须有处理路径", "severity": "medium"}],
                "first_question": "请说明这份文档正式评审或导出前还有哪些阻塞项和责任人。",
                "upstream_dependencies": [],
                "skill_labels": ["协同评审", "导出编排", "质量评审"],
            },
        ]

    @staticmethod
    def _initial_entity_state(doc_type: str, specs: list[dict[str, Any]]) -> dict[str, Any]:
        """Build slot-level state used by the conversational write engine."""
        slots: dict[str, dict[str, Any]] = {}
        upstream_dependencies: list[str] = []
        for spec in specs:
            for dependency in spec.get("upstream_dependencies", []):
                if dependency not in upstream_dependencies:
                    upstream_dependencies.append(dependency)
            for slot in spec.get("required_inputs", []):
                slots[slot] = {
                    "status": "missing",
                    "section_key": spec["section_key"],
                    "evidence": [],
                }
        return {
            "doc_type": doc_type,
            "slots": slots,
            "confirmed_facts": [],
            "pending_confirmations": [],
            "revision_count": 0,
            "upstream_dependencies": upstream_dependencies,
        }

    @staticmethod
    def _skill_trace_for_section(section: DocumentGenerationSection, action: str) -> list[dict[str, Any]]:
        """Return business-facing skill trace labels for one turn."""
        labels: list[str] = []
        for spec in FULL_DELIVERY_CAPABILITY_PACKS.get(section.section_key.split(".")[0], []):
            if spec["section_key"] == section.section_key:
                labels = list(spec.get("skill_labels", []))
                break
        if not labels:
            labels = ["业务澄清", "结构化写入", "质量评审"]
        return [
            {
                "label": label,
                "status": "completed",
                "action": action,
                "section_key": section.section_key,
            }
            for label in labels
        ]

    @staticmethod
    def _append_write_log(
        session: DocumentGenerationSession,
        *,
        action: str,
        section: DocumentGenerationSection,
        old_text: str | None,
        new_text: str,
        verified: bool,
        skill_trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Append an audited write/verify record to session stash JSON."""
        stash = dict(session.stash_json or {})
        write_log = list(stash.get("write_log") or [])
        entry = {
            "index": len(write_log) + 1,
            "action": action,
            "section_key": section.section_key,
            "section_title": section.title,
            "patch_type": "replace" if old_text else "append",
            "old_text": old_text,
            "new_text": new_text,
            "verified": verified,
            "quality": section.quality_json or {},
            "skill_labels": [item["label"] for item in skill_trace],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        write_log.append(entry)
        stash["write_log"] = write_log
        stash["skill_trace"] = list(stash.get("skill_trace") or []) + skill_trace
        session.stash_json = stash
        return entry

    async def start_generation_session(
        self,
        tenant_id: UUID,
        project_id: UUID,
        doc_type: str,
        title: str | None,
        context: dict[str, Any],
        created_by: UUID,
        template_id: UUID | None = None,
    ) -> DocumentGenerationSession:
        """Start a persistent interactive generation session."""
        specs = self._get_interactive_specs(doc_type)
        required_section_keys = [
            spec["section_key"]
            for index, spec in enumerate(specs)
            if index == 0 or self._spec_has_required_quality_rule(spec)
        ]
        skippable_section_keys = [
            spec["section_key"]
            for spec in specs
            if spec["section_key"] not in set(required_section_keys)
        ]
        session = DocumentGenerationSession(
            tenant_id=tenant_id,
            project_id=project_id,
            template_id=template_id,
            doc_type=doc_type,
            title=title or f"{doc_type.upper()} Document - {datetime.now().strftime('%Y-%m-%d')}",
            status=GenerationSessionStatus.ACTIVE.value,
            generation_mode="interactive",
            current_section_key=specs[0]["section_key"],
            context_json={
                **(context or {}),
                "entity_state": self._initial_entity_state(doc_type, specs),
            },
            stash_json={"cross_section_facts": [], "write_log": [], "skill_trace": []},
            quality_summary_json={
                "mode": "interactive",
                "source": "full_delivery_workbench",
                "section_count": len(specs),
                "confirmed_sections": 0,
                "delivery_readiness": {
                    "ready": False,
                    "finalization_allowed": False,
                    "doc_type": doc_type,
                    "section_count": len(specs),
                    "resolved_sections": 0,
                    "confirmed_sections": 0,
                    "skipped_sections": [],
                    "required_section_keys": required_section_keys,
                    "skippable_section_keys": skippable_section_keys,
                    "required_sections_confirmed": False,
                    "unresolved_sections": [spec["section_key"] for spec in specs],
                    "pending_confirmations": [],
                    "low_quality_sections": [],
                    "blockers": [
                        "unresolved sections: "
                        + ", ".join(spec["section_key"] for spec in specs)
                    ],
                    "export_ready": False,
                    "review_ready": False,
                },
            },
            created_by=created_by,
        )
        self.db.add(session)
        await self.db.flush()

        for index, spec in enumerate(specs):
            self.db.add(
                DocumentGenerationSection(
                    tenant_id=tenant_id,
                    session_id=session.id,
                    section_key=spec["section_key"],
                    title=spec["title"],
                    position=index,
                    status=GenerationSectionStatus.PENDING.value,
                    prompt=spec["prompt"],
                    content_requirement=spec["content_requirement"],
                    pending_questions_json=[spec["first_question"]],
                    confirmed_facts_json=[],
                    quality_json={
                        "sufficiency_level": "L1",
                        "score": 0,
                        "required_slot_count": len(spec["required_inputs"]),
                    },
                    required_inputs=spec["required_inputs"],
                    quality_rules=spec["quality_rules"],
                )
            )

        self.db.add(
            DocumentGenerationStep(
                tenant_id=tenant_id,
                session_id=session.id,
                step_index=0,
                role="assistant",
                action_type="ask",
                section_key=specs[0]["section_key"],
                message=specs[0]["first_question"],
                patch_json={},
                quality_json={"sufficiency_level": "L1", "score": 0},
                created_by=created_by,
            )
        )
        await self.db.flush()
        return await self.get_generation_session(session.id, tenant_id)  # type: ignore[return-value]

    async def get_generation_session(
        self,
        session_id: UUID,
        tenant_id: UUID,
    ) -> DocumentGenerationSession | None:
        """Load an interactive generation session with sections and steps."""
        result = await self.db.execute(
            select(DocumentGenerationSession)
            .options(
                selectinload(DocumentGenerationSession.sections),
                selectinload(DocumentGenerationSession.steps),
            )
            .where(
                DocumentGenerationSession.id == session_id,
                DocumentGenerationSession.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_generation_sessions(
        self,
        tenant_id: UUID,
        project_id: UUID,
        status: str | None = None,
    ) -> list[DocumentGenerationSession]:
        """List interactive generation sessions for one tenant project."""
        conditions = [
            DocumentGenerationSession.tenant_id == tenant_id,
            DocumentGenerationSession.project_id == project_id,
        ]
        if status:
            conditions.append(DocumentGenerationSession.status == status)

        result = await self.db.execute(
            select(DocumentGenerationSession)
            .options(
                selectinload(DocumentGenerationSession.sections),
                selectinload(DocumentGenerationSession.steps),
            )
            .where(*conditions)
            .order_by(DocumentGenerationSession.updated_at.desc())
        )
        return list(result.scalars().all())

    async def cancel_generation_session(
        self,
        session_id: UUID,
        tenant_id: UUID,
        cancelled_by: UUID,
    ) -> DocumentGenerationSession:
        """Cancel a non-finalized interactive generation session and audit it."""
        session = await self.get_generation_session(session_id, tenant_id)
        if not session:
            raise ValueError(f"Generation session not found: {session_id}")
        if session.status == GenerationSessionStatus.FINALIZED.value:
            raise ValueError("Cannot cancel finalized generation session")
        if session.status == GenerationSessionStatus.CANCELLED.value:
            return session

        session.status = GenerationSessionStatus.CANCELLED.value
        session.quality_summary_json = {
            **(session.quality_summary_json or {}),
            "cancelled_by": str(cancelled_by),
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._add_generation_step(
            session,
            role="user",
            action_type="cancel",
            message="用户取消了文档生成会话。",
            section_key=session.current_section_key,
            created_by=cancelled_by,
            patch_json={"status": GenerationSessionStatus.CANCELLED.value},
        )
        await self.db.flush()
        return await self.get_generation_session(session.id, tenant_id)  # type: ignore[return-value]

    @staticmethod
    def _is_confirmation(message: str) -> bool:
        """Recognize short user confirmations from the prototype workflow."""
        normalized = message.strip().lower()
        return normalized in {"确认", "对", "是", "没问题", "可以", "ok", "okay", "就这样", "通过"}

    @staticmethod
    def _score_section_input(message: str, section: DocumentGenerationSection) -> dict[str, Any]:
        """Return a lightweight sufficiency score for section drafting."""
        length = len(message.strip())
        keyword_hits = sum(
            1
            for keyword in ["目标", "痛点", "流程", "角色", "异常", "模块", "安全", "审计", "指标", "验收", "需要", "优化", "人工", "发运"]
            if keyword in message
        )
        density_bonus = 20 if length >= 30 else 0
        score = min(95, max(20, length // 2 + keyword_hits * 10 + density_bonus))
        if score >= 85:
            level = "L4"
        elif score >= 65:
            level = "L3"
        elif score >= 40:
            level = "L2"
        else:
            level = "L1"
        return {
            "score": score,
            "sufficiency_level": level,
            "keyword_hits": keyword_hits,
            "rule_count": len(section.quality_rules or []),
        }

    @staticmethod
    def _draft_section_content(section: DocumentGenerationSection, facts: list[str]) -> str:
        """Build deterministic draft markdown for a section from confirmed facts."""
        fact_lines = [f"- {fact}" for fact in facts if fact.strip()]
        if not fact_lines:
            fact_lines = ["- ⚠️ 待确认：本节仍缺少业务方确认信息。"]
        pending_rules = [
            f"- ⚠️ 待确认：{rule.get('rule')}"
            for rule in (section.quality_rules or [])
            if isinstance(rule, dict) and rule.get("severity") in {"high", "medium"}
        ]
        return "\n".join([
            "### 已确认信息",
            *fact_lines,
            "",
            "### 结构化整理",
            f"- 本节目标：{section.content_requirement}",
            "- 信息来源：用户在交互式生成会话中的确认或待确认回答。",
            "",
            "### 待确认事项",
            *(pending_rules or ["- 暂无新增待确认事项。"]),
        ])

    def _section_summaries(self, session: DocumentGenerationSession) -> list[dict[str, Any]]:
        """Return compact section status summaries for the UI."""
        return [
            {
                "section_key": section.section_key,
                "title": section.title,
                "status": section.status,
                "score": (section.quality_json or {}).get("score", 0),
            }
            for section in sorted(session.sections, key=lambda item: item.position)
        ]

    @staticmethod
    def _section_has_required_quality_rule(section: DocumentGenerationSection) -> bool:
        """Treat sections with high-severity rules as required final content."""
        return any(
            isinstance(rule, dict) and rule.get("severity") == "high"
            for rule in (section.quality_rules or [])
        )

    @staticmethod
    def _spec_has_required_quality_rule(spec: dict[str, Any]) -> bool:
        return any(
            isinstance(rule, dict) and rule.get("severity") == "high"
            for rule in (spec.get("quality_rules") or [])
        )

    def _generation_readiness_policy(self, sections: list[DocumentGenerationSection]) -> dict[str, Any]:
        """Build a no-migration required/skippable policy from section specs."""
        required_section_keys = [
            section.section_key
            for section in sections
            if section.position == 0 or self._section_has_required_quality_rule(section)
        ]
        skippable_section_keys = [
            section.section_key
            for section in sections
            if section.section_key not in set(required_section_keys)
        ]
        return {
            "required_section_keys": required_section_keys,
            "skippable_section_keys": skippable_section_keys,
        }

    def _build_generation_readiness(self, session: DocumentGenerationSession) -> dict[str, Any]:
        """Evaluate whether an interactive session can become a formal document."""
        ordered_sections = sorted(session.sections, key=lambda item: item.position)
        policy = self._generation_readiness_policy(ordered_sections)
        required_section_keys = set(policy["required_section_keys"])
        skippable_section_keys = set(policy["skippable_section_keys"])
        entity_state = (session.context_json or {}).get("entity_state", {})
        pending_confirmations = list(entity_state.get("pending_confirmations") or [])
        slots = dict(entity_state.get("slots") or {})

        unresolved_sections = [
            section.section_key
            for section in ordered_sections
            if section.status not in {
                GenerationSectionStatus.CONFIRMED.value,
                GenerationSectionStatus.SKIPPED.value,
            }
        ]
        skipped_sections = [
            section.section_key
            for section in ordered_sections
            if section.status == GenerationSectionStatus.SKIPPED.value
        ]
        required_sections_skipped = [
            section_key for section_key in skipped_sections if section_key in required_section_keys
        ]
        low_quality_sections = []
        for section in ordered_sections:
            if section.status != GenerationSectionStatus.CONFIRMED.value:
                continue
            quality = section.quality_json or {}
            score = int(quality.get("score") or 0)
            level = quality.get("sufficiency_level") or "L1"
            if not section.content.strip() or score < 40 or level == "L1":
                low_quality_sections.append(section.section_key)

        missing_required_slots = sorted({
            slot_state.get("section_key")
            for slot_state in slots.values()
            if isinstance(slot_state, dict)
            and slot_state.get("section_key") in required_section_keys
            and slot_state.get("status") in {"missing", "skipped"}
        } - skippable_section_keys)

        pending_confirmation_sections = [
            str(item.get("section_key"))
            for item in pending_confirmations
            if isinstance(item, dict) and item.get("section_key")
        ]
        blockers = [
            f"unresolved sections: {', '.join(unresolved_sections)}" if unresolved_sections else "",
            (
                f"pending confirmations: {', '.join(pending_confirmation_sections)}"
                if pending_confirmation_sections
                else ""
            ),
            (
                f"required sections skipped: {', '.join(required_sections_skipped)}"
                if required_sections_skipped
                else ""
            ),
            f"low quality sections: {', '.join(low_quality_sections)}" if low_quality_sections else "",
            (
                f"required input slots missing: {', '.join(missing_required_slots)}"
                if missing_required_slots
                else ""
            ),
        ]
        blockers = [blocker for blocker in blockers if blocker]
        confirmed_count = sum(
            1
            for section in ordered_sections
            if section.status == GenerationSectionStatus.CONFIRMED.value
        )
        ready = not blockers
        return {
            "ready": ready,
            "finalization_allowed": ready,
            "export_ready": ready,
            "review_ready": confirmed_count > 0 and not pending_confirmations and not low_quality_sections,
            "doc_type": session.doc_type,
            "section_count": len(ordered_sections),
            "resolved_sections": len(ordered_sections) - len(unresolved_sections),
            "confirmed_sections": confirmed_count,
            "skipped_sections": skipped_sections,
            "required_section_keys": policy["required_section_keys"],
            "skippable_section_keys": policy["skippable_section_keys"],
            "required_sections_confirmed": not required_sections_skipped and not missing_required_slots,
            "unresolved_sections": unresolved_sections,
            "pending_confirmations": pending_confirmation_sections,
            "low_quality_sections": low_quality_sections,
            "blockers": blockers,
        }

    def _refresh_generation_quality_summary(self, session: DocumentGenerationSession) -> dict[str, Any]:
        """Synchronize quality summary with the strict finalization gate."""
        ordered_sections = sorted(session.sections, key=lambda item: item.position)
        readiness = self._build_generation_readiness(session)
        session.quality_summary_json = {
            **(session.quality_summary_json or {}),
            "confirmed_sections": readiness["confirmed_sections"],
            "drafted_sections": sum(
                1 for section in ordered_sections if section.status == GenerationSectionStatus.DRAFTED.value
            ),
            "skipped_sections": len(readiness["skipped_sections"]),
            "delivery_readiness": readiness,
        }
        return readiness

    def _next_open_section(
        self,
        session: DocumentGenerationSession,
        current: DocumentGenerationSection,
    ) -> DocumentGenerationSection:
        """Find the next section that still needs user work."""
        ordered = sorted(session.sections, key=lambda item: item.position)
        for section in ordered:
            if section.position > current.position and section.status not in {
                GenerationSectionStatus.CONFIRMED.value,
                GenerationSectionStatus.SKIPPED.value,
            }:
                return section
        return current

    async def _add_generation_step(
        self,
        session: DocumentGenerationSession,
        role: str,
        action_type: str,
        message: str,
        section_key: str | None,
        created_by: UUID | None,
        patch_json: dict[str, Any] | None = None,
        quality_json: dict[str, Any] | None = None,
    ) -> None:
        """Append one audited generation step."""
        step = DocumentGenerationStep(
            tenant_id=session.tenant_id,
            session_id=session.id,
            step_index=len(session.steps),
            role=role,
            action_type=action_type,
            section_key=section_key,
            message=message,
            patch_json=patch_json or {},
            quality_json=quality_json or {},
            created_by=created_by,
        )
        session.steps.append(step)
        self.db.add(step)

    async def continue_generation_session(
        self,
        session_id: UUID,
        tenant_id: UUID,
        user_message: str,
        action: str,
        created_by: UUID,
    ) -> SimpleNamespace:
        """Process one interactive user turn."""
        session = await self.get_generation_session(session_id, tenant_id)
        if not session:
            raise ValueError(f"Generation session not found: {session_id}")
        if session.status != GenerationSessionStatus.ACTIVE.value:
            raise ValueError("Generation session is not active")

        ordered_sections = sorted(session.sections, key=lambda item: item.position)
        current = next(
            (section for section in ordered_sections if section.section_key == session.current_section_key),
            ordered_sections[0],
        )
        normalized_action = action.lower().strip() or "answer"
        await self._add_generation_step(
            session,
            role="user",
            action_type=normalized_action,
            message=user_message,
            section_key=current.section_key,
            created_by=created_by,
        )
        session_context = dict(session.context_json or {})
        entity_state = dict(session_context.get("entity_state") or self._initial_entity_state(session.doc_type, self._get_interactive_specs(session.doc_type)))
        entity_state["slots"] = dict(entity_state.get("slots") or {})
        entity_state["confirmed_facts"] = list(entity_state.get("confirmed_facts") or [])
        entity_state["pending_confirmations"] = list(entity_state.get("pending_confirmations") or [])
        turn_skill_trace = self._skill_trace_for_section(current, normalized_action)
        turn_write_entry: dict[str, Any] | None = None

        if normalized_action == "skip":
            current.status = GenerationSectionStatus.SKIPPED.value
            current.quality_json = {"score": 0, "sufficiency_level": "L1", "skipped": True}
            for slot, slot_state in entity_state["slots"].items():
                if slot_state.get("section_key") == current.section_key:
                    entity_state["slots"][slot] = {**slot_state, "status": "skipped"}
            next_section = self._next_open_section(session, current)
            session.current_section_key = next_section.section_key
            assistant_message = next_section.pending_questions_json[0] if next_section.id != current.id else "所有章节均已处理，可以生成文档。"
            response_section = next_section
        elif normalized_action == "confirm" or self._is_confirmation(user_message):
            if not current.content:
                current.content = self._draft_section_content(current, current.confirmed_facts_json or [])
            current.status = GenerationSectionStatus.CONFIRMED.value
            current.quality_json = {**(current.quality_json or {}), "confirmed": True}
            for slot, slot_state in entity_state["slots"].items():
                if slot_state.get("section_key") == current.section_key:
                    entity_state["slots"][slot] = {
                        **slot_state,
                        "status": "confirmed",
                        "evidence": list(slot_state.get("evidence") or []) + list(current.confirmed_facts_json or []),
                    }
            entity_state["pending_confirmations"] = [
                item for item in entity_state["pending_confirmations"] if item.get("section_key") != current.section_key
            ]
            turn_write_entry = self._append_write_log(
                session,
                action="confirm",
                section=current,
                old_text=None,
                new_text=current.content,
                verified=bool(current.content.strip()),
                skill_trace=turn_skill_trace,
            )
            next_section = self._next_open_section(session, current)
            session.current_section_key = next_section.section_key
            assistant_message = next_section.pending_questions_json[0] if next_section.id != current.id else "所有章节均已处理，可以生成文档。"
            response_section = next_section
        elif normalized_action == "revise":
            old_content = current.content or ""
            old_text: str | None = None
            new_text = user_message.strip()
            if "=>" in user_message:
                old_text, new_text = [part.strip() for part in user_message.split("=>", 1)]
            elif "改为" in user_message and "把" in user_message:
                before, after = user_message.split("改为", 1)
                old_text = before.split("把", 1)[-1].strip(" ：:，,。")
                new_text = after.strip(" ：:，,。")
            if old_text and old_text in old_content:
                current.content = old_content.replace(old_text, new_text, 1)
                verified = new_text in current.content and current.content != old_content
            else:
                current.content = "\n\n".join(
                    part for part in [old_content.strip(), f"### 修订记录\n- 待核对修订：{new_text}"] if part
                )
                verified = new_text in current.content
            entity_state["revision_count"] = int(entity_state.get("revision_count") or 0) + 1
            current.status = GenerationSectionStatus.DRAFTED.value
            current.quality_json = {**(current.quality_json or {}), "revision_verified": verified}
            turn_write_entry = self._append_write_log(
                session,
                action="revise",
                section=current,
                old_text=old_text,
                new_text=new_text,
                verified=verified,
                skill_trace=turn_skill_trace,
            )
            assistant_message = "已按修订要求更新当前章节，请确认修订是否正确，或继续补充需要调整的内容。"
            response_section = current
        else:
            facts = list(current.confirmed_facts_json or [])
            if user_message.strip():
                facts.append(user_message.strip())
                entity_state["confirmed_facts"].append(
                    {
                        "section_key": current.section_key,
                        "fact": user_message.strip(),
                        "status": "drafted",
                    }
                )
            current.confirmed_facts_json = facts
            quality = self._score_section_input(user_message, current)
            current.quality_json = quality
            current.content = self._draft_section_content(current, facts)
            current.status = GenerationSectionStatus.DRAFTED.value
            current.pending_questions_json = (
                [] if quality["score"] >= 65 else [f"请补充“{current.title}”中可验证的角色、流程、指标或例外条件。"]
            )
            assistant_message = (
                f"已形成“{current.title}”草稿。请确认，或继续补充需要写入本节的信息。"
                if quality["score"] >= 40
                else current.pending_questions_json[0]
            )
            pending_confirmation = {
                "section_key": current.section_key,
                "title": current.title,
                "message": "请确认本节草稿是否可进入下一章节。",
                "quality": quality,
            }
            entity_state["pending_confirmations"] = [
                item for item in entity_state["pending_confirmations"] if item.get("section_key") != current.section_key
            ] + [pending_confirmation]
            for slot, slot_state in entity_state["slots"].items():
                if slot_state.get("section_key") == current.section_key:
                    entity_state["slots"][slot] = {
                        **slot_state,
                        "status": "drafted" if quality["score"] >= 40 else "missing",
                        "evidence": list(slot_state.get("evidence") or []) + ([user_message.strip()] if user_message.strip() else []),
                    }
            turn_write_entry = self._append_write_log(
                session,
                action="answer",
                section=current,
                old_text=None,
                new_text=current.content,
                verified=bool(current.content.strip()),
                skill_trace=turn_skill_trace,
            )
            response_section = current

        session_context["entity_state"] = entity_state
        session.context_json = session_context
        self._refresh_generation_quality_summary(session)
        await self._add_generation_step(
            session,
            role="assistant",
            action_type="reply",
            message=assistant_message,
            section_key=response_section.section_key,
            created_by=created_by,
            patch_json={"section_key": response_section.section_key, "content": response_section.content},
            quality_json=response_section.quality_json or {},
        )
        await self.db.flush()
        refreshed = await self.get_generation_session(session.id, tenant_id)
        current_response = next(
            section for section in refreshed.sections if section.section_key == response_section.section_key
        )
        return SimpleNamespace(
            session=refreshed,
            current_section=current_response,
            assistant_message=assistant_message,
            section_summaries=self._section_summaries(refreshed),
            write_log=(refreshed.stash_json or {}).get("write_log", []),
            skill_trace=turn_skill_trace,
            quality_gate=(refreshed.quality_summary_json or {}).get("delivery_readiness", {}),
            pending_confirmations=(refreshed.context_json or {}).get("entity_state", {}).get("pending_confirmations", []),
        )

    async def finalize_generation_session(
        self,
        session_id: UUID,
        tenant_id: UUID,
        created_by: UUID,
    ) -> Document:
        """Create a draft document from the current interactive session."""
        session = await self.get_generation_session(session_id, tenant_id)
        if not session:
            raise ValueError(f"Generation session not found: {session_id}")
        if session.status != GenerationSessionStatus.ACTIVE.value:
            raise ValueError("Generation session is not active")

        readiness = self._refresh_generation_quality_summary(session)
        if not readiness["ready"]:
            await self.db.flush()
            raise ValueError(
                "Cannot finalize generation session: "
                + "; ".join(readiness["blockers"])
            )

        content_lines = [f"# {session.title}", ""]
        for index, section in enumerate(sorted(session.sections, key=lambda item: item.position), start=1):
            content_lines.extend([f"## {index}. {section.title}", ""])
            if section.content.strip():
                content_lines.extend([section.content.strip(), ""])
            elif section.status == GenerationSectionStatus.SKIPPED.value:
                content_lines.extend([
                    "Section skipped during authoring; this section is optional for finalization.",
                    "",
                ])
            else:
                content_lines.extend([
                    f"⚠️ 待确认：{section.content_requirement}",
                    "",
                ])

        document = await DocumentService(self.db).create_document(
            tenant_id=tenant_id,
            project_id=session.project_id,
            doc_type=session.doc_type,
            title=session.title,
            content="\n".join(content_lines).strip() + "\n",
            created_by=created_by,
            metadata={
                "generated": True,
                "generation_mode": "interactive",
                "generation_session_id": str(session.id),
                "generation_status": "draft",
                "section_summaries": self._section_summaries(session),
                "delivery": {
                    "completion_ratio": round(
                        sum(
                            1
                            for section in session.sections
                            if section.status == GenerationSectionStatus.CONFIRMED.value
                        ) / max(1, len(session.sections)),
                        2,
                    ),
                    "quality_summary": session.quality_summary_json or {},
                    "delivery_readiness": readiness,
                    "entity_state": (session.context_json or {}).get("entity_state", {}),
                    "upstream_dependencies": (session.context_json or {}).get("entity_state", {}).get("upstream_dependencies", []),
                    "pending_confirmations": (session.context_json or {}).get("entity_state", {}).get("pending_confirmations", []),
                    "write_log_count": len((session.stash_json or {}).get("write_log", [])),
                },
            },
        )
        session.document_id = document.id
        session.status = GenerationSessionStatus.FINALIZED.value
        session.finalized_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(document)
        return document

    def _get_llm_gateway(self) -> LLMGateway | None:
        """Get LLM gateway, creating one if not already set.

        Returns:
            LLMGateway instance or None
        """
        if self._llm_gateway is not None:
            return self._llm_gateway

        try:
            return GatewayFactory.from_settings(
                primary_api_key=settings.OPENAI_API_KEY,
                primary_base_url=settings.OPENAI_BASE_URL,
                primary_model=settings.OPENAI_MODEL,
                fallback_api_key=settings.LLM_FALLBACK_API_KEY if settings.LLM_FALLBACK_API_KEY else None,
                fallback_base_url=settings.LLM_FALLBACK_BASE_URL,
                fallback_model=settings.LLM_FALLBACK_MODEL,
            )
        except Exception:
            pass
        return None

    def _llm_provider_name(self, llm: LLMGateway | None) -> str | None:
        """Return the provider selected for generation evidence."""
        if llm is None:
            return None
        primary_provider = getattr(llm, "primary_provider", None)
        if primary_provider is not None:
            return getattr(primary_provider, "name", None)
        providers = getattr(llm, "providers", None) or []
        if providers:
            return getattr(providers[0], "name", None)
        return None

    def _build_generation_evidence(
        self,
        *,
        status: str,
        prompt: str | None,
        started_at: float,
        llm: LLMGateway | None = None,
        response: Any | None = None,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        """Build non-secret generation metadata for production readiness gates."""
        provider_name = self._llm_provider_name(llm)
        model = getattr(response, "model", None)
        if model is None and llm is not None:
            primary_provider = getattr(llm, "primary_provider", None)
            model = getattr(primary_provider, "model", None)
            if model is None:
                providers = getattr(llm, "providers", None) or []
                model = getattr(providers[0], "model", None) if providers else None

        evidence: dict[str, Any] = {
            "status": status,
            "provider": provider_name,
            "model": model,
            "usage": getattr(response, "usage", None) or {},
            "finish_reason": getattr(response, "finish_reason", None),
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt_sha256": hashlib.sha256((prompt or "").encode("utf-8")).hexdigest() if prompt else None,
        }
        if error is not None:
            evidence["error_type"] = error.__class__.__name__
            evidence["error_message"] = sanitize_error_message(str(error))
        return evidence

    def _build_source_grounding_evidence(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build non-secret evidence that generation used source-backed knowledge."""
        grounding_items = context.get("source_grounding") or context.get("knowledge_grounding") or []
        if isinstance(grounding_items, dict):
            grounding_items = [grounding_items]
        if not isinstance(grounding_items, list):
            grounding_items = []

        knowledge_entry_ids: list[str] = []
        source_file_ids: list[str] = []
        markers: list[str] = []
        for item in grounding_items:
            if not isinstance(item, dict):
                continue
            knowledge_entry_id = str(item.get("knowledge_entry_id") or "").strip()
            source_file_id = str(item.get("source_file_id") or "").strip()
            marker = str(item.get("marker") or "").strip()
            if knowledge_entry_id and knowledge_entry_id not in knowledge_entry_ids:
                knowledge_entry_ids.append(knowledge_entry_id)
            if source_file_id and source_file_id not in source_file_ids:
                source_file_ids.append(source_file_id)
            if marker and marker not in markers:
                markers.append(marker)

        return {
            "knowledge_entry_ids": knowledge_entry_ids,
            "source_file_ids": source_file_ids,
            "marker_count": len(markers),
            "grounded": bool(knowledge_entry_ids and source_file_ids),
        }

    async def _record_provider_run(
        self,
        *,
        tenant_id: UUID,
        context: dict[str, Any],
        evidence: dict[str, Any],
        status: str,
        error: Exception | None = None,
    ) -> ProviderRun | None:
        """Persist provider usage evidence when generation context names a provider."""
        provider_id = context.get("provider_id")
        if not provider_id:
            return None
        try:
            provider_uuid = UUID(str(provider_id))
        except (TypeError, ValueError):
            return None
        provider_version_id = context.get("provider_version_id")
        try:
            provider_version_uuid = UUID(str(provider_version_id)) if provider_version_id else None
        except (TypeError, ValueError):
            provider_version_uuid = None

        usage = evidence.get("usage") or {}
        run = ProviderRun(
            tenant_id=tenant_id,
            provider_id=provider_uuid,
            version_id=provider_version_uuid,
            capability_type=CapabilityType.TEXT_GENERATION.value,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=round(float(evidence.get("latency_ms") or 0)),
            status=RunStatus.SUCCESS.value if status == "generated" else RunStatus.FAILURE.value,
            error_message=sanitize_error_message(str(error)) if error is not None else None,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    def _generate_structured_placeholder(
        self,
        title: str,
        doc_type: str,
        schema: Any,
        context: dict[str, Any],
    ) -> str:
        """Generate a structured placeholder when no LLM is configured.

        Creates a template with the document structure that can be filled manually
        or by regenerating when LLM is available. This is not a placeholder message
        but a pending generation flag with full structure.

        Args:
            title: Document title
            doc_type: Document type
            schema: Pydantic schema for the document type
            context: Generation context

        Returns:
            Structured placeholder document content
        """
        from app.domains.documents.document_types import (
            DocumentType, URSSchema, BRDSchema, PRDSchema,
            UserStorySchema, DetailedDesignSchema,
            InterfaceDocumentSchema, DataDictionarySchema, TestCaseSchema,
        )

        # Build structured template based on document type
        templates = {
            DocumentType.URS.value: """# {title}

## 1. 业务目标
[待填写]

## 2. 用户角色
[待填写]

## 3. 功能需求

### 3.1 需求项 1
- ID: REQ-001
- 描述: [待填写]
- 优先级: [高/中/低]
- 验收标准: [待填写]

## 4. 非功能需求
[待填写]

## 5. 约束与假设
[待填写]

## 6. 术语表
[待填写]

---
文档状态: **待生成** (需要配置 LLM Gateway 或手动填写)
项目: {project_name}
生成时间: {timestamp}
""",
            DocumentType.BRD.value: """# {title}

## 1. 概述
[待填写]

## 2. 业务流程
[待填写]

## 3. 功能范围
[待填写]

## 4. 验收标准
[待填写]

---
文档状态: **待生成**
项目: {project_name}
生成时间: {timestamp}
""",
            DocumentType.PRD.value: """# {title}

## 1. 产品概述
[待填写]

## 2. 详细需求

## 3. 用户故事

## 4. 原型链接
[待填写]

---
文档状态: **待生成**
项目: {project_name}
生成时间: {timestamp}
""",
        }

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        project_name = context.get("project_name", "Unknown Project")

        template = templates.get(doc_type, """# {title}

## 文档结构
[待填写]

---
文档状态: **待生成**
项目: {project_name}
生成时间: {timestamp}
""")

        return template.format(
            title=title,
            project_name=project_name,
            timestamp=timestamp,
        )

    def _get_schema_prompt(self, doc_type: str, context: dict[str, Any]) -> str:
        """Generate a prompt for document generation based on schema.

        Args:
            doc_type: Document type
            context: Generation context

        Returns:
            Prompt string for LLM
        """
        project_name = context.get("project_name", "Unnamed Project")
        existing_docs = context.get("existing_documents", [])
        requirements = context.get("requirements", "")
        additional_context = context.get("additional_context", "")

        schema_prompts = {
            DocumentType.URS.value: f"""Generate a User Requirements Specification (URS) document for the project: {project_name}.

This document should include:
- Business objectives
- User personas
- Functional requirements with IDs, descriptions, priority levels, and acceptance criteria
- Non-functional requirements (performance, security, usability, etc.)
- Constraints and assumptions
- A glossary of terms

{"Existing documents for context: " + str(existing_docs) if existing_docs else ""}
{"Requirements summary: " + requirements if requirements else ""}
{"Additional context: " + additional_context if additional_context else ""}

Provide a comprehensive URS document in structured format.
""",
            DocumentType.BRD.value: f"""Generate a Business Requirements Document (BRD) for the project: {project_name}.

This document should include:
- Executive summary
- Business context and background
- Stakeholder analysis
- Business rules
- Functional requirements linked to URS
- Data requirements
- Process flows
- Edge cases

{"Existing documents for context: " + str(existing_docs) if existing_docs else ""}
{"Requirements summary: " + requirements if requirements else ""}
{"Additional context: " + additional_context if additional_context else ""}

Provide a comprehensive BRD document in structured format.
""",
            DocumentType.PRD.value: f"""Generate a Product Requirements Document (PRD) for the project: {project_name}.

This document should include:
- Product goals
- User stories linked to BRD requirements
- Feature specifications
- UI/UX requirements
- Technical constraints
- Success metrics and KPIs

{"Existing documents for context: " + str(existing_docs) if existing_docs else ""}
{"Requirements summary: " + requirements if requirements else ""}
{"Additional context: " + additional_context if additional_context else ""}

Provide a comprehensive PRD document in structured format.
""",
            DocumentType.USER_STORY.value: f"""Generate a User Story for the project: {project_name}.

Each user story should follow the format: As a [user type], I want [goal] so that [benefit].

Include:
- Story ID (e.g., US-001)
- Title
- User type
- Goal
- Benefit
- Acceptance criteria
- Priority (must-have/should-have/could-have/won't-have)
- Story points (optional)
- Dependencies
- Linked requirements

{"Requirements summary: " + requirements if requirements else ""}
{"Additional context: " + additional_context if additional_context else ""}

Provide detailed user stories in structured format.
""",
            DocumentType.DETAILED_DESIGN.value: f"""Generate a Detailed Design Document for the project: {project_name}.

This document should include:
- Module overview
- Class diagrams (structure)
- Sequence diagrams for key operations
- Data models
- API specifications
- Error handling strategies
- Security considerations
- Linked user stories

{"Existing documents for context: " + str(existing_docs) if existing_docs else ""}
{"Additional context: " + additional_context if additional_context else ""}

Provide a comprehensive technical design document in structured format.
""",
            DocumentType.INTERFACE.value: f"""Generate an Interface Document for the project: {project_name}.

This document should include:
- API name and base URL
- Authentication mechanism
- Endpoint definitions (method, path, description, request/response schemas)
- Data formats supported
- Rate limits
- Versioning strategy

{"Additional context: " + additional_context if additional_context else ""}

Provide a comprehensive API specification in structured format.
""",
            DocumentType.DATA_DICTIONARY.value: f"""Generate a Data Dictionary for the project: {project_name}.

This document should include:
- Table definitions with columns (name, type, nullable, default, description, constraints)
- Index definitions
- Table relationships
- Data retention policy

{"Additional context: " + additional_context if additional_context else ""}

Provide a comprehensive data dictionary in structured format.
""",
            DocumentType.TEST_CASE.value: f"""Generate Test Cases for the project: {project_name}.

Each test case should include:
- Test case ID (e.g., TC-001)
- Test suite
- Title
- Preconditions
- Test steps (step number, action, expected result)
- Test data
- Priority (critical/high/medium/low)
- Linked user story
- Whether automated

{"Additional context: " + additional_context if additional_context else ""}

Provide comprehensive test cases in structured format.
""",
        }

        return schema_prompts.get(doc_type, f"Generate a document for project: {project_name}")

    async def generate_document(
        self,
        doc_type: str,
        project_id: UUID,
        tenant_id: UUID,
        context: dict[str, Any],
        created_by: UUID | None = None,
        template_id: UUID | None = None,
    ) -> Document:
        """Generate a document using AI.

        Args:
            doc_type: Document type to generate
            project_id: Project UUID
            tenant_id: Tenant UUID
            context: Generation context with project info, existing docs, etc.
            created_by: User ID of generator

        Returns:
            Generated Document

        Raises:
            ValueError: If doc_type is invalid or generation fails
        """
        if template_id is not None:
            return await self.generate_from_template(
                doc_type=doc_type,
                template_id=template_id,
                project_id=project_id,
                tenant_id=tenant_id,
                context=context,
                created_by=created_by,
            )

        # Validate doc_type
        if doc_type not in DOCUMENT_TYPE_SCHEMAS:
            raise ValueError(f"Invalid document type: {doc_type}")

        # Get project title from context
        title = context.get("title", f"{doc_type.upper()} Document - {datetime.now().strftime('%Y-%m-%d')}")

        # Generate content using LLM if available
        content = ""
        generation_status = "placeholder"
        generation_issues = []
        generation_evidence: dict[str, Any] = {}
        source_grounding = self._build_source_grounding_evidence(context)
        provider_run: ProviderRun | None = None
        llm = self._get_llm_gateway()
        if llm:
            prompt = self._get_schema_prompt(doc_type, context)
            started_at = time.perf_counter()
            try:
                response = await llm.generate(
                    prompt,
                    {"temperature": 0.7, "max_tokens": 4096},
                )
                content = response.text
                generation_status = "generated"
                generation_evidence = self._build_generation_evidence(
                    status=generation_status,
                    prompt=prompt,
                    started_at=started_at,
                    llm=llm,
                    response=response,
                )
                provider_run = await self._record_provider_run(
                    tenant_id=tenant_id,
                    context=context,
                    evidence=generation_evidence,
                    status=generation_status,
                )
            except Exception as e:
                # Fallback to template if LLM fails
                sanitized_error = sanitize_error_message(str(e))
                content = f"# {title}\n\nDocument content generation failed. Please manually complete this document.\n\nError: {sanitized_error}"
                generation_status = "failed"
                generation_evidence = self._build_generation_evidence(
                    status=generation_status,
                    prompt=prompt,
                    started_at=started_at,
                    llm=llm,
                    error=e,
                )
                provider_run = await self._record_provider_run(
                    tenant_id=tenant_id,
                    context=context,
                    evidence=generation_evidence,
                    status=generation_status,
                    error=e,
                )
                generation_issues.append({
                    "type": "generation_failed",
                    "message": sanitized_error,
                    "stage": "initial_generation",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        else:
            # No LLM configured - generate a structured placeholder that can be filled later
            # This is not a placeholder message but a pending generation flag
            schema = get_schema_for_doc_type(doc_type)
            content = self._generate_structured_placeholder(title, doc_type, schema, context)
            generation_status = "placeholder"
            generation_evidence = self._build_generation_evidence(
                status=generation_status,
                prompt=None,
                started_at=time.perf_counter(),
                llm=None,
            )

        # Create document
        doc_service = DocumentService(self.db)
        if provider_run is not None:
            generation_evidence["provider_run_id"] = str(provider_run.id)
        document = await doc_service.create_document(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=doc_type,
            title=title,
            content=content,
            created_by=created_by,
            metadata={
                "generated": True,
                "generation_status": generation_status,
                "generation_issues": generation_issues,
                "generation_evidence": generation_evidence,
                "source_grounding": source_grounding,
                "context_keys": list(context.keys()),
            },
        )

        return document

    async def generate_from_template(
        self,
        doc_type: str,
        template_id: UUID,
        project_id: UUID,
        tenant_id: UUID,
        context: dict[str, Any],
        created_by: UUID | None = None,
    ) -> Document:
        """Generate a document from a template.

        Args:
            doc_type: Document type to generate
            template_id: Template UUID to use
            project_id: Project UUID
            tenant_id: Tenant UUID
            context: Generation context with placeholder values
            created_by: User ID of generator

        Returns:
            Generated Document from template

        Raises:
            ValueError: If template or doc_type is invalid
        """
        # Import here to avoid circular dependency
        from app.domains.templates.service import TemplateService

        template_service = TemplateService(self.db)

        # Look up the template
        template = await template_service.get_template(template_id, tenant_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        # Get the active version of the template
        template_version = await template_service.get_active_version(template_id)
        if not template_version:
            raise ValueError(f"No active version found for template: {template_id}")

        # Get template content
        content = template_version.content

        # Substitute placeholders from context and keep evidence for release gates.
        filled_content, placeholder_evidence = self._substitute_template_placeholders_with_evidence(content, context)

        # Use LLM to fill remaining placeholders if configured
        llm = self._get_llm_gateway()
        generation_issues = []
        generation_evidence: dict[str, Any] = {}
        if llm and (
            placeholder_evidence["unresolved_placeholders"]
            or "[待填写]" in filled_content
            or "${" in filled_content
        ):
            filled_content, generation_issues, generation_evidence = await self._fill_remaining_placeholders_with_llm(
                filled_content, doc_type, context, llm
            )
            placeholder_evidence = self._build_template_placeholder_evidence(
                content=filled_content,
                context=context,
                filled_placeholders=placeholder_evidence["filled_placeholders"],
            )

        # Create document with template metadata
        doc_service = DocumentService(self.db)
        title = context.get("title", f"{doc_type.upper()} Document - {datetime.now().strftime('%Y-%m-%d')}")

        # Determine generation_status
        if generation_issues:
            if any(issue.get("type") == "placeholder_fill_failed" for issue in generation_issues):
                generation_status = "partial"
            else:
                generation_status = "failed"
        elif (
            placeholder_evidence["unresolved_placeholders"]
            or "[待填写]" in filled_content
            or "${" in filled_content
        ):
            generation_status = "placeholder"
        else:
            generation_status = "generated"

        if generation_evidence:
            generation_evidence["status"] = generation_status
        else:
            generation_evidence = self._build_generation_evidence(
                status=generation_status,
                prompt=None,
                started_at=time.perf_counter(),
                llm=llm,
            )

        document = await doc_service.create_document(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=doc_type,
            title=title,
            content=filled_content,
            created_by=created_by,
            metadata={
                "generated": True,
                "generation_status": generation_status,
                "generation_issues": generation_issues,
                "generation_evidence": generation_evidence,
                "template_placeholder_evidence": placeholder_evidence,
                "unresolved_template_placeholders": placeholder_evidence["unresolved_placeholders"],
                "template_id": str(template_id),
                "template_version": template_version.version,
                "context_keys": list(context.keys()),
            },
        )

        return document

    def _substitute_template_placeholders(
        self,
        content: str,
        context: dict[str, Any],
    ) -> str:
        """Substitute known placeholders in template content.

        Args:
            content: Template content with placeholders
            context: Context dict with values to substitute

        Returns:
            Content with placeholders substituted
        """
        result, _evidence = self._substitute_template_placeholders_with_evidence(content, context)
        return result

    def _substitute_template_placeholders_with_evidence(
        self,
        content: str,
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Substitute known placeholders and return structured evidence."""
        variables = self._template_placeholder_variables(context)
        result = substitute_placeholders(content, variables)

        for key, value in variables.items():
            replacement = str(value)
            result = result.replace(f"${{{key}}}", replacement)
            result = result.replace(f"[{key}]", replacement)

        filled_placeholders = sorted(
            {
                name
                for name in extract_placeholders(content)
                if name in variables
            }
        )
        return result, self._build_template_placeholder_evidence(
            content=result,
            context=context,
            filled_placeholders=filled_placeholders,
        )

    def _template_placeholder_variables(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build placeholder variables with common Chinese/English aliases."""
        variables: dict[str, Any] = {
            str(key): value
            for key, value in (context or {}).items()
            if value is not None
        }

        project_name = variables.get("project_name") or variables.get("项目名称")
        if project_name:
            variables.setdefault("project_name", project_name)
            variables.setdefault("项目名称", project_name)

        created_by_name = variables.get("created_by_name") or variables.get("创建人")
        if created_by_name:
            variables.setdefault("created_by_name", created_by_name)
            variables.setdefault("创建人", created_by_name)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        variables.setdefault("timestamp", timestamp)
        variables.setdefault("生成时间", timestamp)

        return variables

    def _build_template_placeholder_evidence(
        self,
        *,
        content: str,
        context: dict[str, Any],
        filled_placeholders: list[str],
    ) -> dict[str, Any]:
        """Return unresolved template placeholder evidence for metadata and gates."""
        unresolved = sorted(set(extract_placeholders(content)))
        return {
            "filled_placeholders": filled_placeholders,
            "unresolved_placeholders": unresolved,
            "context_keys": sorted(str(key) for key in (context or {}).keys()),
        }

    async def _fill_remaining_placeholders_with_llm(
        self,
        content: str,
        doc_type: str,
        context: dict[str, Any],
        llm: LLMGateway,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """Use LLM to fill remaining placeholders in template content.

        Args:
            content: Template content with unfilled placeholders
            doc_type: Document type
            context: Generation context
            llm: LLM gateway

        Returns:
            Content with placeholders filled by LLM, issues, and generation evidence
        """
        project_name = context.get("project_name", "Unknown Project")

        prompt = f"""Fill in the remaining placeholders in this {doc_type} document template for project: {project_name}.

The document currently has some placeholders marked with [待填写] or ${{placeholder}} that need to be filled.

Current document content:
{content}

Please fill in all placeholders with appropriate content based on the project context provided. Maintain the document structure and format. Respond with the complete filled document.

Context information:
{json.dumps(context, ensure_ascii=False, indent=2)}

Provide the complete filled document in the same markdown format.
"""
        started_at = time.perf_counter()
        try:
            response = await llm.generate(prompt, {"temperature": 0.7, "max_tokens": 8192})
            evidence = self._build_generation_evidence(
                status="generated",
                prompt=prompt,
                started_at=started_at,
                llm=llm,
                response=response,
            )
            return response.text, [], evidence
        except Exception as e:
            # Return original content without polluting it with HTML comments
            # Issues are returned separately for structured tracking
            evidence = self._build_generation_evidence(
                status="partial",
                prompt=prompt,
                started_at=started_at,
                llm=llm,
                error=e,
            )
            return content, [{
                "type": "placeholder_fill_failed",
                "message": str(e),
                "stage": "placeholder_fill",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }], evidence

    async def validate_generated_content(
        self,
        content: str,
        doc_type: str,
    ) -> tuple[bool, list[str]]:
        """Validate generated content against schema.

        Args:
            content: Generated content (JSON string or structured text)
            doc_type: Document type

        Returns:
            Tuple of (is_valid, list of validation errors)
        """
        schema_class = get_schema_for_doc_type(doc_type)

        try:
            # Try to parse as JSON
            data = json.loads(content)
            schema_class.model_validate(data)
            return True, []
        except json.JSONDecodeError:
            # Content is not JSON - validate as structured text
            # Check for required markdown sections and minimum content
            errors = []
            if len(content.strip()) < 50:
                errors.append("Content is too short (minimum 50 characters)")
            if not content.startswith("#"):
                errors.append("Content must be a markdown document starting with # heading")

            # Check for pending generation markers
            if "**待生成**" in content or "[待填写]" in content:
                errors.append("Document contains unfilled placeholder sections")
            if "AI-generated content would appear here" in content:
                errors.append("Document contains placeholder message - LLM not configured")

            if errors:
                return False, errors
            return True, []
        except Exception as e:
            return False, [str(e)]
