# 咨询交付 AI 工作台 v1.0 工程设计

## 1. 设计依据与交付口径

本工程以 `咨询交付 AI 工作台20260518.md` 作为唯一产品与技术依据，从当前目录重新创建完整系统。现有 Markdown 文件保留，不复用旧代码、旧手册或历史实现。

系统目标是一次性交付 v1.0 完整版本，覆盖项目空间、资料管理、文档生成、Agent 编排、技能市场、第三方集成、知识库、血缘追踪、权限审计、Word/PPTX 导入导出、运营监控、配额、缓存、熔断、Docker Compose 部署和测试体系。

除用户明确允许的 Graphify / GitNexus Provider 当前使用受控 mock/fixture 输出外，其他核心能力不得使用 mock、stub、写死数据或占位接口。未配置的第三方集成只能显示未配置或不可用，不能返回假业务数据。

## 2. 总体选择

Monorepo 采用 `apps/`、`packages/`、`infra/`、`docs/` 顶层目录组织：

```text
apps/
  api/          # FastAPI 后端
  worker/       # ARQ 异步 worker
  web/          # Next.js 前端
packages/
  contracts/    # API Contract、ProviderContract、SkillContract、ToolContract、事件契约
  shared/       # 前后端共享类型和工具函数
infra/
  docker/       # Dockerfile
  scripts/      # 运维脚本
docs/
  superpowers/  # 设计文档和实现计划
```

Monorepo 只决定代码管理方式，不降低系统可组合性，也不改变多租户模式。系统内部通过稳定 Contract、Provider Adapter、Workflow DAG、RuntimeRule、TemplateVersion 和事件机制实现低耦合、多组合和多租户隔离。

## 3. 技术栈

后端使用 FastAPI、SQLAlchemy 2、Alembic、Pydantic v2、PostgreSQL、pgvector、Redis、ARQ。前端使用 Next.js、React、TypeScript、Tailwind CSS、shadcn/ui 风格组件、`@xyflow/react` 和 `elkjs`。部署基线为 Docker Compose，包含 `web`、`api`、`worker`、`postgres`、`redis`。

数据库与存储口径如下：PostgreSQL 是权威主数据与事务中心；Redis 承担队列、缓存、锁、限流和 JWT blacklist 热缓存；`StorageProvider` 承担上传资料、Office 文件、导出文件和大型 RawArtifact 附件；pgvector 是 v1.0 默认向量检索实现，但业务层必须通过 `VectorStoreProvider` / `RetrievalService` 访问；全文检索通过 `SearchProvider` 抽象，默认可用 PostgreSQL FTS 起步；GraphRAG 图查询通过 `GraphStoreProvider` 抽象，默认使用 PostgreSQL 关系表保存权威图谱主数据，外部图数据库或图计算层仅作为可替换查询加速实现。

Python 包管理使用 `uv`，前端包管理使用 `pnpm`。测试使用 `pytest`、后端 service/route/permission/contract 测试，前端使用 TypeScript typecheck、lint 和关键页面测试。

## 4. 子系统边界

### 4.1 Enterprise Control Plane

负责租户、用户、账号密码登录、JWT Session、RBAC、ABAC、字段级权限、审计日志、配额、密钥配置、Provider Registry、i18n 配置和系统级治理。

所有业务 API、AgentTask、ProviderRun、导出任务、RAG 检索和 LLM 调用必须携带 `tenant_id`、`user_id`、`project_id` 和权限上下文。

### 4.2 Delivery Product Surface

负责 Next.js 页面、导航、工作台首页、项目空间、资料上传、文档生成、文档评审、模板中心、知识库、需求追踪矩阵、变更建议单、AgentOps、Provider Health、审计与监控页面。

前端只调用本系统 typed API client，不直接调用 LLM、Graphify、GitNexus、禅道、Jira、Confluence 或其他第三方系统。

### 4.3 Delivery Document Platform

负责文档实体、结构化字段、文档状态机、八类核心文档 Schema、文档版本、基线、diff、回滚、质量评分、变更建议、受控回写和导出前校验。

核心文档链路为 URS、BRD、PRD、User Story、详细设计、接口文档、数据字典、测试用例。下游发现上游问题时，只能创建 `ChangeRequest` 和 `FieldPatch`，不得直接覆盖上游正式基线。

### 4.4 Agent Runtime Platform

负责 `WorkflowDefinition`、`WorkflowVersion`、`AgentRun`、`AgentTask`、`ToolContract`、`SkillContract`、重试、超时、DLQ、熔断、人工接管和 AgentOps。

工作流编辑器使用 `@xyflow/react + elkjs`，运行时通过 ARQ 异步执行。Agent 节点可以组合需求澄清、文档生成、评审、调研、方法论、导出、Provider Tool 和审批节点。

### 4.5 Knowledge & Lineage Platform

负责资料入库、RawArtifact、KnowledgeEntry、KnowledgeLink、ProvenanceRecord、NormalizedGraphNode、NormalizedGraphEdge、RAG、GraphRAG、LLM Wiki、文档血缘、影响分析和需求追踪矩阵。

Graphify / GitNexus 输出不能直接进入业务知识层，必须先进入 RawArtifact，再经 GraphNormalizer 标准化，并经过权限过滤、审核和血缘绑定。大型 RawArtifact 附件进入 `StorageProvider`，数据库只保存 metadata、hash、路径、Provider 版本和血缘引用。向量检索、全文检索和图查询分别通过 `VectorStoreProvider`、`SearchProvider`、`GraphStoreProvider` 访问，避免业务层绑定 pgvector、PostgreSQL FTS 或具体图数据库。

### 4.6 Integration & Provider Platform

负责 LLM Gateway、GraphifyProvider、GitNexusProvider、NativeGraphProvider、IntegrationProvider、Webhook、Outbox、Provider Registry、ProviderVersion、ProviderCapability、ProviderHealth、灰度和回滚。

LLM Gateway 通过 OpenAI-compatible API 接入 MiniMax，环境变量为 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。Gateway 设计为数个可替换的 Provider Adapter，支持 fallback 路由：若主 Provider 调用失败或触发熔断，自动切换到备用 Provider，无需修改调用方代码。密钥不得写入代码或提交文件。

Graphify / GitNexus 当前实现真实 Adapter、契约、健康检查、RawArtifact、标准化和 contract tests，但 Provider 输出源允许使用受控 fixture/mock，因为用户已明确允许当前不连接真实服务。

第三方协作系统实现真实 IntegrationProvider 框架。禅道、Jira、Confluence、PingCode、TAPD、飞书、企微、钉钉按租户配置启用；没有配置时显示未配置，不生成假业务结果。

### 4.7 Office / PPTX Export Platform

负责 Word、Markdown、PPTX 导入导出、模板上传、模板版本、占位符识别、页面类型识别、样式保持、多模板组合、导出任务、导出制品、导出质量检查和权限过滤。

PPTX 能力分三阶段交付：**L1**（文本读取）、**L2**（结构识别、占位符解析、样式保持）、**L3**（用户模板生成与导出校验）。L1/L2 为 v1.0 基线，L3 在模板治理更成熟后实现。底层可使用 OpenXML、python-docx、python-pptx 等库，但模板治理由本系统控制（PPTX 模板必须采用纯文本框包裹 `{{变量名}}` 的严格占位符规范）。

### 4.8 Observability & Operations Platform

负责 SLA 指标、Agent 成功率、Provider 成功率、标准化失败率、导出成功率、配额用量、缓存命中率、成本、审计完整率、告警、运营报表和健康检查。

## 5. 多租户与权限设计

所有业务主表带 `tenant_id`，所有查询必须经过租户过滤。Redis key、文件存储路径、队列 job metadata、审计日志、ProviderRun、RawArtifact、导出文件都必须带租户隔离信息。

租户隔离以应用层强制过滤为主，PostgreSQL RLS 作为可选的纵深防御——仅在高风险表上启用，而非全局开启，以避免 RLS 查询开销影响系统性能。

权限链路采用 RBAC + ABAC + 字段级权限。字段级 deny/allow 必须同时作用于 API 响应、LLM Prompt 上下文、RAG/GraphRAG、Provider 标准化结果、前端展示和导出文件。

租户级 Provider、模型、第三方集成、模板、配额和密钥相互隔离。Provider Registry 支持租户级启用、禁用、灰度和回滚。

## 6. 数据与契约设计

核心数据对象包括 Tenant、User、Role、Policy、Project、ProjectMember、SourceFile、RawArtifact、Document、DocumentEntity、DocumentVersion、DocumentBaseline、QualityResult、ChangeRequest、FieldPatch、Template、TemplateVersion、WorkflowDefinition、WorkflowVersion、AgentRun、AgentTask、KnowledgeEntry、KnowledgeLink、ProvenanceRecord、LineageRecord、ProviderRun、ProviderVersion、IntegrationProvider、WebhookSubscription、OutboxEvent、ExportJob、ExportArtifact、AuditLog、MetricEvent。

`packages/contracts` 保存 API Contract、ProviderContract、SkillContract、ToolContract、事件契约、错误码、分页格式、权限上下文和共享 DTO。前后端共享契约，不共享领域服务内部实现。

## 7. 存储、队列与部署

文件存储默认使用本地 Docker volume，通过 `StorageProvider` 抽象预留 S3 / OCI 兼容 Object Storage。OCI 相关配置通过环境变量启用，不影响本地 Compose 启动。数据库只保存文件 metadata、hash、路径、权限、版本和血缘；上传资料、Word/PPTX/PDF、截图、导出文件和大型 RawArtifact 附件不得直接写入 PostgreSQL。

异步任务使用 Redis + ARQ，覆盖文档生成、资料解析、知识抽取、Provider 调用、导出、通知、Webhook 投递、质量评审和影响分析。

高增长表从初始迁移开始预留分区和归档策略：`audit_logs`、`agent_events`、`metric_events`、`provider_runs`、`webhook_delivery_events`、`outbox_events`、`llm_prompt_cache_entries` 至少支持按月分区、保留周期配置和冷热归档。搜索、向量和图谱能力必须通过 Provider 抽象层接入，允许后续替换为 OpenSearch / Elasticsearch、Qdrant / Milvus / Weaviate、Neo4j / Memgraph / AGE 等实现，而不改变领域服务调用方。

Docker Compose 提供完整运行栈：PostgreSQL + pgvector、Redis、FastAPI、ARQ worker、Next.js。生产部署到 OCI Ubuntu 时使用 `.env` 提供真实密钥、管理员账号、模型配置和存储配置。

## 8. 认证与初始化

系统采用内置账号密码登录、bcrypt 密码哈希和 JWT Session，并配合 JWT Blacklist 实现强制登出。Blacklist 以 Redis 为热缓存、数据库为持久化备份——Redis 不可用时仍可通过数据库查询阻止已 revoked 的 token，避免 Blacklist 成为系统单点故障。初始平台管理员通过环境变量初始化：

```text
BOOTSTRAP_ADMIN_EMAIL
BOOTSTRAP_ADMIN_PASSWORD
BOOTSTRAP_ADMIN_NAME
```

代码不写死管理员账号或密码。配置层预留 OIDC 参数，但当前不依赖外部 SSO。

## 9. 测试与验收

后端必须覆盖 service、route、permission、contract（含 ProviderContract fixture replay）、migration、export、provider、workflow、queue、tenant isolation 测试。前端必须覆盖 typecheck、lint、关键页面加载、权限态、空态、错误态和长任务进度态。

关键验收链路包括：

1. 管理员初始化、登录、创建租户和用户。
2. 创建项目、上传资料、解析并形成 SourceFile、RawArtifact、KnowledgeEntry。
3. 生成 URS、BRD、PRD、User Story、详细设计、接口文档、数据字典、测试用例。
4. 形成 DocumentVersion、DocumentBaseline、QualityResult、LineageRecord。
5. 下游变更触发 ChangeRequest、FieldPatch、影响分析和受控回写。
6. 使用 Workflow DAG 编排 Agent 并通过 ARQ 执行。
7. 调用 MiniMax LLM Gateway 生成和评审内容。
8. Graphify / GitNexus fixture Provider 输出进入 RawArtifact 并标准化。
9. 导出 Word、Markdown、PPTX，并记录 ExportJob、ExportArtifact 和审计。
10. 多租户、字段级权限、导出过滤、Prompt 裁剪和审计测试通过。

## 10. 不做事项

不实现完整 IDE，不实现 Figma 类画布，不让 GitNexus 自动创建或提交 PR，不替代 Jira / Confluence / 禅道 / PingCode / TAPD / 飞书等外部协作系统，不让外部 Provider 决定本系统权限、审计、版本、正式文档基线或业务知识主数据。

**已知降级（v1.0）**：
- 实时协作采用模块级悲观锁，CRDT 方案（Yjs + WebSocket + TipTap CollaborationCursor）因 Python/Node.js 生态不兼容问题延期至 v2.0。
- LLM Prompt 上下文字段级裁剪在 v1.0 标记为 P2，优先实现 API 响应过滤和导出过滤。
- PPTX 能力分 L1/L2/L3 三阶段交付，L3 用户模板生成与导出校验延期至 v2.0。

## 11. 设计结论

本工程采用模块化 Monorepo，但运行时坚持低耦合：核心领域服务通过 Contract 通信，外部能力通过 Provider Adapter 接入，长任务通过队列和事件解耦，多租户和权限作为横切治理强制执行。该设计不影响多组合能力，也不影响多租户能力，适合在当前目录一次性建设完整 v1.0 系统。
