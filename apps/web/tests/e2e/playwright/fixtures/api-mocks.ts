import { Page } from '@playwright/test'
import * as MOCK from './mock-data'

type SetupApiMockOptions = {
  documents?: any[]
  comments?: any[]
  statusHistory?: any[]
  statusCapabilities?: any[]
}

export async function setupApiMocks(page: Page, options: SetupApiMockOptions = {}) {
  const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))
  let documents: any[] = clone(options.documents ?? MOCK.MOCK_DOCUMENTS)
  let comments: any[] = clone(options.comments ?? MOCK.MOCK_COMMENTS)
  let versions: any[] = clone(MOCK.MOCK_VERSIONS)
  let baselines: any[] = clone(MOCK.MOCK_BASELINES)
  let snapshots: any[] = clone(MOCK.MOCK_SNAPSHOTS)
  let statusHistory: any[] = clone(options.statusHistory ?? [])
  let templateSections: any[] = clone(MOCK.MOCK_TEMPLATE_SECTIONS)
  let templates: any[] = clone(MOCK.MOCK_TEMPLATE)
  let templateVersions: any[] = clone(MOCK.MOCK_TEMPLATE_VERSIONS)
  let traceabilityImpactAnalysis = clone(MOCK.MOCK_TRACEABILITY_BOARD_IMPACT)
  let skillCatalog: any[] = clone(MOCK.MOCK_SKILL_CATALOG)
  let agentProfiles: any[] = clone(MOCK.MOCK_AGENT_PROFILES)
  let agentRuns: any[] = clone(MOCK.MOCK_AGENT_RUNS)
  let agentTasks: any[] = clone(MOCK.MOCK_AGENT_TASKS)
  let agentEvents: any[] = clone(MOCK.MOCK_AGENT_EVENTS)
  let workflows: any[] = clone(MOCK.MOCK_WORKFLOWS)
  let workflowVersions: any[] = clone(MOCK.MOCK_WORKFLOW_VERSIONS)
  let exportJobs: any[] = clone(MOCK.MOCK_EXPORTS)
  let sourceFiles: any[] = clone(MOCK.MOCK_SOURCE_FILES)
  let projectInvitations: any[] = [
    {
      id: 'invitation-e2e-001',
      project_id: 'project-e2e-001',
      email: 'consultant@example.com',
      status: 'active',
      expires_at: new Date(Date.now() + 86400000).toISOString(),
      accepted_at: null,
      revoked_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ]
  let generationSessions: any[] = []
  let notifications: any[] = [
    {
      id: 'notification-review-001',
      tenant_id: 'tenant-e2e-001',
      user_id: MOCK.MOCK_USER.id,
      actor_id: 'user-reviewer-001',
      project_id: 'project-e2e-001',
      category: 'document_lifecycle',
      priority: 'high',
      title: '文档待评审',
      body: '《WMS 升级 PRD》已进入待评审状态。',
      action_url: '/projects/project-e2e-001/documents/doc-e2e-001',
      entity_type: 'document',
      entity_id: 'doc-e2e-001',
      metadata_json: {},
      read_at: null,
      archived_at: null,
      expires_at: null,
      ack_required: true,
      acknowledged_at: null,
      ack_deadline_at: '2026-06-07T09:30:00Z',
      escalation_level: 1,
      escalated_at: '2026-06-07T09:31:00Z',
      created_at: '2026-06-07T08:30:00Z',
      updated_at: '2026-06-07T08:30:00Z',
    },
    {
      id: 'notification-agent-001',
      tenant_id: 'tenant-e2e-001',
      user_id: MOCK.MOCK_USER.id,
      actor_id: null,
      project_id: 'project-e2e-001',
      category: 'agent_run',
      priority: 'urgent',
      title: '需求评审工作流失败',
      body: 'Provider 暂不可用，请查看执行记录。',
      action_url: '/agent-ops?run_id=run-e2e-failed',
      entity_type: 'agent_run',
      entity_id: 'run-e2e-failed',
      metadata_json: {},
      read_at: null,
      archived_at: null,
      expires_at: null,
      ack_required: false,
      acknowledged_at: null,
      ack_deadline_at: null,
      escalation_level: 0,
      escalated_at: null,
      created_at: '2026-06-07T08:00:00Z',
      updated_at: '2026-06-07T08:00:00Z',
    },
  ]
  let notificationPreference = {
    id: 'notification-preference-001',
    tenant_id: 'tenant-e2e-001',
    user_id: MOCK.MOCK_USER.id,
    in_app_enabled: true,
    email_enabled: false,
    enabled_categories: [],
    min_priority: 'low',
    daily_digest: false,
    ack_timeout_minutes: 60,
    created_at: '2026-06-07T08:00:00Z',
    updated_at: '2026-06-07T08:00:00Z',
  }
  let notificationDeliveries = [
    {
      id: 'delivery-failed-001',
      tenant_id: 'tenant-e2e-001',
      channel: 'email',
      recipient: 'ops@example.com',
      title: '告警邮件投递失败',
      body: 'SMTP 暂不可用',
      status: 'failed',
      retry_count: '3',
      error_message: 'SMTP unavailable',
      metadata_json: {},
      sent_at: null,
      next_retry_at: null,
      created_at: '2026-06-07T08:00:00Z',
      updated_at: '2026-06-07T08:00:00Z',
    },
  ]
  let projectLifecyclePolicy = {
    revision: 1,
    statuses: [
      { key: 'draft', label: '草稿' },
      { key: 'writing', label: '编写中' },
      { key: 'pending_review', label: '待评审' },
      { key: 'review', label: '评审' },
      { key: 'in_review', label: '评审中' },
      { key: 'revision_required', label: '待修订' },
      { key: 'approved', label: '已批准' },
      { key: 'published', label: '已发布' },
      { key: 'archived', label: '已归档' },
    ],
    transitions: [
      { from_status: 'draft', to_status: 'writing' },
      { from_status: 'draft', to_status: 'pending_review' },
      { from_status: 'draft', to_status: 'review' },
      { from_status: 'draft', to_status: 'archived' },
      { from_status: 'writing', to_status: 'draft' },
      { from_status: 'writing', to_status: 'pending_review' },
      { from_status: 'writing', to_status: 'review' },
      { from_status: 'writing', to_status: 'archived' },
      { from_status: 'pending_review', to_status: 'review' },
      { from_status: 'pending_review', to_status: 'in_review' },
      { from_status: 'pending_review', to_status: 'revision_required' },
      { from_status: 'pending_review', to_status: 'approved' },
      { from_status: 'pending_review', to_status: 'archived' },
      { from_status: 'review', to_status: 'draft' },
      { from_status: 'review', to_status: 'in_review' },
      { from_status: 'review', to_status: 'revision_required' },
      { from_status: 'review', to_status: 'approved' },
      { from_status: 'review', to_status: 'archived' },
      { from_status: 'in_review', to_status: 'revision_required' },
      { from_status: 'in_review', to_status: 'approved' },
      { from_status: 'in_review', to_status: 'archived' },
      { from_status: 'revision_required', to_status: 'writing' },
      { from_status: 'revision_required', to_status: 'pending_review' },
      { from_status: 'revision_required', to_status: 'review' },
      { from_status: 'revision_required', to_status: 'archived' },
      { from_status: 'approved', to_status: 'review' },
      { from_status: 'approved', to_status: 'revision_required' },
      { from_status: 'approved', to_status: 'published' },
      { from_status: 'approved', to_status: 'archived' },
      { from_status: 'published', to_status: 'archived' },
    ],
    require_reason_for: [],
    publish_gates: {
      require_approved: true,
      require_resolved_comments: true,
      require_resolved_placeholders: true,
    },
  }
  const projectLaunchBlueprints = [
    {
      key: 'consulting-discovery',
      name: '咨询调研与需求澄清',
      description: '用于访谈、现状调研、问题澄清和业务需求确认。',
      scenarios: ['咨询调研', '需求澄清'],
      document_types: ['urs', 'brd'],
      workflow_template_ids: ['brd-document-generation', 'document-quality-assessment'],
      checks: ['项目负责人已加入', '初始交付文档已规划', '推荐工作流已就绪'],
      next_actions: ['导入调研资料', '启动需求澄清'],
    },
    {
      key: 'product-delivery',
      name: '产品需求到交付',
      description: '覆盖用户需求、业务需求、产品设计、详细设计与测试验收。',
      scenarios: ['产品建设', '业务系统交付'],
      document_types: ['urs', 'brd', 'prd', 'detailed_design', 'test_case'],
      workflow_template_ids: ['brd-document-generation', 'document-quality-assessment', 'human-approval-delivery-pipeline'],
      checks: ['项目负责人已加入', '核心交付链已规划', '质量和审批工作流已就绪'],
      next_actions: ['导入需求资料', '开始对话式编写', '确认交付里程碑'],
    },
    {
      key: 'system-modernization',
      name: '系统升级与迁移',
      description: '覆盖现状评估、需求、设计、接口、数据和测试交付链。',
      scenarios: ['遗留系统升级', '平台迁移'],
      document_types: ['urs', 'brd', 'prd', 'detailed_design', 'interface', 'data_dictionary', 'test_case'],
      workflow_template_ids: ['change-impact-governance', 'parallel-quality-review', 'human-approval-delivery-pipeline'],
      checks: ['项目负责人已加入', '迁移交付链已规划', '变更治理和审批工作流已就绪'],
      next_actions: ['导入现状资料', '建立接口与数据清单'],
    },
  ]
  let projectLaunchPlan = {
    id: 'launch-plan-e2e-001',
    tenant_id: 'tenant-e2e-001',
    project_id: MOCK.MOCK_PROJECT.id,
    blueprint_key: 'product-delivery',
    status: 'ready',
    config_json: {
      document_types: ['urs', 'brd', 'prd', 'detailed_design', 'test_case'],
      workflow_template_ids: ['brd-document-generation', 'document-quality-assessment'],
      project_settings: { launch_blueprint: 'product-delivery', launch_status: 'ready' },
    },
    checks_json: [
      { key: 'owner', label: '项目负责人已加入', status: 'passed' },
      { key: 'documents', label: '初始交付文档已规划', status: 'passed' },
      { key: 'workflows', label: '推荐工作流已就绪', status: 'passed' },
    ],
    results_json: {
      documents: { created: 5, existing: 0 },
      workflows: { selected: ['brd-document-generation', 'document-quality-assessment'] },
      next_actions: ['导入需求资料', '开始对话式编写'],
    },
    error_message: null,
    attempt_count: 1,
    created_by: MOCK.MOCK_USER.id,
    completed_at: '2026-06-07T09:00:00Z',
    created_at: '2026-06-07T09:00:00Z',
    updated_at: '2026-06-07T09:00:00Z',
  }
  let projectDeliveryPlan: any = {
    id: 'delivery-plan-e2e-001',
    tenant_id: 'tenant-e2e-001',
    project_id: MOCK.MOCK_PROJECT.id,
    blueprint_key: 'product-delivery',
    status: 'attention',
    summary_json: {},
    settings_json: { gate_policy: 'governed' },
    created_by: MOCK.MOCK_USER.id,
    started_at: '2026-06-07T09:00:00Z',
    completed_at: null,
    created_at: '2026-06-07T09:00:00Z',
    updated_at: '2026-06-07T09:00:00Z',
    summary: {
      total_count: 4,
      completed_count: 1,
      blocked_count: 1,
      overdue_count: 0,
      progress_percent: 25,
      next_milestone_id: 'milestone-core-authoring',
      blockers: ['评审与追溯'],
    },
    milestones: [
      { id: 'milestone-scope-readiness', key: 'scope-readiness', title: '资料与范围确认', description: '确认项目范围、输入资料和交付责任。', status: 'completed', priority: 'high', order_index: 0, due_at: null, planned_start_at: null, completed_at: '2026-06-08T09:00:00Z', owner_id: MOCK.MOCK_USER.id, required_document_types_json: ['urs'], required_workflow_template_ids_json: [], gate_results_json: [{ key: 'required-documents', status: 'passed', message: '必需文档已就绪' }], metadata_json: {}, tenant_id: 'tenant-e2e-001', project_id: MOCK.MOCK_PROJECT.id, plan_id: 'delivery-plan-e2e-001', created_at: '2026-06-07T09:00:00Z', updated_at: '2026-06-08T09:00:00Z' },
      { id: 'milestone-core-authoring', key: 'core-authoring', title: '核心文档编写', description: '完成核心需求和设计文档。', status: 'planned', priority: 'high', order_index: 1, due_at: '2026-06-20T09:00:00Z', planned_start_at: null, completed_at: null, owner_id: MOCK.MOCK_USER.id, required_document_types_json: ['urs', 'brd'], required_workflow_template_ids_json: [], gate_results_json: [{ key: 'required-documents', status: 'passed', message: '必需文档已就绪' }], metadata_json: {}, tenant_id: 'tenant-e2e-001', project_id: MOCK.MOCK_PROJECT.id, plan_id: 'delivery-plan-e2e-001', created_at: '2026-06-07T09:00:00Z', updated_at: '2026-06-07T09:00:00Z' },
      { id: 'milestone-review-traceability', key: 'review-traceability', title: '评审与追溯', description: '完成文档评审、批准和追溯关系检查。', status: 'blocked', priority: 'high', order_index: 2, due_at: null, planned_start_at: null, completed_at: null, owner_id: MOCK.MOCK_USER.id, required_document_types_json: ['urs', 'brd'], required_workflow_template_ids_json: [], gate_results_json: [{ key: 'document-approval', status: 'blocked', message: '文档必须批准或发布：BRD', action_href: `/projects/${MOCK.MOCK_PROJECT.id}/documents` }], metadata_json: {}, tenant_id: 'tenant-e2e-001', project_id: MOCK.MOCK_PROJECT.id, plan_id: 'delivery-plan-e2e-001', created_at: '2026-06-07T09:00:00Z', updated_at: '2026-06-07T09:00:00Z' },
      { id: 'milestone-release-delivery', key: 'release-delivery', title: '交付发布', description: '通过交付门禁并发布完整项目成果。', status: 'planned', priority: 'critical', order_index: 3, due_at: null, planned_start_at: null, completed_at: null, owner_id: MOCK.MOCK_USER.id, required_document_types_json: ['urs', 'brd', 'prd'], required_workflow_template_ids_json: [], gate_results_json: [{ key: 'required-documents', status: 'blocked', message: '缺少必需文档' }], metadata_json: {}, tenant_id: 'tenant-e2e-001', project_id: MOCK.MOCK_PROJECT.id, plan_id: 'delivery-plan-e2e-001', created_at: '2026-06-07T09:00:00Z', updated_at: '2026-06-07T09:00:00Z' },
    ],
  }
  let projectAcceptance: any = {
    project_id: MOCK.MOCK_PROJECT.id,
    customer_name: '',
    contact_name: '',
    contact_email: '',
    decision: 'pending',
    notes: '',
    items: [],
    updated_by: null,
    accepted_at: null,
    closed_at: null,
    package_ready: true,
    gate: { status: 'blocked', label: '关闭门禁未通过', blockers: ['客户尚未给出可交付的验收结论'], warnings: [] },
  }
  let tenantApiKeys: any[] = [
    {
      id: 'api-key-e2e-active',
      tenant_id: 'tenant-e2e-001',
      name: 'GitNexus Provider 生产接入',
      key_prefix: 'amx_live_gnx',
      permissions: ['read', 'write', 'manage_settings'],
      status: 'active',
      created_by_id: MOCK.MOCK_USER.id,
      revoked_by_id: null,
      last_used_at: '2026-06-04T10:15:00Z',
      expires_at: null,
      revoked_at: null,
      created_at: '2026-06-01T09:00:00Z',
      updated_at: '2026-06-04T10:15:00Z',
    },
    {
      id: 'api-key-e2e-revoked',
      tenant_id: 'tenant-e2e-001',
      name: '旧版导出自动化',
      key_prefix: 'amx_old_exp',
      permissions: ['read'],
      status: 'revoked',
      created_by_id: MOCK.MOCK_USER.id,
      revoked_by_id: MOCK.MOCK_USER.id,
      last_used_at: null,
      expires_at: null,
      revoked_at: '2026-06-03T11:00:00Z',
      created_at: '2026-05-28T09:00:00Z',
      updated_at: '2026-06-03T11:00:00Z',
    },
  ]

  const findDocument = (docId: string) => documents.find((document) => document.id === docId) || documents[0]
  const findSkill = (skillId: string) => skillCatalog.find((skill) => skill.id === skillId) || skillCatalog[0]
  const findAgentProfile = (agentId: string) => agentProfiles.find((agent) => agent.id === agentId) || agentProfiles[0]
  const findWorkflow = (workflowId: string | null | undefined) => workflows.find((workflow) => workflow.id === workflowId) || workflows[0]
  const findWorkflowVersion = (workflowId: string | null | undefined) =>
    workflowVersions.find((version) => version.workflow_definition_id === workflowId && version.is_active) ||
    workflowVersions.find((version) => version.workflow_definition_id === workflowId) ||
    workflowVersions[0]
  const findGenerationSession = (sessionId: string) => generationSessions.find((session) => session.id === sessionId) || generationSessions[0]
  const createGenerationSession = (overrides: Record<string, any> = {}) => {
    const now = overrides.updated_at || new Date().toISOString()
    const docType = overrides.doc_type || 'brd'
    const sessionId = overrides.id || `gen-session-${docType}-${Date.now()}`
    const sections = [
      ['brd.background_goals', '背景与目标'],
      ['brd.stakeholders', '干系人与业务角色'],
      ['brd.business_flows', '现状与目标业务流程'],
      ['brd.requirement_modules', '核心需求模块'],
      ['brd.non_functional', '非功能需求'],
    ].map(([section_key, title], index) => ({
      id: `${sessionId}-section-${index + 1}`,
      tenant_id: 'tenant-e2e-001',
      session_id: sessionId,
      section_key: docType === 'prd' ? section_key.replace('brd.', 'prd.') : section_key,
      title,
      position: index,
      status: overrides.section_statuses?.[index] || (index === 0 ? 'drafted' : 'pending'),
      prompt: '按章节逐步生成。',
      content_requirement: `补充${title}。`,
      content: index === 0 ? '### 已确认信息\n- WMS 批次分配依赖人工经验，错发率高。\n\n### 待确认事项\n- 补充可验证指标。' : '',
      pending_questions_json: index === 0 ? ['请先用一句话说明当前业务痛点和目标。'] : [`请补充${title}。`],
      confirmed_facts_json: index === 0 ? ['WMS 批次分配依赖人工经验，错发率高。'] : [],
      quality_json: { score: index === 0 ? 72 : 0, sufficiency_level: index === 0 ? 'L3' : 'L1' },
      required_inputs: [],
      quality_rules: [],
      created_at: now,
      updated_at: now,
    }))
    const defaultEntityState = {
      doc_type: docType,
      upstream_dependencies: docType === 'brd' ? ['urs'] : ['prd'],
      pending_confirmations: [],
      slots: { scope: { status: 'drafted' } },
    }
    const contextOverride = overrides.context_json || {}
    const entityStateOverride = contextOverride.entity_state || {}

    return {
      id: sessionId,
      tenant_id: 'tenant-e2e-001',
      project_id: overrides.project_id || 'project-e2e-001',
      document_id: overrides.document_id || null,
      template_id: overrides.template_id || null,
      doc_type: docType,
      title: overrides.title || 'WMS 升级 BRD 会话',
      status: overrides.status || 'active',
      generation_mode: 'interactive',
      current_section_key: overrides.current_section_key || sections[0].section_key,
      context_json: {
        requirements: 'WMS 升级',
        language: 'zh-CN',
        ...contextOverride,
        entity_state: {
          ...defaultEntityState,
          ...entityStateOverride,
          doc_type: entityStateOverride.doc_type || docType,
          upstream_dependencies: entityStateOverride.upstream_dependencies || defaultEntityState.upstream_dependencies,
          pending_confirmations: entityStateOverride.pending_confirmations || [],
        },
      },
      stash_json: overrides.stash_json || {
        cross_section_facts: ['WMS 批次分配依赖人工经验，错发率高。'],
        write_log: [
          {
            index: 1,
            action: 'answer',
            section_key: sections[0].section_key,
            section_title: sections[0].title,
            patch_type: 'append',
            old_text: null,
            new_text: sections[0].content,
            verified: true,
            skill_labels: ['业务澄清', '结构化写入', '质量评审'],
          },
        ],
        skill_trace: [{ label: '业务澄清', status: 'completed', action: 'answer', section_key: sections[0].section_key }],
      },
      quality_summary_json: {
        mode: 'interactive',
        section_count: sections.length,
        confirmed_sections: overrides.confirmed_sections || 0,
        delivery_readiness: {
          ready: false,
          export_ready: false,
          review_ready: false,
          blockers: ['仍有章节未确认'],
        },
      },
      created_by: 'user-admin-001',
      finalized_at: overrides.finalized_at || null,
      created_at: now,
      updated_at: now,
      sections,
      steps: overrides.steps || [
        {
          id: `${sessionId}-step-1`,
          tenant_id: 'tenant-e2e-001',
          session_id: sessionId,
          step_index: 0,
          role: 'assistant',
          action_type: 'ask',
          section_key: sections[0].section_key,
          message: '请先用一句话说明当前业务痛点和目标。',
          patch_json: {},
          quality_json: {},
          created_by: 'user-admin-001',
          created_at: now,
          updated_at: now,
        },
      ],
    }
  }
  generationSessions = [
    createGenerationSession({
      id: 'gen-session-e2e-active',
      title: 'WMS 升级 BRD 会话',
      updated_at: '2026-05-26T08:30:00.000Z',
    }),
    createGenerationSession({
      id: 'gen-session-e2e-finalized',
      title: '会员运营 PRD 会话',
      doc_type: 'prd',
      status: 'finalized',
      document_id: 'doc-e2e-001',
      finalized_at: '2026-05-26T07:00:00.000Z',
      updated_at: '2026-05-26T07:00:00.000Z',
      confirmed_sections: 5,
      section_statuses: ['confirmed', 'confirmed', 'confirmed', 'confirmed', 'confirmed'],
    }),
  ]
  const hydrateAgentProfile = (profile: any) => ({
    ...profile,
    skill_bindings: (profile.skill_bindings || []).map((binding: any, index: number) => ({
      id: binding.id || `binding-${profile.id}-${index}`,
      tenant_id: binding.tenant_id || profile.tenant_id,
      agent_profile_id: profile.id,
      skill_id: binding.skill_id,
      order_index: binding.order_index ?? index,
      is_required: binding.is_required ?? true,
      skill: findSkill(binding.skill_id),
    })),
  })
  const normalizeActiveVersion = (activeVersionId: string) => {
    templateVersions = templateVersions.map((version) => ({
      ...version,
      is_active: version.id === activeVersionId ? 'true' : 'false',
    }))
  }

  // ==================== 1. IDENTITY & AUTH ====================

  // 登录接口
  await page.route('**/api/v1/identity/auth/login', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'mock-jwt-token-1234567890abcdef',
          token_type: 'Bearer',
          expires_in: 3600,
        }),
      })
    }
  })

  // 获取当前用户
  await page.route('**/api/v1/identity/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_USER),
    })
  })

  let integrations: any[] = [
    {
      id: 'integration-e2e-zentao',
      tenant_id: 'tenant-e2e-001',
      provider_type: 'zentao',
      name: '禅道需求同步',
      config_json: { base_url: 'https://zentao.example.com', api_key: 'configured-token', health_path: '/health' },
      is_enabled: true,
      last_sync_at: '2026-06-12T01:00:00Z',
      created_at: '2026-06-10T01:00:00Z',
      updated_at: '2026-06-12T01:00:00Z',
    },
    {
      id: 'integration-e2e-confluence',
      tenant_id: 'tenant-e2e-001',
      provider_type: 'confluence',
      name: 'Confluence 知识库',
      config_json: { base_url: 'https://confluence.example.com' },
      is_enabled: true,
      last_sync_at: null,
      created_at: '2026-06-10T02:00:00Z',
      updated_at: '2026-06-10T02:00:00Z',
    },
  ]
  let integrationBindings: any[] = [
    {
      id: 'binding-e2e-001',
      tenant_id: 'tenant-e2e-001',
      integration_provider_id: 'integration-e2e-zentao',
      project_id: MOCK.MOCK_PROJECT.id,
      name: 'WMS 项目需求同步',
      scope_json: { types: ['story', 'bug'] },
      field_mapping_json: { title: 'title', content: 'description' },
      cursor_json: { page: 1 },
      is_enabled: true,
      last_sync_status: 'completed',
      last_synced_at: '2026-06-12T01:00:00Z',
      last_error: null,
      created_by: MOCK.MOCK_USER.id,
      created_at: '2026-06-10T03:00:00Z',
      updated_at: '2026-06-12T01:00:00Z',
    },
    {
      id: 'binding-e2e-002',
      tenant_id: 'tenant-e2e-001',
      integration_provider_id: 'integration-e2e-zentao',
      project_id: MOCK.MOCK_PROJECT.id,
      name: 'WMS 缺陷同步',
      scope_json: { types: ['bug'] },
      field_mapping_json: { title: 'title', content: 'steps' },
      cursor_json: {},
      is_enabled: true,
      last_sync_status: 'partial',
      last_synced_at: '2026-06-11T09:00:00Z',
      last_error: '1 条外部事项缺少标题',
      created_by: MOCK.MOCK_USER.id,
      created_at: '2026-06-10T03:30:00Z',
      updated_at: '2026-06-11T09:00:00Z',
    },
  ]
  let outboxEvents: any[] = [
    {
      id: 'outbox-e2e-001',
      tenant_id: 'tenant-e2e-001',
      aggregate_type: 'document',
      aggregate_id: 'doc-e2e-001',
      event_type: 'document.published',
      payload: { title: 'WMS 升级 PRD' },
      published: false,
      published_at: null,
      created_at: '2026-06-12T00:30:00Z',
    },
    {
      id: 'outbox-e2e-002',
      tenant_id: 'tenant-e2e-001',
      aggregate_type: 'project',
      aggregate_id: MOCK.MOCK_PROJECT.id,
      event_type: 'project.delivery_ready',
      payload: { project: MOCK.MOCK_PROJECT.name },
      published: false,
      published_at: null,
      created_at: '2026-06-12T00:40:00Z',
    },
  ]
  let integrationIncidents: any[] = [
    {
      id: 'webhook-delivery-failed-e2e',
      category: 'webhook',
      severity: 'critical',
      title: 'Webhook 投递失败',
      detail: '目标服务返回 HTTP 503',
      status: 'failed',
      attempts: 3,
      occurred_at: '2026-06-13T10:00:00Z',
      action_type: 'retry_webhook',
      action_href: '/integrations?retryWebhook=webhook-delivery-failed-e2e',
    },
    {
      id: 'outbox-failed-e2e',
      category: 'outbox',
      severity: 'critical',
      title: 'Outbox 事件失败',
      detail: '发布超过最大重试次数',
      status: 'failed',
      attempts: 3,
      occurred_at: '2026-06-13T09:00:00Z',
      action_type: 'retry_outbox',
      action_href: '/integrations?retryOutbox=outbox-failed-e2e',
    },
  ]

  await page.route(/\/api\/v1\/integrations(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const created = {
        id: `integration-e2e-${Date.now()}`,
        tenant_id: 'tenant-e2e-001',
        provider_type: payload.provider_type || 'custom',
        name: payload.name || '新集成',
        config_json: payload.config_json || {},
        is_enabled: payload.is_enabled ?? true,
        last_sync_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      integrations = [created, ...integrations]
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(created) })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: integrations, total: integrations.length, page: 1, page_size: 50, has_more: false }),
    })
  })

  await page.route('**/api/v1/integrations/integration-e2e-zentao/test', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'connected', message: '连接成功', details: { status_code: 200 } }),
    })
  })

  await page.route('**/api/v1/integrations/integration-e2e-zentao/sync', async (route) => {
    integrations = integrations.map((item) => item.id === 'integration-e2e-zentao' ? { ...item, last_sync_at: new Date().toISOString() } : item)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, status: 'completed', message: '同步完成', last_sync_at: new Date().toISOString() }),
    })
  })

  await page.route('**/api/v1/integrations/integration-e2e-zentao/project-bindings', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(integrationBindings.filter((item) => item.integration_provider_id === 'integration-e2e-zentao')),
    })
  })

  await page.route('**/api/v1/integrations/project-bindings/binding-e2e-001/preview*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        binding_id: 'binding-e2e-001',
        total: 2,
        cursor: { page: 2 },
        items: [
          {
            external_id: 'ZT-REQ-1001',
            title: '登录异常处理规则',
            content: '补充账号锁定、短信验证码失败和审计记录要求。',
            external_url: 'https://zentao.example.com/story/1001',
            external_updated_at: '2026-06-11T08:00:00Z',
            metadata: { type: 'story' },
          },
          {
            external_id: 'ZT-REQ-1002',
            title: '发货复核流程',
            content: '扫码复核后生成异常处理任务。',
            external_url: 'https://zentao.example.com/story/1002',
            external_updated_at: '2026-06-11T09:00:00Z',
            metadata: { type: 'story' },
          },
        ],
      }),
    })
  })

  await page.route('**/api/v1/integrations/project-bindings/binding-e2e-001/sync', async (route) => {
    integrationBindings = integrationBindings.map((item) => item.id === 'binding-e2e-001' ? {
      ...item,
      last_sync_status: 'completed',
      last_synced_at: new Date().toISOString(),
    } : item)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'sync-run-e2e-001',
        tenant_id: 'tenant-e2e-001',
        binding_id: 'binding-e2e-001',
        status: 'completed',
        mode: 'manual',
        cursor_before_json: { page: 1 },
        cursor_after_json: { page: 2 },
        total_count: 2,
        created_count: 1,
        updated_count: 1,
        unchanged_count: 0,
        failed_count: 0,
        error_message: null,
        details_json: {},
        requested_by: MOCK.MOCK_USER.id,
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
      }),
    })
  })

  await page.route('**/api/v1/integrations/integration-e2e-zentao/webhooks*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: 'webhook-e2e-001',
            tenant_id: 'tenant-e2e-001',
            integration_provider_id: 'integration-e2e-zentao',
            url: 'https://delivery.example.com/hooks/amx',
            events: ['delivery.ready', 'document.published'],
            is_active: true,
            secret: null,
            created_at: '2026-06-10T04:00:00Z',
            updated_at: '2026-06-10T04:00:00Z',
          },
        ],
        total: 1,
        page: 1,
        page_size: 30,
        has_more: false,
      }),
    })
  })

  await page.route('**/api/v1/integrations/outbox/events*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: outboxEvents, total: outboxEvents.length, page: 1, page_size: 20, has_more: false }),
    })
  })

  await page.route('**/api/v1/integrations/outbox/publish*', async (route) => {
    outboxEvents = outboxEvents.map((event) => ({ ...event, published: true, published_at: new Date().toISOString() }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ processed: 2, published: 2, failed: 0 }),
    })
  })

  await page.route('**/api/v1/integrations/operations/incidents*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total: integrationIncidents.length,
        critical_count: integrationIncidents.filter((item) => item.severity === 'critical').length,
        retryable_count: integrationIncidents.length,
        items: integrationIncidents,
      }),
    })
  })

  await page.route('**/api/v1/integrations/webhooks/deliveries/*/retry', async (route) => {
    const id = route.request().url().split('/').at(-2)
    integrationIncidents = integrationIncidents.filter((item) => item.id !== id)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id, delivered_at: new Date().toISOString() }) })
  })

  await page.route('**/api/v1/integrations/outbox/events/*/retry', async (route) => {
    const id = route.request().url().split('/').at(-2)
    integrationIncidents = integrationIncidents.filter((item) => item.id !== id)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id, status: 'pending', published: false }) })
  })

  await page.route('**/api/v1/integrations/operations/summary*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'degraded',
        score: 76,
        summary: '外部集成已配置，但仍存在 Webhook 投递失败和 Outbox 积压。',
        evidence: {
          integration_count: 2,
          enabled_integration_count: 2,
          configured_integration_count: 1,
          synced_integration_count: 1,
          webhook_count: 2,
          active_webhook_count: 1,
          successful_delivery_count: 4,
          failed_delivery_count: 1,
          pending_outbox_count: 1,
          failed_outbox_count: 0,
          project_binding_count: 2,
          completed_project_sync_count: 1,
          synced_asset_count: 5,
        },
        blockers: ['Webhook 投递失败 1 次，需要处理失败目标或重试。', 'Outbox 仍有 1 条待发布事件。'],
        recommended_actions: ['检查 Webhook 投递历史并重试失败事件。', '发布或排查 Outbox 积压事件。'],
      }),
    })
  })

  await page.route('**/api/v1/integrations/operations/command-center*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        release_gate: {
          status: 'blocked',
          label: '联调阻断',
          summary: '外部集成仍存在生产联调阻断，发布前必须完成处置。',
          blockers: ['Webhook 投递失败', 'Outbox 事件待发布'],
          warnings: [],
        },
        summary: {
          score: 76,
          integration_count: 2,
          enabled_integration_count: 2,
          configured_integration_count: 1,
          synced_integration_count: 1,
          active_webhook_count: 1,
          successful_delivery_count: 4,
          failed_delivery_count: 1,
          pending_outbox_count: 1,
          failed_outbox_count: 0,
          project_binding_count: 2,
          completed_project_sync_count: 1,
          synced_asset_count: 5,
          blocker_count: 2,
        },
        risk_items: [
          {
            code: 'failed_webhook_deliveries',
            severity: 'high',
            title: 'Webhook 投递失败',
            detail: '存在失败投递，需要重试或修复目标端后再进入发布。',
            count: 1,
            href: '/integrations',
          },
          {
            code: 'pending_outbox',
            severity: 'high',
            title: 'Outbox 事件待发布',
            detail: '仍有事件没有发布，外部系统可能没有收到最新业务状态。',
            count: 1,
            href: '/integrations',
          },
        ],
        priority_actions: [
          {
            code: 'clear_events',
            title: '清理 Webhook 与 Outbox 阻断',
            description: '重试失败投递，发布积压事件，并保留处理结果。',
            href: '/integrations',
            priority: 'high',
          },
        ],
        operations_summary: {
          status: 'degraded',
          score: 76,
          summary: '外部集成已配置，但仍存在 Webhook 投递失败和 Outbox 积压。',
          evidence: {
            integration_count: 2,
            enabled_integration_count: 2,
            configured_integration_count: 1,
            synced_integration_count: 1,
            webhook_count: 2,
            active_webhook_count: 1,
            successful_delivery_count: 4,
            failed_delivery_count: 1,
            pending_outbox_count: 1,
            failed_outbox_count: 0,
            project_binding_count: 2,
            completed_project_sync_count: 1,
            synced_asset_count: 5,
          },
          blockers: ['Webhook 投递失败 1 次，需要处理失败目标或重试。', 'Outbox 仍有 1 条待发布事件。'],
          recommended_actions: ['检查 Webhook 投递历史并重试失败事件。', '发布或排查 Outbox 积压事件。'],
        },
      }),
    })
  })

  // 租户列表
  await page.route('**/api/v1/identity/tenants*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [MOCK.MOCK_TENANT],
        total: 1,
      }),
    })
  })

  // 用户列表
  await page.route('**/api/v1/identity/users*', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'user-new-001',
          email: payload.email || 'newuser@163.com',
          full_name: payload.full_name || payload.name || '新用户',
          tenant_id: 'tenant-e2e-001',
          is_active: true,
          roles: [],
          created_at: new Date().toISOString(),
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              ...MOCK.MOCK_USER,
              full_name: MOCK.MOCK_USER.name || '系统管理员',
              tenant_id: MOCK.MOCK_TENANT.id,
              is_active: true,
              created_at: '2026-05-21T09:00:00Z',
              roles: [
                {
                  id: 'role-admin',
                  name: '管理员',
                  description: '系统全部操作权限',
                  permissions: { '*': '*' },
                  created_at: '2026-05-21T09:00:00Z',
                },
              ],
            },
            {
              id: 'user-reviewer-001',
              email: 'reviewer@example.com',
              full_name: '业务验收负责人',
              tenant_id: MOCK.MOCK_TENANT.id,
              is_active: true,
              created_at: '2026-05-22T09:00:00Z',
              roles: [
                {
                  id: 'role-member',
                  name: '普通成员',
                  description: '项目协作和文档评审权限',
                  permissions: { read: true, write: true },
                  created_at: '2026-05-21T09:00:00Z',
                },
              ],
            },
          ],
          total: 2,
        }),
      })
    }
  })

  const teamRoles = MOCK.MOCK_ROLES.map((role: any) => ({
    ...role,
    tenant_id: MOCK.MOCK_TENANT.id,
    name: role.id === 'role-admin' ? '管理员' : role.id === 'role-member' ? '普通成员' : role.name,
    description: role.id === 'role-admin' ? '系统全部操作权限' : '项目协作和文档评审权限',
    permissions: role.id === 'role-admin'
      ? { '*': '*' }
      : { projects: ['read'], documents: ['read', 'write', 'review'], agents: ['read'] },
    created_at: role.created_at || '2026-05-21T09:00:00Z',
    updated_at: role.updated_at || '2026-05-21T09:00:00Z',
  }))

  // 角色列表
  await page.route(/\/api\/v1\/identity\/roles(?:\/.*)?(?:\?.*)?$/, async (route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())

    if (method === 'POST' && /\/identity\/roles\/[^/]+\/assign$/.test(url.pathname)) {
      await route.fulfill({ status: 204 })
    } else if (method === 'DELETE' && /\/identity\/roles\/[^/]+\/assign\/[^/]+$/.test(url.pathname)) {
      await route.fulfill({ status: 204 })
    } else if (method === 'DELETE' && /\/identity\/roles\/[^/]+$/.test(url.pathname)) {
      await route.fulfill({ status: 204 })
    } else if (method === 'PATCH' && /\/identity\/roles\/[^/]+$/.test(url.pathname)) {
      const roleId = url.pathname.split('/').pop()
      const payload = JSON.parse(request.postData() || '{}')
      const existing = teamRoles.find((role: any) => role.id === roleId) || teamRoles[0]
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...existing,
          ...payload,
          updated_at: new Date().toISOString(),
        }),
      })
    } else if (method === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: `role-${Date.now()}`,
          tenant_id: MOCK.MOCK_TENANT.id,
          name: payload.name || '新角色',
          description: payload.description || '',
          permissions: payload.permissions || {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: teamRoles,
          total: teamRoles.length,
        }),
      })
    }
  })

  const teamPolicies = [
    {
      id: 'policy-tenant-scope',
      tenant_id: MOCK.MOCK_TENANT.id,
      name: '租户数据隔离策略',
      description: '仅允许访问当前租户下的项目、文档和编排记录。',
      effect: 'allow',
      actions: ['read', 'write', 'review'],
      resources: ['projects:*', 'documents:*', 'agents:*'],
      conditions: { tenant_id: '{{tenant_id}}' },
      created_at: '2026-05-25T09:00:00Z',
      updated_at: '2026-05-25T09:00:00Z',
    },
    {
      id: 'policy-export-deny',
      tenant_id: MOCK.MOCK_TENANT.id,
      name: '非批准文档禁止导出',
      description: '阻止未批准或占位内容进入正式交付包。',
      effect: 'deny',
      actions: ['export'],
      resources: ['documents:placeholder', 'documents:draft'],
      conditions: { status_not_in: ['approved', 'published'] },
      created_at: '2026-05-26T09:00:00Z',
      updated_at: '2026-05-26T09:00:00Z',
    },
  ]

  // ABAC 策略
  await page.route(/\/api\/v1\/identity\/policies(?:\/.*)?(?:\?.*)?$/, async (route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())

    if (method === 'DELETE' && /\/identity\/policies\/[^/]+$/.test(url.pathname)) {
      await route.fulfill({ status: 204 })
    } else if (method === 'PATCH' && /\/identity\/policies\/[^/]+$/.test(url.pathname)) {
      const policyId = url.pathname.split('/').pop()
      const payload = JSON.parse(request.postData() || '{}')
      const existing = teamPolicies.find((policy) => policy.id === policyId) || teamPolicies[0]
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...existing,
          ...payload,
          updated_at: new Date().toISOString(),
        }),
      })
    } else if (method === 'POST') {
      const payload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: `policy-${Date.now()}`,
          tenant_id: MOCK.MOCK_TENANT.id,
          name: payload.name || '新策略',
          description: payload.description || '',
          effect: payload.effect || 'allow',
          actions: payload.actions || ['read'],
          resources: payload.resources || ['projects:*'],
          conditions: payload.conditions || { tenant_id: '{{tenant_id}}' },
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: teamPolicies,
          total: teamPolicies.length,
          page: 1,
          page_size: 100,
          has_more: false,
        }),
      })
    }
  })

  // 字段级权限
  await page.route(/\/api\/v1\/identity\/field-permissions\/[^/]+\/[^/?]+(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'field-permission-001',
          tenant_id: MOCK.MOCK_TENANT.id,
          role_id: 'role-member',
          resource_type: 'document',
          field_name: 'commercial_terms',
          permission: 'read',
          created_at: '2026-05-26T09:00:00Z',
          updated_at: '2026-05-26T09:00:00Z',
        },
      ]),
    })
  })

  await page.route('**/api/v1/identity/field-permissions', async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        id: `field-permission-${Date.now()}`,
        tenant_id: MOCK.MOCK_TENANT.id,
        ...payload,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }),
    })
  })

  await page.route('**/api/v1/identity/permission-diagnostics*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-06-04T13:30:00Z',
        tenant_id: MOCK.MOCK_TENANT.id,
        user_id: MOCK.MOCK_USER.id,
        summary: { total: 6, allowed: 4, denied: 2, field_restricted: 1 },
        checks: [
          { key: 'projects.read', label: '项目资料读取', resource: 'projects', action: 'read', allowed: true, reason: 'rbac' },
          { key: 'documents.review', label: '文档评审', resource: 'documents', action: 'review', allowed: true, reason: 'rbac' },
          { key: 'documents.export', label: '导出交付包', resource: 'documents', action: 'export', allowed: false, reason: 'deny_policy' },
          { key: 'agents.manage', label: '智能编排管理', resource: 'agents', action: 'manage', allowed: true, reason: 'rbac' },
          { key: 'team.read', label: '团队权限读取', resource: 'team', action: 'read', allowed: true, reason: 'rbac' },
          { key: 'team.manage', label: '团队权限管理', resource: 'team', action: 'manage', allowed: false, reason: 'no_grant' },
        ],
        field_controls: [
          { role_id: 'role-member', role_name: '普通成员', resource_type: 'document', field_name: 'commercial_terms', permission: 'none' },
        ],
        policy_evidence: teamPolicies.map((policy) => ({
          id: policy.id,
          name: policy.name,
          effect: policy.effect,
          actions: policy.actions,
          resources: policy.resources,
        })),
      }),
    })
  })

  await page.route('**/api/v1/identity/permission-command-center*', async (route) => {
    const denyPolicies = teamPolicies.filter((policy) => policy.effect === 'deny')
    const highPrivilegeRoles = teamRoles.filter((role: any) => role.id === 'role-admin')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-06-04T13:35:00Z',
        tenant_id: MOCK.MOCK_TENANT.id,
        release_gate: {
          status: 'blocked',
          label: '权限阻断',
          summary: '团队权限仍存在关键权限拒绝项，不能作为生产验收证据。',
          blockers: ['权限自检存在拒绝项'],
          warnings: ['存在拒绝策略', '字段级权限限制生效', '高权限角色需要复核'],
        },
        summary: {
          total_users: 2,
          active_users: 2,
          users_without_roles: 0,
          role_count: teamRoles.length,
          high_privilege_roles: highPrivilegeRoles.length,
          policy_count: teamPolicies.length,
          deny_policy_count: denyPolicies.length,
          field_permission_count: 5,
          field_restricted_count: 1,
          audit_log_count: 8,
          diagnostic_allowed: 4,
          diagnostic_denied: 2,
        },
        risk_items: [
          {
            code: 'permission_denials',
            severity: 'high',
            title: '权限自检存在拒绝项',
            detail: '当前账号的关键团队或导出操作仍被拒绝，需要发布前复核。',
            count: 2,
            href: '/team',
          },
          {
            code: 'deny_policies',
            severity: 'medium',
            title: '存在拒绝策略',
            detail: 'deny 策略会覆盖角色授权，需要确认命中范围。',
            count: denyPolicies.length,
            href: '/team',
          },
          {
            code: 'field_restrictions',
            severity: 'medium',
            title: '字段级权限限制生效',
            detail: '字段 none 权限会影响文档、导出和智能编排可见性。',
            count: 1,
            href: '/team',
          },
        ],
        priority_actions: [
          {
            code: 'review_denials',
            title: '复核权限自检拒绝项',
            description: '检查项目、文档、编排、团队权限的拒绝原因。',
            href: '/team',
            priority: 'high',
          },
          {
            code: 'review_policy_and_fields',
            title: '复核策略与字段权限',
            description: '确认 deny 策略、字段 none 权限不会阻断交付。',
            href: '/team',
            priority: 'medium',
          },
        ],
        diagnostic_snapshot: { total: 6, allowed: 4, denied: 2, field_restricted: 1 },
        recent_audit_actions: ['team.role_assigned', 'permission.simulate'],
      }),
    })
  })

  await page.route(/\/api\/v1\/identity\/api-keys(?:\/[^/?]+)?(?:\?.*)?$/, async (route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())

    if (method === 'POST' && /\/identity\/api-keys$/.test(url.pathname)) {
      const payload = JSON.parse(request.postData() || '{}')
      const id = `api-key-e2e-${Date.now()}`
      const created = {
        id,
        tenant_id: 'tenant-e2e-001',
        name: payload.name || '未命名密钥',
        key_prefix: 'amx_live_new',
        permissions: payload.permissions || ['read'],
        status: 'active',
        created_by_id: MOCK.MOCK_USER.id,
        revoked_by_id: null,
        last_used_at: null,
        expires_at: payload.expires_at || null,
        revoked_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      tenantApiKeys = [created, ...tenantApiKeys]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          ...created,
          api_key: `amx_live_new_${id}_secret_once`,
        }),
      })
    } else if (method === 'DELETE') {
      const keyId = url.pathname.split('/').pop()
      tenantApiKeys = tenantApiKeys.map((key) =>
        key.id === keyId
          ? {
              ...key,
              status: 'revoked',
              revoked_by_id: MOCK.MOCK_USER.id,
              revoked_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            }
          : key
      )
      await route.fulfill({ status: 204 })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: tenantApiKeys,
          total: tenantApiKeys.length,
          page: 1,
          page_size: 100,
          has_more: false,
        }),
      })
    }
  })

  await page.route('**/api/v1/identity/permission-simulations', async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-06-06T10:00:00Z',
        tenant_id: MOCK.MOCK_TENANT.id,
        requested_by_user_id: MOCK.MOCK_USER.id,
        target_user_id: payload.user_id || 'user-reviewer-001',
        target_user_email: 'reviewer@example.com',
        target_user_name: '业务验收负责人',
        resource: payload.resource || 'documents',
        action: payload.action || 'export',
        allowed: false,
        reason: 'deny_policy',
        roles: [
          {
            id: 'role-member',
            name: '普通成员',
            description: '项目协作和文档评审权限',
            permissions: { projects: ['read'], documents: ['read', 'write', 'review'], agents: ['read'] },
          },
        ],
        field_controls: [
          { role_id: 'role-member', role_name: '普通成员', resource_type: 'document', field_name: 'commercial_terms', permission: 'none' },
        ],
        policy_evidence: [
          { id: 'policy-export-deny', name: '非批准文档禁止导出', effect: 'deny', actions: ['export'], resources: ['documents'] },
        ],
      }),
    })
  })

  // 审计日志
  await page.route('**/api/v1/identity/audit-logs*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: 'audit-role-001',
            tenant_id: MOCK.MOCK_TENANT.id,
            user_id: MOCK.MOCK_USER.id,
            action: 'role.assign',
            resource_type: 'role',
            resource_id: 'role-admin',
            extra_data: { role: '管理员', user_name: '系统管理员', summary: '为系统管理员分配管理员角色' },
            ip_address: '127.0.0.1',
            user_agent: 'Playwright',
            created_at: '2026-05-26T09:00:00Z',
          },
          {
            id: 'audit-document-001',
            tenant_id: MOCK.MOCK_TENANT.id,
            user_id: MOCK.MOCK_USER.id,
            action: 'document.delete',
            resource_type: 'document',
            resource_id: 'doc-e2e-006',
            extra_data: { user_name: '系统管理员', summary: '删除占位验收报告草稿' },
            ip_address: '127.0.0.1',
            user_agent: 'Playwright',
            created_at: '2026-05-26T08:30:00Z',
          },
          {
            id: 'audit-export-001',
            tenant_id: MOCK.MOCK_TENANT.id,
            user_id: MOCK.MOCK_USER.id,
            action: 'export.execute',
            resource_type: 'export',
            resource_id: 'export-e2e-001',
            extra_data: { user_name: '系统管理员', summary: '生成项目交付包并保留导出证据' },
            ip_address: '127.0.0.1',
            user_agent: 'Playwright',
            created_at: '2026-05-26T08:00:00Z',
          },
          {
            id: 'audit-workflow-001',
            tenant_id: MOCK.MOCK_TENANT.id,
            user_id: 'user-reviewer-001',
            action: 'workflow.approve',
            resource_type: 'workflow',
            resource_id: 'workflow-e2e-001',
            extra_data: { user_name: '业务验收负责人', summary: '审批文档生成工作流发布' },
            ip_address: '127.0.0.1',
            user_agent: 'Playwright',
            created_at: '2026-05-25T10:00:00Z',
          },
          {
            id: 'audit-user-001',
            tenant_id: MOCK.MOCK_TENANT.id,
            user_id: MOCK.MOCK_USER.id,
            action: 'user.create',
            resource_type: 'user',
            resource_id: 'user-reviewer-001',
            extra_data: { email: 'reviewer@example.com', user_name: '系统管理员', summary: '创建业务验收负责人账号' },
            ip_address: '127.0.0.1',
            user_agent: 'Playwright',
            created_at: '2026-05-25T09:00:00Z',
          },
        ],
        total: 5,
        page: 1,
        page_size: 12,
        has_more: false,
      }),
    })
  })

  // 角色分配
  await page.route(/\/api\/v1\/identity\/roles\/[^/]+\/assign$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    })
  })


  // ==================== 2. PROJECTS ====================

  // 项目列表与创建
  await page.route(/\/api\/v1\/projects(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK.MOCK_PROJECT,
          name: payload.name || MOCK.MOCK_PROJECT.name,
          description: payload.description || MOCK.MOCK_PROJECT.description,
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [MOCK.MOCK_PROJECT],
          total: 1,
          page: 1,
          page_size: 10,
          has_more: false,
        }),
      })
    }
  })

  await page.route('**/api/v1/projects/launch-blueprints', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(projectLaunchBlueprints),
    })
  })

  await page.route('**/api/v1/projects/launch', async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const project = {
      ...MOCK.MOCK_PROJECT,
      id: 'project-launched-001',
      name: payload.name || '新启动项目',
      description: payload.description || '',
    }
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        project,
        plan: {
          ...projectLaunchPlan,
          project_id: project.id,
          blueprint_key: payload.blueprint_key,
          config_json: {
            ...projectLaunchPlan.config_json,
            document_types: payload.document_types,
            workflow_template_ids: payload.workflow_template_ids,
          },
        },
      }),
    })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/launch-plan(?:\/retry)?$/, async (route) => {
    if (route.request().url().endsWith('/retry')) {
      projectLaunchPlan = {
        ...projectLaunchPlan,
        attempt_count: projectLaunchPlan.attempt_count + 1,
        updated_at: new Date().toISOString(),
      }
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ project: MOCK.MOCK_PROJECT, plan: projectLaunchPlan }),
    })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/delivery-plan(?:\/initialize)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(projectDeliveryPlan),
    })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/acceptance$/, async (route) => {
    if (route.request().method() === 'PUT') {
      const payload = JSON.parse(route.request().postData() || '{}')
      projectAcceptance = {
        ...projectAcceptance,
        ...payload,
        updated_by: MOCK.MOCK_USER.id,
        accepted_at: new Date().toISOString(),
        gate: { status: 'passed', label: '可正式关闭', blockers: [], warnings: [] },
      }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(projectAcceptance) })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/acceptance\/close$/, async (route) => {
    projectAcceptance = { ...projectAcceptance, closed_at: new Date().toISOString() }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(projectAcceptance) })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/acceptance\/reopen$/, async (route) => {
    projectAcceptance = { ...projectAcceptance, closed_at: null }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(projectAcceptance) })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/milestones\/reorder$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const byId = new Map(projectDeliveryPlan.milestones.map((item: any) => [item.id, item]))
    projectDeliveryPlan.milestones = (payload.milestone_ids || []).map((id: string, index: number) => ({ ...byId.get(id), order_index: index }))
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(projectDeliveryPlan) })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/milestones$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const milestone = {
      id: `milestone-${Date.now()}`,
      tenant_id: 'tenant-e2e-001',
      project_id: MOCK.MOCK_PROJECT.id,
      plan_id: projectDeliveryPlan.id,
      owner_id: payload.owner_id || MOCK.MOCK_USER.id,
      key: payload.key,
      title: payload.title,
      description: payload.description || '',
      status: 'planned',
      priority: payload.priority || 'medium',
      order_index: projectDeliveryPlan.milestones.length,
      planned_start_at: null,
      due_at: payload.due_at || null,
      completed_at: null,
      required_document_types_json: payload.required_document_types || [],
      required_workflow_template_ids_json: payload.required_workflow_template_ids || [],
      gate_results_json: [],
      metadata_json: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    projectDeliveryPlan.milestones.push(milestone)
    projectDeliveryPlan.summary.total_count += 1
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(milestone) })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/milestones\/([^/]+)\/(start|complete|reopen)$/, async (route) => {
    const match = route.request().url().match(/milestones\/([^/]+)\/(start|complete|reopen)$/)
    const milestone = projectDeliveryPlan.milestones.find((item: any) => item.id === match?.[1])
    if (milestone) {
      milestone.status = match?.[2] === 'start' ? 'in_progress' : match?.[2] === 'complete' ? 'completed' : 'planned'
      milestone.completed_at = milestone.status === 'completed' ? new Date().toISOString() : null
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(milestone) })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/milestones\/([^/]+)$/, async (route) => {
    const milestoneId = route.request().url().match(/milestones\/([^/]+)$/)?.[1]
    const index = projectDeliveryPlan.milestones.findIndex((item: any) => item.id === milestoneId)
    if (route.request().method() === 'DELETE') {
      projectDeliveryPlan.milestones.splice(index, 1)
      projectDeliveryPlan.milestones.forEach((item: any, orderIndex: number) => { item.order_index = orderIndex })
      projectDeliveryPlan.summary.total_count = projectDeliveryPlan.milestones.length
      await route.fulfill({ status: 204 })
      return
    }
    const payload = JSON.parse(route.request().postData() || '{}')
    const milestone = Object.assign(projectDeliveryPlan.milestones[index], {
      ...payload,
      required_document_types_json: payload.required_document_types,
      required_workflow_template_ids_json: payload.required_workflow_template_ids,
      status: projectDeliveryPlan.milestones[index].status === 'blocked' ? 'planned' : projectDeliveryPlan.milestones[index].status,
    })
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(milestone) })
  })

  await page.route('**/api/v1/projects/delivery-portfolio', async (route) => {
    const milestones = projectDeliveryPlan.milestones.map((milestone: any) => ({
      milestone_id: milestone.id,
      project_id: milestone.project_id,
      project_name: MOCK.MOCK_PROJECT.name,
      title: milestone.title,
      status: milestone.status,
      priority: milestone.priority,
      owner_id: milestone.owner_id,
      owner_name: milestone.owner_id ? '项目负责人' : '未分配',
      due_at: milestone.due_at,
      is_overdue: milestone.id === 'milestone-review-traceability',
      gate_blocker_count: milestone.gate_results_json.filter((gate: any) => gate.status === 'blocked').length,
      action_href: `/projects/${milestone.project_id}/plan`,
    }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: new Date().toISOString(),
        project_count: 1,
        portfolio: {
          totals: { total: milestones.length, active: milestones.filter((item: any) => item.status !== 'completed').length, completed: milestones.filter((item: any) => item.status === 'completed').length, blocked: milestones.filter((item: any) => item.status === 'blocked').length, overdue: 1, unassigned: 0 },
          status_counts: { planned: 2, blocked: 1, completed: 1 },
          upcoming: milestones,
          blocked: milestones.filter((item: any) => item.status === 'blocked' || item.gate_blocker_count > 0),
          owner_load: [{ owner_id: MOCK.MOCK_USER.id, owner_name: '项目负责人', active_count: 3, blocked_count: 1, overdue_count: 1, project_count: 1, action_href: '/collaboration' }],
        },
      }),
    })
  })

  // 系统级交付总控台
  await page.route('**/api/v1/projects/delivery-overview*', async (route) => {
    const workbench = MOCK.MOCK_PROJECT_DELIVERY_WORKBENCH
    const reviewQueueCount = 1
    const openChangeCount = 1
    const isExportReady = false
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-05-21T10:00:00Z',
        readiness_score: 54,
        totals: {
          projects: 1,
          documents: workbench.totals.documents,
          source_files: workbench.totals.source_files,
          knowledge_entries: workbench.totals.knowledge_entries,
          open_changes: openChangeCount,
          review_queue: reviewQueueCount,
          export_ready_projects: 0,
          blocked_projects: 1,
        },
        module_health: [
          {
            key: 'sources',
            label: '项目资料',
            status: 'attention',
            score: 60,
            summary: `${workbench.totals.source_files} 份资料已进入项目。`,
            action_href: '/projects',
          },
          {
            key: 'knowledge',
            label: '知识图谱',
            status: 'healthy',
            score: 90,
            summary: `${workbench.totals.knowledge_entries} 条知识可用于生成和追溯。`,
            action_href: '/knowledge/graph',
          },
          {
            key: 'documents',
            label: '项目文档',
            status: 'healthy',
            score: 85,
            summary: `${workbench.totals.documents} 份文档处于交付链路中。`,
            action_href: '/documents',
          },
          {
            key: 'review',
            label: '评审协同',
            status: 'attention',
            score: 80,
            summary: `${reviewQueueCount} 份文档仍在评审队列。`,
            action_href: '/collaboration',
          },
          {
            key: 'changes',
            label: '变更追溯',
            status: 'attention',
            score: 82,
            summary: `${openChangeCount} 个变更仍需处理。`,
            action_href: '/projects',
          },
          {
            key: 'export',
            label: '导出交付',
            status: 'blocked',
            score: 0,
            summary: '0 个项目达到导出条件。',
            action_href: '/exports',
          },
        ],
        projects: [
          {
            project_id: MOCK.MOCK_PROJECT.id,
            name: MOCK.MOCK_PROJECT.name,
            status: MOCK.MOCK_PROJECT.status,
            updated_at: MOCK.MOCK_PROJECT.updated_at,
            readiness_score: 38,
            readiness_label: '推进中',
            blocker_count: workbench.readiness.blockers.length + workbench.risks.length,
            document_count: workbench.totals.documents,
            source_file_count: workbench.totals.source_files,
            knowledge_entry_count: workbench.totals.knowledge_entries,
            open_change_count: openChangeCount,
            review_queue_count: reviewQueueCount,
            export_ready: isExportReady,
            delivery_phase_key: 'review',
            delivery_phase_label: '评审追溯',
            release_gate_status: 'blocked',
            next_action_label: workbench.next_actions[1].label,
            next_action_href: workbench.next_actions[1].href,
            next_action_priority: workbench.next_actions[1].priority,
          },
        ],
        phase_summary: [
          {
            key: 'intake',
            label: '资料导入',
            status: 'empty',
            project_count: 0,
            blocked_project_count: 0,
            ready_project_count: 0,
            score: 0,
            summary: '0 个项目处于资料导入阶段，0 个存在阻塞。',
            action_href: '/projects',
          },
          {
            key: 'authoring',
            label: '文档编写',
            status: 'empty',
            project_count: 0,
            blocked_project_count: 0,
            ready_project_count: 0,
            score: 0,
            summary: '0 个项目处于文档编写阶段，0 个存在阻塞。',
            action_href: '/documents',
          },
          {
            key: 'review',
            label: '评审追溯',
            status: 'blocked',
            project_count: 1,
            blocked_project_count: 1,
            ready_project_count: 0,
            score: 75,
            summary: '1 个项目处于评审追溯阶段，1 个存在阻塞。',
            action_href: '/collaboration',
          },
          {
            key: 'release',
            label: '导出发布',
            status: 'empty',
            project_count: 0,
            blocked_project_count: 0,
            ready_project_count: 0,
            score: 0,
            summary: '0 个项目处于导出发布阶段，0 个存在阻塞。',
            action_href: '/exports',
          },
        ],
        release_gates: [
          {
            key: 'sources_ready',
            label: '项目资料就绪',
            status: 'passed',
            passed_count: 1,
            total_count: 1,
            score: 100,
            blockers: [],
            action_href: '/projects',
          },
          {
            key: 'documents_complete',
            label: '核心文档完整',
            status: 'passed',
            passed_count: 1,
            total_count: 1,
            score: 100,
            blockers: [],
            action_href: '/documents',
          },
          {
            key: 'traceability_clear',
            label: '追溯变更清理',
            status: 'blocked',
            passed_count: 0,
            total_count: 1,
            score: 0,
            blockers: [`${MOCK.MOCK_PROJECT.name}: 仍有变更或追溯同步待处理`],
            action_href: '/projects',
          },
          {
            key: 'review_clear',
            label: '评审协同完成',
            status: 'blocked',
            passed_count: 0,
            total_count: 1,
            score: 0,
            blockers: [`${MOCK.MOCK_PROJECT.name}: 仍有文档评审队列`],
            action_href: '/collaboration',
          },
          {
            key: 'export_ready',
            label: '交付包可导出',
            status: 'blocked',
            passed_count: 0,
            total_count: 1,
            score: 0,
            blockers: [`${MOCK.MOCK_PROJECT.name}: 交付包尚不可导出`],
            action_href: '/exports',
          },
        ],
        operating_plan: [
          {
            project_id: MOCK.MOCK_PROJECT.id,
            project_name: MOCK.MOCK_PROJECT.name,
            phase_key: 'review',
            phase_label: '评审追溯',
            action_code: workbench.next_actions[1].code,
            action_label: workbench.next_actions[1].label,
            action_description: workbench.next_actions[1].description,
            action_href: workbench.next_actions[1].href,
            priority: workbench.next_actions[1].priority,
            status: 'blocked',
          },
        ],
        milestone_portfolio: {
          totals: { total: 4, active: 3, completed: 1, blocked: 1, overdue: 1, unassigned: 0 },
          status_counts: { planned: 1, in_progress: 1, blocked: 1, completed: 1 },
          upcoming: [
            {
              milestone_id: 'milestone-review-traceability',
              project_id: MOCK.MOCK_PROJECT.id,
              project_name: MOCK.MOCK_PROJECT.name,
              title: '评审与追溯',
              status: 'blocked',
              priority: 'high',
              owner_id: MOCK.MOCK_USER.id,
              owner_name: '项目负责人',
              due_at: '2026-06-10T09:00:00Z',
              is_overdue: true,
              gate_blocker_count: 2,
              action_href: `/projects/${MOCK.MOCK_PROJECT.id}/plan`,
            },
            {
              milestone_id: 'milestone-release-delivery',
              project_id: MOCK.MOCK_PROJECT.id,
              project_name: MOCK.MOCK_PROJECT.name,
              title: '交付发布',
              status: 'planned',
              priority: 'critical',
              owner_id: MOCK.MOCK_USER.id,
              owner_name: '项目负责人',
              due_at: '2026-06-20T09:00:00Z',
              is_overdue: false,
              gate_blocker_count: 1,
              action_href: `/projects/${MOCK.MOCK_PROJECT.id}/plan`,
            },
          ],
          blocked: [],
          owner_load: [
            {
              owner_id: MOCK.MOCK_USER.id,
              owner_name: '项目负责人',
              active_count: 3,
              blocked_count: 1,
              overdue_count: 1,
              project_count: 1,
              action_href: '/collaboration',
            },
          ],
        },
        completion_score: 76,
        production_gate: {
          status: 'blocked',
          score: 76,
          production_ready: false,
          ready_count: 8,
          attention_count: 2,
          blocking_count: 1,
          total_count: 11,
          checks: [
            {
              capability_key: 'notification_alert_handling',
              label: '通知确认与告警处置',
              status: 'blocked',
              score: 55,
              detail: '1 条升级通知尚未确认；1 条通知投递失败。',
              action_label: '处理通知与告警',
              action_href: '/notifications',
            },
            {
              capability_key: 'external_integration_sync',
              label: '外部集成同步闭环',
              status: 'attention',
              score: 70,
              detail: '外部同步尚未落地为项目资料和知识资产。',
              action_label: '管理外部集成',
              action_href: '/settings?tab=integrations',
            },
          ],
        },
        completion_capabilities: [
          {
            key: 'project_documents',
            label: '项目文档闭环',
            status: 'attention',
            score: 72,
            summary: '3 份文档，1 个项目存在阻塞。',
            evidence: { projects: 1, documents: 3, blocked_projects: 1 },
            blockers: ['1 个项目仍有交付阻塞。'],
            action_label: '进入项目文档',
            action_href: '/projects',
          },
          {
            key: 'source_knowledge',
            label: '资料与知识图谱',
            status: 'ready',
            score: 90,
            summary: '4 份资料，12 条知识。',
            evidence: { source_files: 4, knowledge_entries: 12 },
            blockers: [],
            action_label: '查看知识图谱',
            action_href: '/knowledge/graph',
          },
          {
            key: 'intelligent_orchestration',
            label: '智能编排',
            status: 'ready',
            score: 88,
            summary: '3 个活跃 Agent，6 个已发布 Skill，2 条工作流。',
            evidence: { active_agents: 3, published_skills: 6, active_workflows: 2 },
            blockers: [],
            action_label: '打开智能编排',
            action_href: '/agents',
          },
          {
            key: 'template_governance',
            label: '模板与章节治理',
            status: 'ready',
            score: 86,
            summary: '5 个模板，24 个章节定义。',
            evidence: { active_templates: 5, template_versions: 5, template_sections: 24 },
            blockers: [],
            action_label: '管理模板',
            action_href: '/templates',
          },
          {
            key: 'traceability_change',
            label: '追溯与变更',
            status: 'attention',
            score: 70,
            summary: '1 个开放变更，1 个评审队列项。',
            evidence: { open_changes: 1, review_queue: 1 },
            blockers: ['1 个变更仍需处理。', '1 个评审项仍未关闭。'],
            action_label: '处理追溯变更',
            action_href: '/documents/contradictions',
          },
          {
            key: 'export_release',
            label: '导出发布',
            status: 'blocked',
            score: 35,
            summary: '0 个项目可导出，0 个完成导出任务。',
            evidence: { export_ready_projects: 0, completed_exports: 0 },
            blockers: ['尚无项目交付包达到可导出状态。'],
            action_label: '进入导出中心',
            action_href: '/exports',
          },
          {
            key: 'provider_operations',
            label: '供应商与模型运维',
            status: 'ready',
            score: 90,
            summary: '3 个供应商，2 个活跃供应商。',
            evidence: { providers: 3, live_providers: 2 },
            blockers: [],
            action_label: '检查供应商',
            action_href: '/providers',
          },
          {
            key: 'team_permissions',
            label: '团队与权限',
            status: 'ready',
            score: 95,
            summary: '4 个活跃用户，3 个角色，8 条审计记录。',
            evidence: { users: 4, roles: 3, audit_logs: 8 },
            blockers: [],
            action_label: '管理团队权限',
            action_href: '/team',
          },
          {
            key: 'system_operations',
            label: '运维监控与审计',
            status: 'attention',
            score: 68,
            summary: '12 条指标，3 条配额，0 条告警规则。',
            evidence: { metric_events: 12, quota_usages: 3, active_alert_rules: 0 },
            blockers: ['尚未配置可用告警规则。'],
            action_label: '查看运维监控',
            action_href: '/system-health',
          },
          {
            key: 'external_integration_sync',
            label: '外部集成同步闭环',
            status: 'attention',
            score: 70,
            summary: '2 个已启用集成，2 个项目绑定，0 个已同步资产。',
            evidence: { enabled_integrations: 2, integration_bindings: 2, completed_sync_runs: 1, synced_assets: 0 },
            blockers: ['外部同步尚未落地为项目资料和知识资产。'],
            action_label: '管理外部集成',
            action_href: '/settings?tab=integrations',
          },
          {
            key: 'collaboration_execution',
            label: '协同责任与评审处置',
            status: 'ready',
            score: 100,
            summary: '2 个开放协同事项，0 个阻塞，0 个逾期。',
            evidence: { collaboration_work_items: 9, completed_work_items: 7, open_work_items: 2, blocked_work_items: 0, overdue_work_items: 0 },
            blockers: [],
            action_label: '处理协同事项',
            action_href: '/collaboration',
          },
          {
            key: 'notification_alert_handling',
            label: '通知确认与告警处置',
            status: 'blocked',
            score: 55,
            summary: '1 条待确认，1 条已升级，1 条投递失败。',
            evidence: { notification_preferences: 4, unacknowledged_notifications: 1, escalated_notifications: 1, notification_deliveries: 8, sent_notification_deliveries: 7, failed_notification_deliveries: 1 },
            blockers: ['1 条升级通知尚未确认。', '1 条通知投递失败。'],
            action_label: '处理通知与告警',
            action_href: '/notifications',
          },
        ],
        completion_gaps: [
          {
            key: 'export_release_gap',
            capability_key: 'export_release',
            severity: 'critical',
            title: '导出发布未闭环',
            detail: '尚无项目交付包达到可导出状态。',
            action_label: '进入导出中心',
            action_href: '/exports',
          },
          {
            key: 'system_operations_gap',
            capability_key: 'system_operations',
            severity: 'high',
            title: '运维监控与审计未闭环',
            detail: '尚未配置可用告警规则。',
            action_label: '查看运维监控',
            action_href: '/system-health',
          },
        ],
        critical_actions: workbench.next_actions.slice(0, 3).map((action: any) => ({
          project_id: MOCK.MOCK_PROJECT.id,
          project_name: MOCK.MOCK_PROJECT.name,
          code: action.code,
          label: action.label,
          description: action.description,
          href: action.href,
          priority: action.priority,
        })),
      }),
    })
  })

  // 特定项目详情与更新/删除
  await page.route(/\/api\/v1\/projects\/[^/]+\/document-lifecycle-policy(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'PUT') {
      const payload = JSON.parse(route.request().postData() || '{}')
      projectLifecyclePolicy = {
        ...payload,
        revision: projectLifecyclePolicy.revision + 1,
      }
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(projectLifecyclePolicy),
    })
  })

  // 特定项目详情与更新/删除
  await page.route(/\/api\/v1\/projects\/(?!(?:delivery-overview|delivery-portfolio|launch|launch-blueprints)(?:\?|$))[^/?]+(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    if (method === 'PATCH') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK.MOCK_PROJECT,
          ...payload,
        }),
      })
    } else if (method === 'DELETE') {
      documents = documents.filter((document) => document.id !== docId)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK.MOCK_PROJECT),
      })
    }
  })

  // 项目成员与邀请
  await page.route(/\/api\/v1\/projects\/[^/]+\/(?:delivery-workbench|document-workbench)(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_PROJECT_DELIVERY_WORKBENCH),
    })
  })

  // 项目成员与邀请
  await page.route(/\/api\/v1\/projects\/[^/]+\/members(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: MOCK.MOCK_PROJECT_MEMBERS,
        total: 1,
        page: 1,
        page_size: 10,
        has_more: false,
      }),
    })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/members\/[^/?]+(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/invitations(?:\?email=.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'invitation-created-e2e',
          token: 'mock-invite-token-998877',
          invite_path: '/invitations/mock-invite-token-998877',
          expires_at: new Date(Date.now() + 86400000).toISOString(),
        }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: projectInvitations, total: projectInvitations.length, page: 1, page_size: 100, has_more: false }),
    })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/invitations\/[^/]+\/resend$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'invitation-e2e-001',
        token: 'mock-renewed-invite-token',
        invite_path: '/invitations/mock-renewed-invite-token',
        expires_at: new Date(Date.now() + 604800000).toISOString(),
      }),
    })
  })

  await page.route(/\/api\/v1\/projects\/[^/]+\/invitations\/[^/]+\/revoke$/, async (route) => {
    projectInvitations = projectInvitations.map((item) => ({ ...item, status: 'revoked', revoked_at: new Date().toISOString() }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(projectInvitations[0]),
    })
  })

  // 项目文件 / 源文件 接口 (包含列表与上传)
  await page.route(/\/api\/v1\/projects\/[^/]+\/files(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const createdAt = new Date().toISOString()
      const createdFile = {
        id: `file-uploaded-${Date.now()}`,
        projectId: 'project-e2e-001',
        project_id: 'project-e2e-001',
        name: 'new-source.txt',
        original_filename: 'new-source.txt',
        filename: 'new-source.txt',
        content_type: 'text/plain',
        size: 200,
        status: 'processing',
        ingestion_stage: '已进入解析队列',
        ingestion_summary: '资料已上传，等待解析服务抽取知识条目。',
        extracted_knowledge_count: 0,
        required_action: '等待解析完成',
        created_at: createdAt,
        updated_at: createdAt,
      }
      sourceFiles = [createdFile, ...sourceFiles]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(createdFile),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: sourceFiles,
          total: sourceFiles.length,
        }),
      })
    }
  })


  // ==================== 3. DOCUMENTS ====================

  // 文档列表与创建
  await page.route(/\/api\/v1\/documents(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          ...documents[0],
          name: payload.name || documents[0].name,
          type: payload.type || documents[0].type,
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: documents,
          total: documents.length,
          page: 1,
          page_size: 10,
          has_more: false,
        }),
      })
    }
  })

  // 特定文档详情与更新/删除
  await page.route(/\/api\/v1\/documents\/(?!generate(?:\?.*)?$|generation-sessions(?:\/|\?|$)|statistics\/summary(?:\?.*)?$)[^/?]+(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    const url = route.request().url()
    const docId = url.split('/').pop() || 'doc-e2e-001'
    const templateDoc = findDocument(docId)

    if (method === 'PATCH') {
      const payload = JSON.parse(route.request().postData() || '{}')
      documents = documents.map((document) =>
        document.id === docId
          ? {
              ...document,
              ...payload,
              name: payload.name ?? payload.title ?? document.name,
              title: payload.title ?? payload.name ?? document.title,
              updatedAt: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            }
          : document
      )
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(findDocument(docId)),
      })
    } else if (method === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(templateDoc),
      })
    }
  })

  await page.route(/\/api\/v1\/documents\/[^/]+\/status$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const docId = route.request().url().split('/').slice(-2)[0] || 'doc-e2e-001'
    const updatedAt = new Date().toISOString()
    const document = findDocument(docId)
    const unresolvedCommentCount = comments.filter((comment) =>
      (comment.documentId === docId || comment.document_id === docId) && !comment.resolved
    ).length

    if (payload.status === 'published' && document.status !== 'approved' && document.status !== 'published') {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Document must be approved before it can be published' }),
      })
      return
    }

    if (payload.status === 'published' && unresolvedCommentCount > 0) {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Document has unresolved comments and cannot be published' }),
      })
      return
    }

    documents = documents.map((document) =>
      document.id === docId
        ? {
            ...document,
            status: payload.status ?? document.status,
            metadata: { ...(document.metadata || {}), status: payload.status ?? document.status },
            metadata_json: { ...(document.metadata_json || {}), status: payload.status ?? document.status },
            updatedAt,
            updated_at: updatedAt,
          }
        : document
    )
    if (payload.status && payload.status !== document.status) {
      statusHistory = [
        ...statusHistory,
        {
          from_status: document.status,
          to_status: payload.status,
          action: payload.action || `document_${payload.status}`,
          reason: payload.reason || null,
          changed_by: 'user-admin-001',
          changed_at: updatedAt,
          unresolved_comment_count: unresolvedCommentCount,
        },
      ]
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(findDocument(docId)),
    })
  })

  await page.route(/\/api\/v1\/documents\/[^/]+\/status-history$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(statusHistory),
    })
  })

  await page.route(/\/api\/v1\/documents\/[^/]+\/status-capabilities$/, async (route) => {
    const docId = route.request().url().split('/').slice(-2)[0] || 'doc-e2e-001'
    const document = findDocument(docId)
    const unresolvedCommentCount = comments.filter((comment) =>
      (comment.documentId === docId || comment.document_id === docId) && !comment.resolved
    ).length
    const defaultCapabilities = [
      {
        status: 'draft',
        label: '草稿',
        permission_action: 'documents.write',
        allowed: ['review', 'approved'].includes(document.status),
        authorization_reason: 'document_or_project_owner',
        blockers: [],
      },
      {
        status: 'review',
        label: '评审',
        permission_action: 'documents.review',
        allowed: ['draft', 'writing', 'approved'].includes(document.status),
        authorization_reason: 'rbac',
        blockers: [],
      },
      {
        status: 'approved',
        label: '已批准',
        permission_action: 'documents.approve',
        allowed: ['pending_review', 'review', 'in_review'].includes(document.status),
        authorization_reason: 'rbac',
        blockers: [],
      },
      {
        status: 'published',
        label: '已发布',
        permission_action: 'documents.publish',
        allowed: document.status === 'approved' && unresolvedCommentCount === 0,
        authorization_reason: 'rbac',
        blockers: document.status !== 'approved'
          ? ['Document must be approved before it can be published']
          : unresolvedCommentCount > 0
            ? [`Document has ${unresolvedCommentCount} unresolved comments and cannot be published`]
            : [],
      },
      {
        status: 'archived',
        label: '已归档',
        permission_action: 'documents.archive',
        allowed: document.status !== 'archived',
        authorization_reason: 'rbac',
        blockers: [],
      },
    ]

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        current_status: document.status,
        policy_revision: projectLifecyclePolicy.revision,
        capabilities: options.statusCapabilities ?? defaultCapabilities,
      }),
    })
  })

  // 交互式文档生成会话
  await page.route(/\/api\/v1\/documents\/generation-sessions(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'GET') {
      const requestUrl = new URL(route.request().url())
      const projectId = requestUrl.searchParams.get('project_id')
      const status = requestUrl.searchParams.get('status')
      const filteredSessions = generationSessions
        .filter((session) => !projectId || session.project_id === projectId)
        .filter((session) => !status || session.status === status)
        .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(filteredSessions),
      })
      return
    }

    const payload = JSON.parse(route.request().postData() || '{}')
    const session = createGenerationSession({
      id: 'gen-session-e2e-created',
      project_id: payload.project_id,
      doc_type: payload.doc_type || 'brd',
      title: payload.title || '业务需求文档',
      context_json: payload.context || {},
      updated_at: new Date().toISOString(),
    })
    generationSessions = [session, ...generationSessions.filter((item) => item.id !== session.id)]
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(session),
    })
  })

  await page.route(/\/api\/v1\/documents\/generation-sessions\/[^/]+$/, async (route) => {
    const sessionId = route.request().url().match(/generation-sessions\/([^/?]+)/)?.[1] || 'gen-session-e2e-active'
    const session = generationSessions.find((item) => item.id === sessionId)
    await route.fulfill({
      status: session ? 200 : 404,
      contentType: 'application/json',
      body: JSON.stringify(session || { detail: 'Generation session not found' }),
    })
  })

  await page.route(/\/api\/v1\/documents\/generation-sessions\/[^/]+\/cancel$/, async (route) => {
    const sessionId = route.request().url().match(/generation-sessions\/([^/]+)\//)?.[1] || 'gen-session-e2e-active'
    const session = generationSessions.find((item) => item.id === sessionId)
    if (!session) {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Generation session not found' }),
      })
      return
    }
    if (session.status === 'finalized') {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Cannot cancel finalized generation session' }),
      })
      return
    }

    session.status = 'cancelled'
    session.updated_at = new Date().toISOString()
    session.steps = [
      ...(session.steps || []),
      {
        id: `${session.id}-cancel-step`,
        tenant_id: session.tenant_id,
        session_id: session.id,
        step_index: session.steps?.length || 0,
        role: 'user',
        action_type: 'cancel',
        section_key: session.current_section_key,
        message: '用户取消了文档生成会话。',
        patch_json: { status: 'cancelled' },
        quality_json: {},
        created_by: 'user-admin-001',
        created_at: session.updated_at,
        updated_at: session.updated_at,
      },
    ]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(session),
    })
  })

  await page.route(/\/api\/v1\/documents\/generation-sessions\/[^/]+\/messages$/, async (route) => {
    const sessionId = route.request().url().match(/generation-sessions\/([^/]+)\//)?.[1] || 'gen-session-e2e-001'
    const payload = JSON.parse(route.request().postData() || '{}')
    const session = findGenerationSession(sessionId)
    const current = session.sections.find((section: any) => section.section_key === session.current_section_key) || session.sections[0]
    if (payload.action === 'confirm') {
      current.status = 'confirmed'
      const next = session.sections.find((section: any) => section.position > current.position && section.status === 'pending') || current
      session.current_section_key = next.section_key
    } else if (payload.action === 'skip') {
      current.status = 'skipped'
      const next = session.sections.find((section: any) => section.position > current.position && section.status === 'pending') || current
      session.current_section_key = next.section_key
    } else {
      current.status = 'drafted'
      current.content = `### 已确认信息\n- ${payload.message || '待确认'}\n\n### 待确认事项\n- ⚠️ 待确认：补充可验证指标。`
      current.quality_json = { score: 72, sufficiency_level: 'L3' }
      current.confirmed_facts_json = [payload.message]
    }
    const writeLog = [
      ...((session.stash_json || {}).write_log || []),
      {
        index: ((session.stash_json || {}).write_log || []).length + 1,
        action: payload.action || 'answer',
        section_key: current.section_key,
        section_title: current.title,
        patch_type: payload.action === 'revise' ? 'replace' : 'append',
        old_text: null,
        new_text: current.content,
        verified: true,
        skill_labels: ['业务澄清', '结构化写入', '质量评审'],
      },
    ]
    const pendingConfirmations = payload.action === 'confirm' ? [] : [
      { section_key: current.section_key, section_title: current.title, message: '请确认本节草稿是否可进入下一章节。' },
    ]
    session.context_json = {
      ...(session.context_json || {}),
      entity_state: {
        ...((session.context_json || {}).entity_state || {}),
        doc_type: session.doc_type,
        pending_confirmations: pendingConfirmations,
      },
    }
    session.stash_json = {
      ...(session.stash_json || {}),
      write_log: writeLog,
      skill_trace: [
        ...((session.stash_json || {}).skill_trace || []),
        { label: '业务澄清', status: 'completed', action: payload.action || 'answer', section_key: current.section_key },
      ],
    }
    session.quality_summary_json = {
      ...(session.quality_summary_json || {}),
      confirmed_sections: session.sections.filter((section: any) => section.status === 'confirmed').length,
      delivery_readiness: {
        ready: false,
        export_ready: false,
        review_ready: payload.action === 'confirm',
        blockers: payload.action === 'confirm' ? [] : ['仍有章节未确认'],
      },
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session,
        current_section: session.sections.find((section: any) => section.section_key === session.current_section_key) || current,
        assistant_message: '已形成章节草稿。请确认，或继续补充需要写入本节的信息。',
        section_summaries: session.sections.map((section: any) => ({
          section_key: section.section_key,
          title: section.title,
          status: section.status,
          score: section.quality_json.score || 0,
        })),
        write_log: writeLog,
        skill_trace: [
          { label: '业务澄清', status: 'completed', action: payload.action || 'answer', section_key: current.section_key },
          { label: '结构化写入', status: 'completed', action: payload.action || 'answer', section_key: current.section_key },
          { label: '质量评审', status: 'completed', action: payload.action || 'answer', section_key: current.section_key },
        ],
        quality_gate: {
          ready: false,
          export_ready: false,
          review_ready: payload.action === 'confirm',
          blockers: payload.action === 'confirm' ? [] : ['仍有章节未确认'],
        },
        pending_confirmations: pendingConfirmations,
      }),
    })
  })

  await page.route(/\/api\/v1\/documents\/generation-sessions\/[^/]+\/finalize$/, async (route) => {
    const sessionId = route.request().url().match(/generation-sessions\/([^/]+)\//)?.[1] || 'gen-session-e2e-001'
    const session = findGenerationSession(sessionId)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        document_id: 'doc-e2e-interactive-001',
        doc_type: session.doc_type,
        title: session.title,
        content: '# 交互式生成文档\n## 1. 背景与目标\n已形成章节草稿。',
        status: 'draft',
        version: 1,
        generated_at: new Date().toISOString(),
      }),
    })
  })

  // 文档生成接口
  await page.route('**/api/v1/documents/generate', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        document_id: 'doc-e2e-001',
        doc_type: 'urs',
        title: '用户需求规格说明书',
        content: '# 智能生成的文档内容\n通过 Mock 生成完成。',
        status: 'published',
        version: 1,
        generated_at: new Date().toISOString(),
      }),
    })
  })

  // 文档统计汇总
  await page.route('**/api/v1/documents/statistics/summary', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_documents: MOCK.MOCK_DOCUMENTS.length,
        published_documents: MOCK.MOCK_DOCUMENTS.filter((document) => document.status === 'published').length,
        draft_documents: 1,
      }),
    })
  })

  // 文档正式引用
  await page.route(/\/api\/v1\/documents\/[^/]+\/references(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    const url = new URL(route.request().url())
    const pathParts = url.pathname.split('/')
    const documentId = pathParts[pathParts.length - 2] || 'doc-e2e-001'

    if (method === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK.MOCK_TRACEABILITY_REFERENCES[0],
          id: `ref-${Date.now()}`,
          source_document_id: documentId,
          target_document_id: payload.target_document_id || 'doc-e2e-003',
          reference_type: payload.reference_type || 'derives_from',
          source_section: payload.source_section || null,
          target_section: payload.target_section || null,
        }),
      })
      return
    }

    const direction = url.searchParams.get('direction') || 'all'
    const items = MOCK.MOCK_TRACEABILITY_REFERENCES.filter((reference) => {
      if (direction === 'incoming') return reference.target_document_id === documentId
      if (direction === 'outgoing') return reference.source_document_id === documentId
      return reference.source_document_id === documentId || reference.target_document_id === documentId
    })
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items, total: items.length }),
    })
  })

  // 文档影响分析
  await page.route(/\/api\/v1\/documents\/[^/]+\/impact-analysis$/, async (route) => {
    const pathParts = new URL(route.request().url()).pathname.split('/')
    const documentId = pathParts[pathParts.length - 2] || 'doc-e2e-001'
    traceabilityImpactAnalysis = {
      ...structuredClone(MOCK.MOCK_TRACEABILITY_BOARD_IMPACT),
      trigger_document_id: documentId,
    }
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(traceabilityImpactAnalysis),
    })
  })


  // ==================== 4. KNOWLEDGE BASE & GRAPH ====================

  const knowledgeGraphNodes = [
    {
      id: 'entry-source-ready-001',
      type: 'text',
      title: '仓储批次分配规则',
      summary: '仓储系统需要按批次、库区和人工复核结果生成分配建议，并保留验收指标。',
      project_id: 'project-e2e-001',
      source_file_id: 'file-e2e-ready',
      source_label: '仓储升级招标文件.pdf',
      status: 'ready',
      confidence: 0.92,
      metadata: {
        title: '仓储批次分配规则',
        sourceFileName: '仓储升级招标文件.pdf',
        sourceFileId: 'file-e2e-ready',
        state: 'ready',
        summary: '仓储系统需要按批次、库区和人工复核结果生成分配建议。',
      },
      created_at: '2026-05-21T09:00:00Z',
      updated_at: '2026-05-21T09:00:00Z',
    },
    {
      id: 'entry-source-gap-001',
      type: 'text',
      title: '验收证据缺口',
      summary: '验收材料已有范围描述，但缺少客户签收日期和验收负责人。',
      project_id: 'project-e2e-001',
      source_file_id: 'file-e2e-failed',
      source_label: '验收访谈纪要.docx',
      status: 'gap',
      confidence: 0.66,
      metadata: {
        title: '验收证据缺口',
        sourceFileName: '验收访谈纪要.docx',
        sourceFileId: 'file-e2e-failed',
        state: 'gap',
        gap: '缺少验收签收日期，需要补充客户确认材料。',
      },
      created_at: '2026-05-21T09:05:00Z',
      updated_at: '2026-05-21T09:05:00Z',
    },
    {
      id: 'entry-source-conflict-001',
      type: 'text',
      title: '上线窗口冲突',
      summary: '合同附件与访谈纪要对上线窗口存在冲突，需要人工裁决。',
      project_id: 'project-e2e-001',
      source_file_id: 'file-e2e-ready-2',
      source_label: '合同附件.xlsx',
      status: 'conflict',
      confidence: 0.61,
      metadata: {
        title: '上线窗口冲突',
        sourceFileName: '合同附件.xlsx',
        sourceFileId: 'file-e2e-ready-2',
        state: 'conflict',
        conflict: '合同附件要求 6 月上线，访谈纪要要求 7 月灰度。',
      },
      created_at: '2026-05-21T09:10:00Z',
      updated_at: '2026-05-21T09:10:00Z',
    },
  ]

  const knowledgeGraphEdges = [
    {
      id: 'link-e2e-001',
      source: 'entry-source-ready-001',
      target: 'entry-source-gap-001',
      type: 'depends_on',
      confidence: 0.88,
      metadata: { description: '验收规则依赖签收证据' },
      created_at: '2026-05-21T09:20:00Z',
    },
    {
      id: 'link-e2e-002',
      source: 'entry-source-conflict-001',
      target: 'entry-source-ready-001',
      type: 'cites',
      confidence: 0.72,
      metadata: { description: '上线窗口影响批次分配计划' },
      created_at: '2026-05-21T09:25:00Z',
    },
  ]

  await page.route('**/api/v1/knowledge/graph*', async (route) => {
    const url = new URL(route.request().url())
    const projectId = url.searchParams.get('project_id')
    const sourceFileId = url.searchParams.get('source_file_id')
    const nodes = knowledgeGraphNodes.filter((node) => {
      if (projectId && node.project_id !== projectId) return false
      if (sourceFileId && node.source_file_id !== sourceFileId) return false
      return true
    })
    const nodeIds = new Set(nodes.map((node) => node.id))
    const edges = knowledgeGraphEdges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    const linkedIds = new Set(edges.flatMap((edge) => [edge.source, edge.target]))
    const gaps = nodes.filter((node) => node.status === 'gap' || node.status === 'conflict')
    const isolatedNodes = nodes.filter((node) => !linkedIds.has(node.id))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        nodes,
        edges,
        summary: {
          node_count: nodes.length,
          edge_count: edges.length,
          source_count: new Set(nodes.map((node) => node.source_file_id || node.source_label)).size,
          ready_count: nodes.filter((node) => node.status === 'ready').length,
          gap_count: nodes.filter((node) => node.status === 'gap').length,
          conflict_count: nodes.filter((node) => node.status === 'conflict').length,
          isolated_count: isolatedNodes.length,
        },
        gaps,
        isolated_nodes: isolatedNodes,
      }),
    })
  })

  await page.route(/\/api\/v1\/knowledge\/entries\/[^/]+\/link$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        id: `link-created-${Date.now()}`,
        source_entry_id: payload.source_entry_id,
        target_entry_id: payload.target_entry_id,
        link_type: payload.link_type || 'cites',
        confidence: payload.confidence ?? 0.9,
        metadata_json: payload.metadata || {},
        created_at: '2026-05-21T10:05:00Z',
      }),
    })
  })

  await page.route(/\/api\/v1\/knowledge\/links\/[^/]+$/, async (route) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({ status: 204, body: '' })
      return
    }
    if (route.request().method() === 'PATCH') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'link-e2e-001',
          source_entry_id: 'entry-source-ready-001',
          target_entry_id: 'entry-source-gap-001',
          link_type: payload.link_type || 'depends_on',
          confidence: payload.confidence ?? 0.9,
          metadata_json: payload.metadata || {},
          created_at: '2026-05-21T10:05:00Z',
        }),
      })
      return
    }
    await route.fallback()
  })

  await page.route(/\/api\/v1\/knowledge\/entries\/[^/]+\/lineage$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'lineage-e2e-001',
          project_id: 'project-e2e-001',
          source_type: 'source_file',
          source_id: 'file-e2e-ready',
          target_type: 'knowledge_entry',
          target_id: 'entry-source-ready-001',
          lineage_type: 'derived_from',
          metadata_json: { extractor: 'GraphRAG' },
          created_at: '2026-05-21T09:30:00Z',
        },
      ]),
    })
  })

  await page.route(/\/api\/v1\/knowledge\/provenance\/[^/]+$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'provenance-e2e-001',
          project_id: 'project-e2e-001',
          entry_id: 'entry-source-ready-001',
          provider_id: 'source_file_ingest',
          provider_version_id: '1.0',
          raw_artifact_id: 'file-e2e-ready',
          confidence: 0.92,
          normalization_notes: '从项目资料抽取并人工复核。',
          created_at: '2026-05-21T09:31:00Z',
        },
      ]),
    })
  })

  // 获取知识条目列表
  await page.route('**/api/v1/knowledge/entries*', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: `entry-created-${Date.now()}`,
          entry_type: payload.entry_type || 'text',
          content: payload.content || '',
          metadata: payload.metadata || {},
          project_id: payload.project_id || 'project-e2e-001',
          source_file_id: payload.source_file_id || null,
          created_at: '2026-05-21T10:00:00Z',
          updated_at: '2026-05-21T10:00:00Z',
        }),
      })
      return
    }

    const url = new URL(route.request().url())
    const projectId = url.searchParams.get('project_id')
    const sourceFileId = url.searchParams.get('source_file_id')
    const entries = MOCK.MOCK_KNOWLEDGE_ENTRIES.filter((entry) => {
      if (projectId && entry.project_id !== projectId) return false
      if (sourceFileId && entry.source_file_id !== sourceFileId) return false
      return true
    })

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: entries,
        total: entries.length,
      }),
    })
  })

  // 批量添加知识库节点
  await page.route('**/api/v1/knowledge/entries/bulk', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, count: 2 }),
    })
  })

  // 获取知识关联 (Links)
  await page.route('**/api/v1/knowledge/links*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: MOCK.MOCK_KNOWLEDGE_LINKS,
      }),
    })
  })

  // 知识库搜索检索
  await page.route('**/api/v1/knowledge/search*', async (route) => {
    const url = new URL(route.request().url())
    const query = (url.searchParams.get('q') || '').toLowerCase()
    const results = knowledgeGraphNodes
      .filter((node) => {
        if (!query) return true
        return [node.title, node.summary, node.source_label, JSON.stringify(node.metadata)].join(' ').toLowerCase().includes(query)
      })
      .map((node, index) => ({
        entry: {
          id: node.id,
          entry_type: node.type,
          content: node.summary,
          metadata: node.metadata,
          project_id: node.project_id,
          source_file_id: node.source_file_id,
          created_at: node.created_at,
          updated_at: node.updated_at,
        },
        node: {
          id: node.id,
          type: node.type,
          properties: node.metadata,
        },
        score: 0.95 - index * 0.1,
        highlight: node.summary,
        highlights: [node.title, node.source_label],
      }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ results }),
    })
  })


  // ==================== 5. TEMPLATES ====================

  // 模板列表与创建
  await page.route(/\/api\/v1\/templates\/?(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const template = {
        ...templates[0],
        id: `template-${Date.now()}`,
        name: payload.name || templates[0].name,
        description: payload.description || '',
        doc_type: payload.doc_type || 'urs',
        version_count: 0,
      }
      templates = [template, ...templates]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(template),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: templates.map((template) => ({
            ...template,
            version_count: templateVersions.length,
          })),
          total: templates.length,
        }),
      })
    }
  })

  // 特定模板详情与删除
  await page.route(/\/api\/v1\/templates\/parse-upload(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        placeholders: [
          {
            name: '项目名称',
            description: '自动提取的占位符：项目名称',
            field_type: 'text',
            required: true,
            occurrence_count: 1,
          },
          {
            name: '客户名称',
            description: '自动提取的占位符：客户名称',
            field_type: 'text',
            required: true,
            occurrence_count: 2,
          },
        ],
        page_types: [
          {
            page_number: 1,
            page_type: 'title',
            title_placeholder: '项目名称',
            content_placeholders: ['项目名称', '客户名称'],
          },
        ],
        file_hash: 'sha256-template-parse-evidence',
        total_pages: 1,
        is_valid: true,
        warnings: [],
        errors: [],
        invalid_placeholders: [],
        duplicate_placeholders: ['客户名称'],
        content_format: 'pptx',
      }),
    })
  })

  await page.route(/\/api\/v1\/templates\/upload(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url())
    const templateId = url.searchParams.get('template_id') || templates[0].id
    normalizeActiveVersion('')
    const uploadedVersion = {
      ...templateVersions[0],
      id: `version-${Date.now()}`,
      template_id: templateId,
      version: templateVersions.length + 1,
      is_active: 'true',
      placeholder_schema: [
        { name: '项目名称', description: '自动提取的占位符：项目名称', field_type: 'text', required: true, occurrence_count: 1 },
        { name: '客户名称', description: '自动提取的占位符：客户名称', field_type: 'text', required: true, occurrence_count: 2 },
      ],
      page_types: [{ page_number: 1, page_type: 'title', title_placeholder: '项目名称', content_placeholders: ['项目名称', '客户名称'] }],
      created_at: new Date().toISOString(),
    }
    templateVersions = [uploadedVersion, ...templateVersions]
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(uploadedVersion),
    })
  })

  await page.route(/\/api\/v1\/templates\/[^/]+\/sections\/seed(?:\?.*)?$/, async (route) => {
    const now = new Date().toISOString()
    const hasUserNeeds = templateSections.some((section) => section.section_key === 'urs.user-needs')
    if (!hasUserNeeds) {
      templateSections = [
        ...templateSections,
        {
          ...MOCK.MOCK_TEMPLATE_SECTIONS[0],
          id: 'section-e2e-002',
          section_key: 'urs.user-needs',
          title: '用户需求',
          position: 1,
          content_requirement: '列出用户角色、业务场景和用户目标。',
          prompt: '请按用户角色和业务场景整理 URS 用户需求。',
          required_inputs: ['user_roles', 'business_scenarios'],
          quality_rules: [{ rule: '每项需求必须能追溯到用户或场景', severity: 'high' }],
          skill_bindings: [],
          created_at: now,
          updated_at: now,
        },
        {
          ...MOCK.MOCK_TEMPLATE_SECTIONS[0],
          id: 'section-e2e-003',
          section_key: 'urs.acceptance',
          title: '验收标准',
          position: 2,
          content_requirement: '定义可验证的验收标准和评审口径。',
          prompt: '请为每项用户需求生成可验证的验收标准。',
          required_inputs: ['requirements'],
          quality_rules: [{ rule: '验收标准必须可测试', severity: 'high' }],
          skill_bindings: [],
          created_at: now,
          updated_at: now,
        },
      ]
    }
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(templateSections),
    })
  })

  await page.route(/\/api\/v1\/templates\/[^/]+\/sections(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    if (method === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const now = new Date().toISOString()
      const section = {
        id: `section-${Date.now()}`,
        tenant_id: 'tenant-e2e-001',
        template_version_id: payload.template_version_id || 'version-e2e-001',
        parent_section_id: payload.parent_section_id || null,
        section_key: payload.section_key,
        title: payload.title,
        level: payload.level || 1,
        position: payload.position ?? templateSections.length,
        content_requirement: payload.content_requirement || '',
        prompt: payload.prompt || '',
        required_inputs: payload.required_inputs || [],
        quality_rules: payload.quality_rules || [],
        created_by: 'user-admin-001',
        created_at: now,
        updated_at: now,
        deleted_at: null,
        skill_bindings: [],
      }
      templateSections = [...templateSections, section]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(section),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(templateSections),
      })
    }
  })

  await page.route(/\/api\/v1\/templates\/sections\/[^/]+\/skills$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const sectionId = route.request().url().split('/').slice(-2)[0]
    const bindings = (payload.skill_ids || []).map((skillId: string, index: number) => ({
      id: `section-binding-${Date.now()}-${index}`,
      tenant_id: 'tenant-e2e-001',
      section_id: sectionId,
      skill_id: skillId,
      order_index: index,
      is_required: true,
      prompt_override: null,
      created_by: 'user-admin-001',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      skill: MOCK.MOCK_SKILL_CATALOG.find((skill) => skill.id === skillId) || null,
    }))
    templateSections = templateSections.map((section) =>
      section.id === sectionId ? { ...section, skill_bindings: bindings } : section
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(bindings),
    })
  })

  await page.route(/\/api\/v1\/templates\/(?!(?:upload|parse-upload)(?:\?.*)?$)[^/?]+(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(templates[0]),
      })
    }
  })

  await page.route(/\/api\/v1\/templates\/[^/]+\/versions\/[^/]+\/activate$/, async (route) => {
    const match = route.request().url().match(/\/versions\/([^/]+)\/activate$/)
    const versionId = match?.[1] || templateVersions[0].id
    normalizeActiveVersion(versionId)
    const version = templateVersions.find((item) => item.id === versionId) || templateVersions[0]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(version),
    })
  })

  // 模板版本列表与上传新版本
  await page.route(/\/api\/v1\/templates\/[^/]+\/versions(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      normalizeActiveVersion('')
      const version = {
        ...templateVersions[0],
        id: `version-${Date.now()}`,
        version: templateVersions.length + 1,
        is_active: 'true',
        created_at: new Date().toISOString(),
      }
      templateVersions = [version, ...templateVersions]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(version),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: templateVersions,
        }),
      })
    }
  })


  // ==================== 6. PROVIDERS (LLM) ====================

  await page.route(/\/api\/v1\/providers\/readiness\/?(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tenant_id: 'tenant-e2e-001',
        total_providers: 3,
        live_providers: 1,
        sandbox_providers: 1,
        unconfigured_providers: 1,
        inactive_providers: 0,
        readiness_score: 23,
        production_ready: false,
        missing_required_types: ['graphify', 'gitnexus'],
        required_types: [
          {
            provider_type: 'llm',
            label: 'LLM 生成',
            live_count: 1,
            sandbox_count: 0,
            unconfigured_count: 0,
            status: 'ready',
          },
          {
            provider_type: 'graphify',
            label: 'Graphify 图谱',
            live_count: 0,
            sandbox_count: 0,
            unconfigured_count: 1,
            status: 'unconfigured',
          },
          {
            provider_type: 'gitnexus',
            label: 'GitNexus 代码索引',
            live_count: 0,
            sandbox_count: 1,
            unconfigured_count: 0,
            status: 'sandbox',
          },
        ],
        items: [
          {
            provider_id: 'provider-e2e-002',
            name: 'OpenAI LLM Provider',
            provider_type: 'llm',
            status: 'active',
            readiness: 'ready',
            reason: 'llm 已具备生产配置',
            recommended_action: '定期运行联调测试并保留审计证据。',
          },
          {
            provider_id: 'provider-e2e-001',
            name: 'Graphify Knowledge Provider',
            provider_type: 'graphify',
            status: 'active',
            readiness: 'unconfigured',
            reason: 'Provider 缺少真实凭据或必要生产配置',
            recommended_action: '补齐 Graphify Knowledge Provider 的 service_key 与服务端点。',
          },
          {
            provider_id: 'provider-e2e-003',
            name: 'GitNexus Sandbox Provider',
            provider_type: 'gitnexus',
            status: 'active',
            readiness: 'sandbox',
            reason: 'Provider 使用 sandbox/mock/test/demo 配置',
            recommended_action: '为 GitNexus Sandbox Provider 配置真实服务凭据和生产模式。',
          },
        ],
        recommended_actions: [
          '补齐核心 Provider 类型：Graphify 图谱, GitNexus 代码索引。',
          '补齐 Graphify Knowledge Provider 的 service_key 与服务端点。',
          '为 GitNexus Sandbox Provider 配置真实服务凭据和生产模式。',
        ],
      }),
    })
  })

  // 供应商列表与创建
  await page.route(/\/api\/v1\/providers\/?(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    if (method === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: `provider-${Date.now()}`,
          name: payload.name || '新供应商',
          type: payload.provider_type || 'openai',
          config: payload.config || {},
          isActive: true,
          status: 'active',
          ops_profile: {
            health: 'healthy',
            latency_ms: 0,
            last_test_result: 'passed',
            quota_impact: '新供应商尚未产生配额影响',
          },
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: MOCK.MOCK_PROVIDER,
          total: MOCK.MOCK_PROVIDER.length,
          page: 1,
          page_size: 10,
          has_more: false,
        }),
      })
    }
  })

  // 特定供应商详情与更新/删除
  await page.route(/\/api\/v1\/providers\/(?!readiness(?:\/|\?|$))[^/?]+(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    if (method === 'PATCH') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK.MOCK_PROVIDER[0],
          name: payload.name || MOCK.MOCK_PROVIDER[0].name,
          config: payload.config || MOCK.MOCK_PROVIDER[0].config,
          isActive: payload.status ? payload.status === 'active' : MOCK.MOCK_PROVIDER[0].isActive,
          status: payload.status || MOCK.MOCK_PROVIDER[0].status,
        }),
      })
    } else if (method === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK.MOCK_PROVIDER[0]),
      })
    }
  })

  // 测试供应商连接
  await page.route(/\/api\/v1\/providers\/[^/]+\/test$/, async (route) => {
    const providerId = route.request().url().match(/\/providers\/([^/]+)\/test/)?.[1]
    const isGraphify = providerId === 'provider-e2e-001'
    const isGitNexus = providerId === 'provider-e2e-003'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: !isGraphify && !isGitNexus,
        message: isGraphify
          ? 'Graphify 主链路超时，sandbox fallback 已接管'
          : isGitNexus
            ? 'GitNexus 索引服务不可用，请先恢复索引服务'
          : 'Mock 测试连接成功：供应商通信正常',
        sandbox_fallback: isGraphify,
        latency_ms: isGraphify ? 860 : isGitNexus ? null : 228,
        output: {
          provider_id: providerId,
          checked_at: '2026-06-03T08:00:00Z',
        },
        status: isGraphify ? 'degraded' : isGitNexus ? 'unhealthy' : 'healthy',
        mode: isGraphify ? 'sandbox_fallback' : 'mock',
        capability_type: isGraphify ? 'graphify' : isGitNexus ? 'gitnexus' : 'llm',
        configured: true,
        production_ready: !isGraphify && !isGitNexus,
      }),
    })
  })


  // ==================== 7. OPERATIONS & METRICS (OPS) ====================

  await page.route('**/api/v1/ops/health*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_OPS_DATA.health),
    })
  })

  await page.route('**/api/v1/ops/production-command-center*', async (route) => {
    const readiness = MOCK.MOCK_OPS_DATA.capability_readiness
    const commissioning = {
      ...MOCK.MOCK_OPS_DATA.capability_commissioning,
      readiness,
    }
    const blockers = commissioning.checks
      .filter((check: any) => check.status === 'failed' || check.status === 'warning')
      .map((check: any) => ({
        key: check.key,
        capability_key: check.capability_key,
        label: check.label,
        severity: check.severity,
        source: 'commissioning',
        summary: check.blockers[0] || check.summary,
        action_label: check.action.label,
        action_href: check.action.href,
        api_endpoint: check.action.api_endpoint,
      }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-05-21T09:00:00Z',
        tenant_id: 'tenant-e2e-001',
        release_gate: {
          status: 'blocked',
          can_release: false,
          readiness_score: readiness.overall_score,
          commissioning_score: commissioning.overall_score,
          summary: '存在关键阻塞，发布前必须完成处置和复核。',
        },
        summary: {
          capabilities: readiness.capabilities.length,
          ready_capabilities: readiness.capabilities.filter((item: any) => item.status === 'ready').length,
          degraded_capabilities: readiness.capabilities.filter((item: any) => item.status === 'degraded').length,
          blocked_capabilities: readiness.capabilities.filter((item: any) => item.status === 'blocked').length,
          commissioning_checks: commissioning.checks.length,
          failed_checks: commissioning.checks.filter((item: any) => item.status === 'failed').length,
          warning_checks: commissioning.checks.filter((item: any) => item.status === 'warning').length,
          runnable_checks: commissioning.checks.filter((item: any) => item.can_run).length,
          critical_blockers: blockers.filter((item: any) => item.severity === 'critical').length,
          high_blockers: blockers.filter((item: any) => item.severity === 'high').length,
        },
        blockers,
        priority_actions: blockers.map((blocker: any) => ({
          key: blocker.key,
          label: blocker.action_label,
          href: blocker.action_href,
          capability_key: blocker.capability_key,
          severity: blocker.severity,
          description: blocker.summary,
          api_endpoint: blocker.api_endpoint,
        })),
        readiness,
        commissioning,
        next_steps: ['先处理知识图谱和外部同步阻塞。', '运行校准检查并保留投产证据。'],
      }),
    })
  })

  await page.route('**/api/v1/ops/capabilities/readiness*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_OPS_DATA.capability_readiness),
    })
  })

  await page.route('**/api/v1/ops/capabilities/commissioning/run*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...MOCK.MOCK_OPS_DATA.capability_commissioning,
        generated_at: new Date().toISOString(),
        executed: true,
        checks: MOCK.MOCK_OPS_DATA.capability_commissioning.checks.map((check: any) => ({
          ...check,
          run_status: check.status === 'passed' ? 'passed' : 'failed',
          run_result: {
            status: check.status,
            evaluated_at: new Date().toISOString(),
            blocker_count: check.blockers.length,
          },
        })),
        readiness: MOCK.MOCK_OPS_DATA.capability_readiness,
      }),
    })
  })

  await page.route('**/api/v1/ops/capabilities/commissioning*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...MOCK.MOCK_OPS_DATA.capability_commissioning,
        readiness: MOCK.MOCK_OPS_DATA.capability_readiness,
      }),
    })
  })

  await page.route('**/api/v1/ops/capabilities/activation-plan*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...MOCK.MOCK_OPS_DATA.capability_activation,
        readiness_before: MOCK.MOCK_OPS_DATA.capability_readiness,
      }),
    })
  })

  await page.route('**/api/v1/ops/capabilities/activation-run*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...MOCK.MOCK_OPS_DATA.capability_activation,
        dry_run: false,
        executed: true,
        readiness_before: MOCK.MOCK_OPS_DATA.capability_readiness,
        readiness_after: {
          ...MOCK.MOCK_OPS_DATA.capability_readiness,
          generated_at: new Date().toISOString(),
          overall_score: 84,
        },
        actions: MOCK.MOCK_OPS_DATA.capability_activation.actions.map((action: any) =>
          action.can_execute
            ? {
                ...action,
                status: 'completed',
                result: {
                  completed: true,
                  created_or_updated: true,
                },
              }
            : action
        ),
        summary: {
          safe_action_count: 2,
          manual_action_count: 2,
          completed_action_count: 2,
          blocked_action_count: 0,
        },
      }),
    })
  })

  await page.route(/\/api\/v1\/ops\/quota-command-center(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: new Date().toISOString(),
        tenant_id: 'tenant-e2e-001',
        release_gate: {
          status: 'attention',
          can_operate: true,
          label: '需要关注',
          summary: '当前仍可运行，但应在继续放量前处置高风险项。',
          blockers: [],
          warnings: ['异常 Provider 可能放大重试与配额消耗。'],
        },
        summary: {
          api_used: 7600,
          api_limit: 10000,
          api_remaining: 2400,
          api_usage_percent: 76,
          total_requests: 7600,
          successful_requests: 7440,
          failed_requests: 160,
          failure_rate_percent: 2.1,
          average_latency_ms: 286,
          daily_burn: 253,
          projected_days_remaining: 9,
          risky_endpoint_count: 1,
          provider_risk_count: 1,
          open_breaker_count: 1,
        },
        risk_items: [
          {
            code: 'provider_health_attention',
            severity: 'high',
            title: 'Provider 健康风险',
            detail: 'Graphify fallback 正在放大重试与配额消耗。',
            count: 1,
            href: '/providers',
          },
        ],
        priority_actions: [
          {
            code: 'provider_health_attention',
            title: '处理 Provider 健康风险',
            description: 'Graphify fallback 正在放大重试与配额消耗。',
            href: '/providers',
            priority: 'high',
          },
        ],
        rate_limit_risks: [
          {
            endpoint: '/api/agent',
            limit: 100,
            remaining: 8,
            used_percentage: 92,
            reset_at: new Date(Date.now() + 3600000).toISOString(),
          },
        ],
      }),
    })
  })

  await page.route('**/api/v1/ops/quotas*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_OPS_DATA.quotas_list),
    })
  })

  await page.route('**/api/v1/ops/rate-limits*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_OPS_DATA.rate_limits),
    })
  })

  await page.route('**/api/v1/ops/usage-stats*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_OPS_DATA.usage_stats),
    })
  })

  await page.route(/\/api\/v1\/ops\/metrics\/tenant\/[^/?]+(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tenant_id: 'tenant-e2e-001',
        timestamp: new Date().toISOString(),
        api_calls_today: 120,
        api_calls_this_month: 2400,
        storage_used_bytes: 2048500,
        storage_limit_bytes: 10737418240,
        document_count: MOCK.MOCK_DOCUMENTS.length,
        user_count: 1,
        active_agents: 1,
      }),
    })
  })

  await page.route(/\/api\/v1\/ops\/metrics(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_OPS_DATA.metrics),
    })
  })

  await page.route(/\/api\/v1\/ops\/quota(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_OPS_DATA.quota),
    })
  })

  await page.route('**/api/v1/ops/circuit-breakers*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        breakers: [
          { name: 'graphify-service-breaker', state: 'half_open', failure_count: 6, last_failure_time: '2026-05-31T08:40:00Z' },
          { name: 'llm-service-breaker', state: 'closed', failure_count: 0, last_failure_time: null },
          { name: 'gitnexus-service-breaker', state: 'open', failure_count: 12, last_failure_time: '2026-05-31T08:35:00Z' }
        ],
      }),
    })
  })


  // ==================== 8. AGENT & WORKFLOWS ====================

  // Skill 市场
  await page.route(/\/api\/v1\/agent\/skills\/catalog(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    if (method === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const skill = {
        ...MOCK.MOCK_SKILL_CATALOG[0],
        id: `skill-${Date.now()}`,
        name: payload.name || '自定义 Skill',
        display_name: payload.display_name || payload.name || '自定义 Skill',
        effective_display_name: payload.display_name || payload.name || '自定义 Skill',
        description: payload.description || '',
        skill_type: payload.skill_type || 'custom',
        category: payload.category || 'custom',
        input_schema_json: payload.input_schema_json || { type: 'object' },
        output_schema_json: payload.output_schema_json || { type: 'object' },
        supported_doc_types: payload.supported_doc_types || [],
        supported_industries: payload.supported_industries || [],
        version: payload.version || '1.0.0',
        implementation_ref: payload.implementation_ref || null,
        metadata_json: payload.metadata_json || {},
        is_builtin: false,
        status: payload.status || 'draft',
        governance_scope: payload.governance_scope || 'tenant',
        visibility: payload.visibility || 'tenant',
        managed_by: 'tenant',
        is_locked: false,
        can_edit: true,
        can_publish: true,
        can_disable: true,
        locked_reason: null,
      }
      skillCatalog = [skill, ...skillCatalog]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(skill),
      })
    } else {
      const url = new URL(route.request().url())
      const status = url.searchParams.get('status')
      const skillType = url.searchParams.get('skill_type')
      const docType = url.searchParams.get('doc_type')
      const search = (url.searchParams.get('search') || '').toLowerCase()
      const items = skillCatalog.filter((skill) => {
        const matchesStatus = !status || skill.status === status
        const matchesType = !skillType || skill.skill_type === skillType
        const matchesDocType = !docType || (skill.supported_doc_types || []).includes(docType)
        const matchesSearch = !search ||
          skill.name.toLowerCase().includes(search) ||
          (skill.display_name || '').toLowerCase().includes(search) ||
          (skill.effective_display_name || '').toLowerCase().includes(search) ||
          (skill.description || '').toLowerCase().includes(search) ||
          (skill.category || '').toLowerCase().includes(search)
        return matchesStatus && matchesType && matchesDocType && matchesSearch
      })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items,
          total: items.length,
          page: 1,
          page_size: 100,
          has_more: false,
        }),
      })
    }
  })

  await page.route(/\/api\/v1\/agent\/skills\/catalog\/[^/]+\/(?:publish|disable)$/, async (route) => {
    const skillId = route.request().url().match(/\/skills\/catalog\/([^/]+)\//)?.[1] || skillCatalog[0].id
    const isDisable = route.request().url().endsWith('/disable')
    const nextStatus = isDisable ? 'disabled' : 'published'
    skillCatalog = skillCatalog.map((skill) => skill.id === skillId ? { ...skill, status: nextStatus } : skill)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(findSkill(skillId)),
    })
  })

  await page.route(/\/api\/v1\/agent\/skills\/catalog\/[^/]+\/test$/, async (route) => {
    const skillId = route.request().url().match(/\/skills\/catalog\/([^/]+)\//)?.[1] || skillCatalog[0].id
    const skill = findSkill(skillId)
    const payload = JSON.parse(route.request().postData() || '{}')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        skill_id: skill.id,
        skill_name: skill.name,
        success: true,
        output_data: {
          summary: '测试输入满足 Skill 契约，并返回可展示的示例结果。',
          score: 0.92,
          checked_fields: Object.keys(payload.input_data || {}),
          recommendation: '测试输入满足 Skill 契约。',
        },
        error_message: null,
        execution_time_ms: 12.4,
        mode: skill.implementation_ref?.startsWith('builtin:') ? 'builtin' : 'contract',
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/skills\/catalog\/[^/?]+(?:\?.*)?$/, async (route) => {
    const skillId = route.request().url().match(/\/skills\/catalog\/([^/?]+)/)?.[1] || skillCatalog[0].id
    const payload = JSON.parse(route.request().postData() || '{}')
    skillCatalog = skillCatalog.map((skill) => skill.id === skillId ? {
      ...skill,
      ...payload,
      effective_display_name: payload.display_name || skill.effective_display_name || payload.name || skill.name,
    } : skill)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(findSkill(skillId)),
    })
  })

  // Agent 配置中心
  await page.route(/\/api\/v1\/agent\/agent-profiles(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    if (method === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const agent = hydrateAgentProfile({
        ...MOCK.MOCK_AGENT_PROFILES[0],
        id: `agent-profile-${Date.now()}`,
        name: payload.name || '自定义 Agent',
        description: payload.description || '',
        agent_type: payload.agent_type || 'custom',
        applicable_doc_types: payload.applicable_doc_types || [],
        tool_names: payload.tool_names || [],
        workflow_definition_id: payload.workflow_definition_id || null,
        human_review_required: payload.human_review_required ?? true,
        system_prompt: payload.system_prompt || '',
        status: payload.status || 'active',
        skill_bindings: (payload.skill_ids || []).map((skillId: string, index: number) => ({
          id: `binding-new-${index}`,
          tenant_id: 'tenant-e2e-001',
          agent_profile_id: 'agent-profile-new',
          skill_id: skillId,
          order_index: index,
          is_required: true,
        })),
      })
      agentProfiles = [agent, ...agentProfiles]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(agent),
      })
    } else {
      const url = new URL(route.request().url())
      const status = url.searchParams.get('status')
      const agentType = url.searchParams.get('agent_type')
      const docType = url.searchParams.get('doc_type')
      const search = (url.searchParams.get('search') || '').toLowerCase()
      const items = agentProfiles.map(hydrateAgentProfile).filter((agent) => {
        const matchesStatus = !status || agent.status === status
        const matchesType = !agentType || agent.agent_type === agentType
        const matchesDocType = !docType || (agent.applicable_doc_types || []).includes(docType)
        const matchesSearch = !search ||
          agent.name.toLowerCase().includes(search) ||
          (agent.description || '').toLowerCase().includes(search)
        return matchesStatus && matchesType && matchesDocType && matchesSearch
      })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items,
          total: items.length,
          page: 1,
          page_size: 100,
          has_more: false,
        }),
      })
    }
  })

  await page.route(/\/api\/v1\/agent\/agent-profiles\/[^/]+\/(?:activate|disable|skills)$/, async (route) => {
    const url = route.request().url()
    const agentId = url.match(/\/agent-profiles\/([^/]+)\//)?.[1] || agentProfiles[0].id
    const method = route.request().method()
    if (url.endsWith('/skills')) {
      const payload = JSON.parse(route.request().postData() || '{}')
      agentProfiles = agentProfiles.map((agent) => agent.id === agentId ? {
        ...agent,
        skill_bindings: (payload.skill_ids || []).map((skillId: string, index: number) => ({
          id: `binding-${agentId}-${index}`,
          tenant_id: agent.tenant_id,
          agent_profile_id: agentId,
          skill_id: skillId,
          order_index: index,
          is_required: true,
        })),
      } : agent)
    } else if (method === 'POST') {
      const isDisable = url.endsWith('/disable')
      agentProfiles = agentProfiles.map((agent) => agent.id === agentId ? {
        ...agent,
        status: isDisable ? 'disabled' : 'active',
      } : agent)
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(hydrateAgentProfile(agentProfiles.find((agent) => agent.id === agentId) || agentProfiles[0])),
    })
  })

  await page.route(/\/api\/v1\/agent\/agent-profiles\/[^/?]+(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    const agentId = route.request().url().match(/\/agent-profiles\/([^/?]+)/)?.[1] || agentProfiles[0].id
    const payload = method === 'PATCH' ? JSON.parse(route.request().postData() || '{}') : {}
    if (method === 'PATCH') {
      agentProfiles = agentProfiles.map((agent) => agent.id === agentId ? {
        ...agent,
        ...payload,
        skill_bindings: payload.skill_ids
          ? payload.skill_ids.map((skillId: string, index: number) => ({
              id: `binding-${agentId}-${index}`,
              tenant_id: agent.tenant_id,
              agent_profile_id: agentId,
              skill_id: skillId,
              order_index: index,
              is_required: true,
            }))
          : agent.skill_bindings,
      } : agent)
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(hydrateAgentProfile(agentProfiles.find((agent) => agent.id === agentId) || agentProfiles[0])),
    })
  })

  // 智能体列表/详情
  await page.route(/\/api\/v1\/agent(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: MOCK.MOCK_AGENT_PROFILES,
        total: MOCK.MOCK_AGENT_PROFILES.length,
        page: 1,
        page_size: 100,
        has_more: false,
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/(?!agent-runs(?:\/|\?|$)|workflows(?:\/|\?|$)|agent-profiles(?:\/|\?|$)|skills(?:\/|\?|$))[^/?]+(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'agent-e2e-001',
        name: '需求提炼专家智能体',
        description: '专用于分析URS并提取GraphRAG节点',
        skills: ['NLP', 'GraphRAG'],
        status: 'idle',
      }),
    })
  })

  // 智能体运行记录
  await page.route(/\/api\/v1\/agent\/agent-runs(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const agent = findAgentProfile(payload.agent_profile_id || agentProfiles[0].id)
      const workflow = findWorkflow(agent.workflow_definition_id)
      const version = findWorkflowVersion(agent.workflow_definition_id)
      const createdAt = new Date().toISOString()
      const run = {
        id: 'run-new-001',
        tenant_id: 'tenant-e2e-001',
        project_id: payload.project_id || 'project-e2e-001',
        workflow_version_id: version.id,
        agent_profile_id: agent.id,
        run_type: 'agent_profile',
        metadata_json: {
          source: 'agents_page',
          workflow_name: workflow.name,
        },
        input_data: {
          ...(payload.input_data || {}),
          source: 'agents_page',
          agent_profile_id: agent.id,
          agent_name: agent.name,
          document_type: agent.applicable_doc_types?.[0] || agent.agent_type,
          workflow_name: workflow.name,
        },
        status: 'completed',
        started_at: createdAt,
        completed_at: createdAt,
        error_message: null,
        created_at: createdAt,
      }
      agentRuns = [run, ...agentRuns]
      agentEvents = [
        {
          id: 'event-run-new-001',
          agent_run_id: run.id,
          tenant_id: 'tenant-e2e-001',
          event_type: 'agent_profile_run_completed',
          event_data: { source: 'agents_page', agent_profile_id: agent.id },
          created_at: createdAt,
        },
        ...agentEvents,
      ]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: run.id,
          status: run.status,
          message: 'Agent profile run executed',
        }),
      })
      return
    }
    const url = new URL(route.request().url())
    const status = url.searchParams.get('status')
    const runType = url.searchParams.get('run_type')
    const workflowDefinitionId = url.searchParams.get('workflow_definition_id')
    const workflowVersionId = url.searchParams.get('workflow_version_id')
    const agentProfileId = url.searchParams.get('agent_profile_id')
    const search = (url.searchParams.get('search') || '').toLowerCase()
    const workflowDefinitionForRun = (run: any) => {
      const version = workflowVersions.find((item) => item.id === run.workflow_version_id)
      return version?.workflow_definition_id || run.workflow?.workflow_definition_id || null
    }
    const items = agentRuns.filter((run) => {
      const searchable = JSON.stringify({
        id: run.id,
        input_data: run.input_data,
        metadata_json: run.metadata_json,
        error_message: run.error_message,
      }).toLowerCase()
      return (
        (!status || run.status === status) &&
        (!runType || run.run_type === runType || (!run.run_type && runType === 'workflow')) &&
        (!workflowVersionId || run.workflow_version_id === workflowVersionId) &&
        (!workflowDefinitionId || workflowDefinitionForRun(run) === workflowDefinitionId) &&
        (!agentProfileId || run.agent_profile_id === agentProfileId) &&
        (!search || searchable.includes(search))
      )
    })
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items,
        total: items.length,
        page: 1,
        page_size: 10,
        has_more: false,
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/agent-runs\/[^/]+\/tasks(?:\?.*)?$/, async (route) => {
    const runId = route.request().url().match(/\/agent-runs\/([^/]+)\/tasks/)?.[1] || 'run-e2e-001'
    const tasks = agentTasks.filter((task) => task.agent_run_id === runId)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: tasks,
        total: tasks.length,
        page: 1,
        page_size: 100,
        has_more: false,
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/agent-runs\/[^/]+\/events(?:\?.*)?$/, async (route) => {
    const runId = route.request().url().match(/\/agent-runs\/([^/]+)\/events/)?.[1] || 'run-e2e-001'
    const events = agentEvents.filter((event) => event.agent_run_id === runId)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: events,
        total: events.length,
        page: 1,
        page_size: 100,
        has_more: false,
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/agent-runs\/[^/]+\/retry$/, async (route) => {
    const runId = route.request().url().match(/\/agent-runs\/([^/]+)\/retry/)?.[1] || 'run-e2e-failed'
    const originalRun = agentRuns.find((run) => run.id === runId) || agentRuns[0]
    const createdAt = new Date().toISOString()
    const retryRun = {
      ...originalRun,
      id: 'run-retry-001',
      status: 'pending',
      started_at: createdAt,
      completed_at: null,
      error_message: null,
      created_at: createdAt,
      metadata_json: {
        ...(originalRun.metadata_json || {}),
        retry_of: originalRun.id,
      },
      progress_percent: 0,
    }
    agentRuns = [retryRun, ...agentRuns]
    agentEvents = [
      {
        id: 'event-run-retry-001',
        agent_run_id: retryRun.id,
        tenant_id: 'tenant-e2e-001',
        event_type: 'run_retry_queued',
        event_data: { retry_of: originalRun.id },
        created_at: createdAt,
      },
      ...agentEvents,
    ]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_id: retryRun.id,
        status: 'pending',
        message: 'Workflow retry queued successfully',
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/agent-runs\/[^/]+\/cancel$/, async (route) => {
    const runId = route.request().url().match(/\/agent-runs\/([^/]+)\/cancel/)?.[1] || 'run-e2e-running'
    const cancelledAt = new Date().toISOString()
    agentRuns = agentRuns.map((run) => run.id === runId ? {
      ...run,
      status: 'cancelled',
      completed_at: cancelledAt,
      progress_percent: 100,
    } : run)
    agentEvents = [
      {
        id: `event-${runId}-cancelled`,
        agent_run_id: runId,
        tenant_id: 'tenant-e2e-001',
        event_type: 'run_cancelled',
        event_data: { requested_by: 'user-admin-001' },
        created_at: cancelledAt,
      },
      ...agentEvents,
    ]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(agentRuns.find((run) => run.id === runId) || agentRuns[0]),
    })
  })

  await page.route(/\/api\/v1\/agent\/agent-runs\/[^/]+\/control-actions$/, async (route) => {
    const runId = route.request().url().match(/\/agent-runs\/([^/]+)\/control-actions/)?.[1] || 'run-e2e-approval'
    const payload = JSON.parse(route.request().postData() || '{}')
    const action = String(payload.action || 'approve')
    const handledAt = new Date().toISOString()
    const failed = action === 'reject'
    const targetTask = agentTasks.find((task) => task.agent_run_id === runId && (!payload.node_id || task.node_id === payload.node_id))

    agentTasks = agentTasks.map((task) => task.id === targetTask?.id ? {
      ...task,
      status: failed ? 'failed' : 'completed',
      output_data: {
        ...(task.output_data || {}),
        control_action: action,
        node_id: task.node_id,
        comment: payload.comment || null,
        resolved_at: handledAt,
      },
      error_message: failed ? (payload.comment || '人工驳回') : null,
      completed_at: handledAt,
    } : task)

    agentRuns = agentRuns.map((run) => run.id === runId ? {
      ...run,
      status: failed ? 'failed' : 'pending',
      completed_at: failed ? handledAt : null,
      error_message: failed ? (payload.comment || '人工驳回，停止本次编排运行。') : null,
      progress_percent: failed ? 100 : Math.max(Number(run.progress_percent || 0), 60),
      requires_human_action: false,
      can_resume: !failed,
      status_hint: failed ? 'control_rejected' : 'control_resolved',
      metadata_json: {
        ...(run.metadata_json || {}),
        requires_human_action: false,
        can_resume: !failed,
        status_hint: failed ? 'control_rejected' : 'control_resolved',
        last_control_action: {
          action,
          node_id: payload.node_id || targetTask?.node_id || 'approval',
          comment: payload.comment || null,
          resolved_at: handledAt,
        },
      },
      gate_summary: {
        ...(run.gate_summary || {}),
        requires_human_action: false,
        status_hint: failed ? 'control_rejected' : 'control_resolved',
      },
    } : run)

    agentEvents = [
      {
        id: `event-${runId}-control-${action}`,
        agent_run_id: runId,
        tenant_id: 'tenant-e2e-001',
        event_type: `control_${action}`,
        event_data: {
          node_id: payload.node_id || targetTask?.node_id || 'approval',
          status: failed ? 'failed' : 'pending',
        },
        created_at: handledAt,
      },
      ...agentEvents,
    ]

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(agentRuns.find((run) => run.id === runId) || agentRuns[0]),
    })
  })

  await page.route(/\/api\/v1\/agent\/agent-runs\/[^/?]+(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(agentRuns.find((run) => run.id === (route.request().url().match(/\/agent-runs\/([^/?]+)/)?.[1] || 'run-e2e-001')) || agentRuns[0]),
    })
  })

  // 触发运行
  await page.route(/\/api\/v1\/agent\/[^/]+\/run$/, async (route) => {
    const agentId = route.request().url().match(/\/agent\/([^/]+)\/run$/)?.[1] || agentProfiles[0].id
    const agent = findAgentProfile(agentId)
    const workflow = findWorkflow(agent.workflow_definition_id)
    const version = findWorkflowVersion(agent.workflow_definition_id)
    const payload = JSON.parse(route.request().postData() || '{}')
    const createdAt = new Date().toISOString()
    const run = {
      id: 'run-new-001',
      tenant_id: 'tenant-e2e-001',
      project_id: payload.project_id || 'project-e2e-001',
      workflow_version_id: version.id,
      input_data: {
        ...(payload.input_data || {}),
        source: 'agents_page',
        agent_profile_id: agent.id,
        agent_name: agent.name,
        document_type: agent.applicable_doc_types?.[0] || agent.agent_type,
        workflow_name: workflow.name,
      },
      status: 'pending',
      started_at: createdAt,
      completed_at: null,
      error_message: null,
      created_at: createdAt,
    }
    agentRuns = [run, ...agentRuns]
    agentEvents = [
      {
        id: 'event-run-new-001',
        agent_run_id: run.id,
        tenant_id: 'tenant-e2e-001',
        event_type: 'run_queued',
        event_data: { source: 'agents_page', agent_profile_id: agent.id },
        created_at: createdAt,
      },
      ...agentEvents,
    ]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: run.id,
        output: 'Agent 运行已排队，运行记录已写入。',
        artifacts: [],
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/orchestration\/dashboard$/, async (route) => {
    const statusCounts = agentRuns.reduce((counts: Record<string, number>, run) => {
      counts[run.status] = (counts[run.status] || 0) + 1
      return counts
    }, {})
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: new Date().toISOString(),
        readiness_score: 92,
        kpis: {
          active_agents: agentProfiles.filter((agent) => agent.status === 'active').length,
          published_skills: skillCatalog.filter((skill) => skill.status === 'published').length,
          active_workflows: workflows.filter((workflow) => workflow.is_active).length,
          executable_workflows: workflowVersions.filter((version) => version.is_active).length,
          total_runs: agentRuns.length,
          running_runs: (statusCounts.pending || 0) + (statusCounts.running || 0),
          failed_runs: statusCounts.failed || 0,
          recoverable_runs: (statusCounts.failed || 0) + (statusCounts.cancelled || 0),
        },
        run_status_counts: statusCounts,
        workflow_category_counts: workflows.reduce((counts: Record<string, number>, workflow) => {
          counts[workflow.category] = (counts[workflow.category] || 0) + 1
          return counts
        }, {}),
        recent_runs: agentRuns.slice(0, 8),
        recommendations: [
          {
            severity: 'info',
            code: 'ready',
            title: '智能编排基础闭环可用',
            detail: 'Skill、Agent、工作流和运行观测均已具备可用配置。',
            action_label: '运行工作流',
            action_href: '/workflows',
          },
        ],
        template_count: MOCK.MOCK_WORKFLOW_TEMPLATES.length,
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/orchestration\/bootstrap$/, async (route) => {
    const statusCounts = agentRuns.reduce((counts: Record<string, number>, run) => {
      counts[run.status] = (counts[run.status] || 0) + 1
      return counts
    }, {})
    const dashboard = {
      generated_at: new Date().toISOString(),
      readiness_score: 92,
      kpis: {
        active_agents: agentProfiles.filter((agent) => agent.status === 'active').length,
        published_skills: skillCatalog.filter((skill) => skill.status === 'published').length,
        active_workflows: workflows.filter((workflow) => workflow.is_active).length,
        executable_workflows: workflowVersions.filter((version) => version.is_active).length,
        total_runs: agentRuns.length,
        running_runs: (statusCounts.pending || 0) + (statusCounts.running || 0),
        failed_runs: statusCounts.failed || 0,
        recoverable_runs: (statusCounts.failed || 0) + (statusCounts.cancelled || 0),
      },
      run_status_counts: statusCounts,
      workflow_category_counts: workflows.reduce((counts: Record<string, number>, workflow) => {
        counts[workflow.category] = (counts[workflow.category] || 0) + 1
        return counts
      }, {}),
      recent_runs: agentRuns.slice(0, 8),
      recommendations: [
        {
          severity: 'info',
          code: 'ready',
          title: '智能编排基础闭环可用',
          detail: 'Skill、Agent、工作流和运行观测均已具备可用配置。',
          action_label: '运行工作流',
          action_href: '/workflows',
        },
      ],
      template_count: MOCK.MOCK_WORKFLOW_TEMPLATES.length,
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        message: 'Intelligent orchestration defaults initialized',
        initialized: {
          published_skills: dashboard.kpis.published_skills,
          active_agents: dashboard.kpis.active_agents,
          executable_agents: dashboard.kpis.active_agents,
          active_workflows: dashboard.kpis.active_workflows,
          executable_workflows: dashboard.kpis.executable_workflows,
        },
        dashboard,
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/workflows\/templates$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: MOCK.MOCK_WORKFLOW_TEMPLATES,
        total: MOCK.MOCK_WORKFLOW_TEMPLATES.length,
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/workflows\/from-template$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const template = MOCK.MOCK_WORKFLOW_TEMPLATES.find((item) => item.template_id === payload.template_id) || MOCK.MOCK_WORKFLOW_TEMPLATES[0]
    const createdAt = new Date().toISOString()
    const workflow = {
      id: `workflow-from-template-${template.template_id}`,
      name: payload.name || template.display_name,
      description: payload.description || template.description,
      category: template.category,
      version_count: 1,
      graph_data: template.dag_json,
      is_active: true,
      created_at: createdAt,
      updated_at: createdAt,
    }
    const version = {
      id: `wv-from-template-${template.template_id}`,
      workflow_definition_id: workflow.id,
      version: 1,
      dag_json: template.dag_json,
      skill_contracts_json: [],
      tool_contracts_json: [],
      is_active: true,
      created_at: createdAt,
    }
    workflows = [workflow, ...workflows.filter((item) => item.id !== workflow.id)]
    workflowVersions = [version, ...workflowVersions.filter((item) => item.id !== version.id)]
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(workflow),
    })
  })

  // 工作流列表与创建/更新
  await page.route(/\/api\/v1\/agent\/workflows(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          ...workflows[0],
          name: payload.name || workflows[0].name,
          description: payload.description || workflows[0].description,
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: workflows,
          total: workflows.length,
        }),
      })
    }
  })

  await page.route(/\/api\/v1\/agent\/workflows\/execute$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const createdAt = new Date().toISOString()
    const run = {
      id: 'run-e2e-new',
      tenant_id: 'tenant-e2e-001',
      project_id: payload.project_id || 'project-e2e-001',
      workflow_version_id: payload.version_id || null,
      agent_profile_id: null,
      run_type: 'workflow',
      input_data: payload.input_data || {},
      metadata_json: { source: 'workflows_page' },
      progress_percent: 0,
      status: 'pending',
      started_at: null,
      completed_at: null,
      error_message: null,
      created_at: createdAt,
    }
    agentRuns = [run, ...agentRuns]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_id: run.id,
        status: 'pending',
        message: 'Workflow execution queued successfully',
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/workflows\/preview$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const nodes = payload.dag_json?.nodes || []
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        valid: nodes.length > 0,
        issues: nodes.length > 0 ? [] : [{ severity: 'error', code: 'empty_dag', node_id: null, message: 'DAG must contain at least one node' }],
        execution_order: nodes.map((node: any) => String(node.id)),
        parallel_groups: nodes
          .filter((node: any) => node.type === 'parallel_group')
          .map((node: any) => ({
            group_id: node.id,
            node_ids: nodes.filter((item: any) => (item.depends_on || []).includes(node.id)).map((item: any) => item.id),
            label: node.data?.label || node.id,
          })),
        approval_gates: nodes
          .filter((node: any) => node.type === 'human_approval')
          .map((node: any) => ({
            node_id: node.id,
            label: node.data?.label || node.id,
            approver_role: node.config?.approver_role || '项目负责人',
            required: node.config?.required ?? true,
          })),
        condition_paths: nodes
          .filter((node: any) => node.type === 'condition')
          .map((node: any) => ({
            node_id: node.id,
            expression: node.config?.expression || '',
            true_path: [],
            false_path: [],
          })),
        estimated_steps: nodes.length,
        blocking_issues: nodes.length > 0 ? [] : [{ severity: 'error', code: 'empty_dag', node_id: null, message: 'DAG must contain at least one node' }],
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/workflows\/[^/]+\/production-preflight(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url())
    const workflowId = url.pathname.match(/\/workflows\/([^/]+)\/production-preflight/)?.[1] || workflows[0].id
    const workflow = findWorkflow(workflowId)
    const version = findWorkflowVersion(workflow.id)
    const nodes = version?.dag_json?.nodes || []
    const recentRuns = agentRuns
      .filter((run) => run.workflow_version_id === version?.id)
      .slice(0, 5)
    const hasProject = Boolean(url.searchParams.get('project_id'))
    const blockingIssues = nodes.length > 0 ? [] : [{ severity: 'error', code: 'empty_dag', node_id: null, message: 'DAG must contain at least one node' }]
    const checks = [
      {
        code: 'workflow_enabled',
        severity: 'info',
        title: '工作流已启用',
        detail: '工作流定义处于启用状态，可以进入版本和 DAG 检查。',
        status: workflow.is_active ? 'passed' : 'failed',
      },
      {
        code: 'active_version',
        severity: 'info',
        title: '活动版本可用',
        detail: `当前将执行 v${version?.version || 1}。`,
        status: version ? 'passed' : 'failed',
      },
      {
        code: 'dag_valid',
        severity: 'info',
        title: 'DAG 校验通过',
        detail: `预计执行 ${nodes.length} 个节点。`,
        status: blockingIssues.length ? 'failed' : 'passed',
      },
      {
        code: 'project_context',
        severity: hasProject ? 'info' : 'high',
        title: hasProject ? '项目上下文已绑定' : '缺少项目上下文',
        detail: hasProject ? '运行将带入当前项目上下文。' : '生产执行需要绑定项目。',
        status: hasProject ? 'passed' : 'failed',
      },
      {
        code: 'human_approval_gates',
        severity: 'medium',
        title: '包含人工审批节点',
        detail: '检测到审批门禁，运行中可能需要人工处理。',
        status: 'warning',
        action_label: '查看运行中心',
        action_href: '/agent-ops',
      },
    ]
    const blockers = checks.filter((check) => check.status === 'failed').map((check) => check.title)
    const warnings = checks.filter((check) => check.status === 'warning').map((check) => check.title)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        workflow_id: workflow.id,
        workflow_name: workflow.name,
        project_id: url.searchParams.get('project_id'),
        active_version_id: version?.id || null,
        release_gate: {
          status: blockers.length ? 'blocked' : warnings.length ? 'attention' : 'passed',
          label: blockers.length ? '不可执行' : warnings.length ? '可执行但需关注' : '可以执行',
          summary: blockers.length ? `${blockers.length} 个阻断项需要先处理。` : '无阻断项，仍有风险提示。',
          blockers,
          warnings,
        },
        preview: {
          valid: blockingIssues.length === 0,
          issues: blockingIssues,
          execution_order: nodes.map((node: any) => String(node.id)),
          parallel_groups: [],
          approval_gates: nodes
            .filter((node: any) => node.type === 'human_approval')
            .map((node: any) => ({
              node_id: node.id,
              label: node.data?.label || node.id,
              approver_role: node.config?.approver_role || '项目负责人',
              required: node.config?.required ?? true,
            })),
          condition_paths: [],
          estimated_steps: nodes.length,
          blocking_issues: blockingIssues,
        },
        checks,
        recent_runs: recentRuns,
        next_actions: checks.filter((check) => check.status !== 'passed'),
      }),
    })
  })

  await page.route(/\/api\/v1\/agent\/workflows\/validate$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const nodes = payload.dag_json?.nodes || []
    const issues = nodes.flatMap((node: any) => {
      if (node.type === 'condition' && !node.config?.expression) {
        return [{ severity: 'error', code: 'condition_missing_expression', node_id: node.id, message: 'Condition node must define expression' }]
      }
      if (node.type === 'human_approval' && !node.config?.approver_role) {
        return [{ severity: 'warning', code: 'approval_missing_role', node_id: node.id, message: 'Approval node should define approver role' }]
      }
      return []
    })
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        valid: nodes.length > 0 && !issues.some((issue: any) => issue.severity === 'error'),
        issues: nodes.length > 0 ? issues : [{ severity: 'error', code: 'empty_dag', node_id: null, message: 'DAG must contain at least one node' }],
        execution_order: nodes.map((node: any) => String(node.id)),
      }),
    })
  })

  // 特定工作流详情与更新
  await page.route(/\/api\/v1\/agent\/workflows\/(?!execute$|validate$|preview$|templates$|from-template$)[^/?]+(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    const workflowId = route.request().url().match(/\/workflows\/([^/?]+)/)?.[1] || workflows[0].id
    const workflow = workflows.find((item) => item.id === workflowId) || workflows[0]
    if (method === 'PATCH') {
      const payload = JSON.parse(route.request().postData() || '{}')
      workflows = workflows.map((item) => item.id === workflowId ? { ...item, ...payload } : item)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...workflow,
          ...payload,
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(workflow),
      })
    }
  })

  // 工作流版本管理与创建版本
  await page.route(/\/api\/v1\/agent\/workflows\/[^/]+\/versions(?:\?.*)?$/, async (route) => {
    const workflowId = route.request().url().match(/\/workflows\/([^/]+)\/versions/)?.[1] || 'workflow-e2e-001'
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const version = {
        id: `wv-${Date.now()}`,
        workflow_definition_id: workflowId,
        version: workflowVersions.filter((item) => item.workflow_definition_id === workflowId).length + 1,
        dag_json: payload.dag_json || {},
        skill_contracts_json: payload.skill_contracts || [],
        tool_contracts_json: payload.tool_contracts || [],
        is_active: true,
        created_at: new Date().toISOString(),
      }
      workflowVersions = [version, ...workflowVersions.map((item) => (
        item.workflow_definition_id === workflowId ? { ...item, is_active: false } : item
      ))]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(version),
      })
    } else {
      const versions = workflowVersions.filter((version) => version.workflow_definition_id === workflowId)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: versions,
          total: versions.length,
        }),
      })
    }
  })

  await page.route(/\/api\/v1\/agent\/workflows\/[^/]+\/versions\/[^/]+\/activate$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        version_id: 'wv-e2e-001',
        workflow_definition_id: 'workflow-e2e-001',
        is_active: true,
        message: 'Version activated successfully',
      }),
    })
  })


  // ==================== 9. CHANGE MANAGEMENT ====================

  // 变更列表与创建
  await page.route(/\/api\/v1\/change(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK.MOCK_CHANGES[0],
          name: payload.name || MOCK.MOCK_CHANGES[0].name,
          description: payload.description || MOCK.MOCK_CHANGES[0].description,
        }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: MOCK.MOCK_CHANGE_BOARD_CHANGES,
          total: MOCK.MOCK_CHANGE_BOARD_CHANGES.length,
          page: 1,
          page_size: 10,
          has_more: false,
        }),
      })
    }
  })

  // 特定变更请求详情
  await page.route(/\/api\/v1\/change\/[^/?]+(?:\?.*)?$/, async (route) => {
    const changeId = route.request().url().match(/\/change\/([^/?]+)/)?.[1]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_CHANGE_BOARD_CHANGES.find((change) => change.id === changeId) || MOCK.MOCK_CHANGE_BOARD_CHANGES[0]),
    })
  })

  // 变更交互 (submit/approve/reject/apply/cancel)
  await page.route(/\/api\/v1\/change\/[^/]+\/(submit|approve|reject|apply|cancel)$/, async (route) => {
    const url = route.request().url()
    const action = url.split('/').pop() || 'submit'
    let status = 'draft'
    if (action === 'submit') status = 'pending'
    else if (action === 'approve') status = 'approved'
    else if (action === 'reject') status = 'rejected'
    else if (action === 'apply') status = 'applied'
    else if (action === 'cancel') status = 'cancelled'

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...(MOCK.MOCK_CHANGE_BOARD_CHANGES.find((change) => change.id === route.request().url().match(/\/change\/([^/]+)\//)?.[1]) || MOCK.MOCK_CHANGE_BOARD_CHANGES[0]),
        status,
      }),
    })
  })

  // 持久化影响分析与同步提案
  await page.route(/\/api\/v1\/change\/impact-analyses\/[^/?]+(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(traceabilityImpactAnalysis),
    })
  })

  await page.route(/\/api\/v1\/change\/sync-proposals\/[^/]+\/(apply|reject)$/, async (route) => {
    const action = route.request().url().endsWith('/apply') ? 'applied' : 'rejected'
    const proposalId = route.request().url().match(/\/sync-proposals\/([^/]+)\//)?.[1]
    const payload = JSON.parse(route.request().postData() || '{}')
    const baseProposal = traceabilityImpactAnalysis.proposals.find((item: any) => item.id === proposalId) || traceabilityImpactAnalysis.proposals[0]
    const proposal = {
      ...baseProposal,
      status: action,
      result_document_version: action === 'applied' ? 2 : null,
      decided_by: 'user-admin-001',
      decided_at: new Date().toISOString(),
      decision_note: payload.decision_note || null,
    }
    traceabilityImpactAnalysis = {
      ...traceabilityImpactAnalysis,
      status: 'resolved',
      proposals: traceabilityImpactAnalysis.proposals.map((item: any) => item.id === proposal.id ? proposal : item),
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(proposal),
    })
  })

  // 变更追溯审计指挥台
  await page.route('**/api/v1/change/command-center*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_CHANGE_AUDIT_COMMAND_CENTER),
    })
  })

  // 追溯覆盖驾驶舱
  await page.route('**/api/v1/change/traceability/coverage*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK.MOCK_TRACEABILITY_BOARD_COVERAGE),
    })
  })

  // 追溯矩阵
  await page.route('**/api/v1/change/traceability/matrix*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: 'trace-row-1',
            document_id: 'doc-e2e-001',
            entry_id: 'entry-e2e-001',
            trace_status: 'aligned',
            updated_at: '2026-05-21T09:00:00Z',
            document: MOCK.MOCK_DOCUMENTS[0],
            entry: MOCK.MOCK_KNOWLEDGE_ENTRIES[0],
          }
        ],
        total: 1,
      }),
    })
  })


  // ==================== 10. EXPORTS ====================

  await page.route(/\/api\/v1\/exports\/readiness(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: 'project-e2e-001',
        total_documents: 6,
        exportable_documents: 4,
        blocked_documents: 2,
        readiness_score: 76,
        can_export_production: false,
        missing_required_types: ['test_case'],
        required_types: [
          { doc_type: 'urs', label: 'URS', ready_count: 1, blocked_count: 0, status: 'ready' },
          { doc_type: 'brd', label: 'BRD', ready_count: 1, blocked_count: 0, status: 'ready' },
          { doc_type: 'prd', label: 'PRD', ready_count: 1, blocked_count: 0, status: 'ready' },
          { doc_type: 'detailed_design', label: '设计说明', ready_count: 1, blocked_count: 0, status: 'ready' },
          { doc_type: 'test_case', label: '测试用例', ready_count: 0, blocked_count: 1, status: 'blocked' },
        ],
        blockers: [
          {
            document_id: 'doc-e2e-006',
            title: '验收报告',
            doc_type: 'acceptance_report',
            status: 'placeholder',
            reason: '文档仍包含占位内容',
            recommended_action: '回到项目文档工作台补齐内容或重新生成后再发布。',
          },
        ],
        recommended_actions: ['补齐核心交付文档类型：测试用例。', '处理占位、空内容和未发布文档后再生成正式交付包。'],
      }),
    })
  })

  await page.route(/\/api\/v1\/exports\/release-evidence(?:\?.*)?$/, async (route) => {
    const completedJobs = exportJobs.filter((job: any) => job.status === 'completed')
    const failedJobs = exportJobs.filter((job: any) => job.status === 'failed')
    const artifacts = completedJobs.flatMap((job: any) => job.artifacts || [])
    const coveredFormats = Array.from(new Set(artifacts.map((artifact: any) => {
      const filename = String(artifact.filename || '').toLowerCase()
      if (filename.endsWith('.docx')) return 'Word'
      if (filename.endsWith('.md')) return 'Markdown'
      if (filename.endsWith('.pptx')) return 'PPTX'
      return 'File'
    }).filter((format: string) => ['Word', 'Markdown', 'PPTX'].includes(format)))).sort()
    const missingFormats = ['Markdown', 'PPTX', 'Word'].filter((format) => !coveredFormats.includes(format))
    const latestJob = completedJobs.find((job: any) => job.export_type === 'project_package') || completedJobs[0] || null
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: 'project-e2e-001',
        release_gate: {
          status: 'blocked',
          label: '发布阻断',
          summary: '导出发布证据仍存在必须处理的阻断项。',
          blockers: ['核心交付清单未就绪', '存在失败导出任务'],
          warnings: missingFormats.length ? ['交付格式覆盖不完整'] : [],
        },
        readiness: {
          project_id: 'project-e2e-001',
          total_documents: 6,
          exportable_documents: 4,
          blocked_documents: 2,
          readiness_score: 76,
          can_export_production: false,
          missing_required_types: ['test_case'],
          required_types: [
            { doc_type: 'urs', label: 'URS', ready_count: 1, blocked_count: 0, status: 'ready' },
            { doc_type: 'brd', label: 'BRD', ready_count: 1, blocked_count: 0, status: 'ready' },
            { doc_type: 'prd', label: 'PRD', ready_count: 1, blocked_count: 0, status: 'ready' },
            { doc_type: 'detailed_design', label: '设计说明', ready_count: 1, blocked_count: 0, status: 'ready' },
            { doc_type: 'test_case', label: '测试用例', ready_count: 0, blocked_count: 1, status: 'blocked' },
          ],
          blockers: [
            {
              document_id: 'doc-e2e-006',
              title: '验收报告',
              doc_type: 'acceptance_report',
              status: 'placeholder',
              reason: '文档仍包含占位内容',
              recommended_action: '回到项目文档工作台补齐内容或重新生成后再发布。',
            },
          ],
          recommended_actions: ['补齐核心交付文档类型：测试用例。', '处理占位、空内容和未发布文档后再生成正式交付包。'],
        },
        summary: {
          total_jobs: exportJobs.length,
          completed_jobs: completedJobs.length,
          failed_jobs: failedJobs.length,
          artifact_count: artifacts.length,
          covered_formats: coveredFormats,
          missing_formats: missingFormats,
          production_package_jobs: completedJobs.filter((job: any) => job.export_type === 'project_package').length,
          latest_completed_at: latestJob?.completed_at || null,
        },
        latest_job: latestJob,
        recent_artifacts: artifacts.slice(0, 6),
        risk_items: [
          {
            code: 'export_readiness_blocked',
            severity: 'critical',
            title: '核心交付清单未就绪',
            detail: '仍有缺失、占位、空内容或未批准发布的核心文档。',
            count: 3,
            href: '/documents',
          },
          {
            code: 'failed_exports',
            severity: 'high',
            title: '存在失败导出任务',
            detail: '导出失败需要确认变量、模板或产物生成错误。',
            count: failedJobs.length,
            href: '/exports',
          },
        ],
        priority_actions: [
          {
            code: 'fix_delivery_documents',
            title: '补齐核心交付文档',
            description: '处理缺失文档、占位内容、空正文和未批准发布状态后再生成正式交付包。',
            href: '/documents',
            priority: 'critical',
          },
          {
            code: 'triage_failed_exports',
            title: '处置失败导出任务',
            description: '查看失败原因，补齐模板变量或格式配置后重新导出。',
            href: '/exports',
            priority: 'high',
          },
        ],
      }),
    })
  })

  await page.route(/\/api\/v1\/exports\/project-package$/, async (route) => {
    const payload = JSON.parse(route.request().postData() || '{}')
    const jobId = `package-job-${Date.now()}`
    const requestedFormats = Array.isArray(payload.formats) && payload.formats.length ? payload.formats : ['markdown']
    const artifactByFormat: Record<string, any> = {
      word: {
        id: `${jobId}-docx`,
        job_id: jobId,
        tenant_id: 'tenant-e2e-001',
        filename: 'customer-review.docx',
        content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        file_size: 8192,
        storage_path: 'tenant-e2e-001/project-e2e-001/customer-review.docx',
        file_hash: 'e'.repeat(64),
        created_at: new Date().toISOString(),
      },
      markdown: {
        id: `${jobId}-md`,
        job_id: jobId,
        tenant_id: 'tenant-e2e-001',
        filename: 'customer-review.md',
        content_type: 'text/markdown',
        file_size: 4096,
        storage_path: 'tenant-e2e-001/project-e2e-001/customer-review.md',
        file_hash: 'f'.repeat(64),
        created_at: new Date().toISOString(),
      },
      pptx: {
        id: `${jobId}-pptx`,
        job_id: jobId,
        tenant_id: 'tenant-e2e-001',
        filename: 'customer-review.pptx',
        content_type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        file_size: 12288,
        storage_path: 'tenant-e2e-001/project-e2e-001/customer-review.pptx',
        file_hash: 'a'.repeat(64),
        created_at: new Date().toISOString(),
      },
    }
    exportJobs = [
      {
        id: jobId,
        tenant_id: 'tenant-e2e-001',
        project_id: payload.project_id || 'project-e2e-001',
        document_id: null,
        template_id: null,
        export_type: 'project_package',
        title: payload.title || '交付导出包',
        status: 'completed',
        output_path: 'tenant-e2e-001/project-e2e-001/customer-review.zip',
        file_hash: 'd'.repeat(64),
        error_message: null,
        created_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        artifacts: requestedFormats.map((format: string) => artifactByFormat[format]).filter(Boolean),
      },
      ...exportJobs,
    ]
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: jobId,
        status: 'completed',
        message: 'Mock project package export job created',
      }),
    })
  })

  await page.route(/\/api\/v1\/exports\/(?:word|markdown|pptx)$/, async (route) => {
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: `job-${Date.now()}`,
        status: 'pending',
        message: 'Mock export job created',
      }),
    })
  })

  await page.route(/\/api\/v1\/exports(?:\?.*)?$/, async (route) => {
    const method = route.request().method()
    if (method === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: `export-${Date.now()}`,
          projectId: payload.projectId || 'project-e2e-001',
          format: payload.format || 'pdf',
          status: 'pending',
          createdAt: new Date().toISOString(),
        }),
      })
    } else if (method === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(exportJobs),
      })
    }
  })

  await page.route(/\/api\/v1\/exports\/[^/]+\/download$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        url: 'https://mock.storage.url/export-e2e-001.pdf',
      }),
    })
  })

  await page.route(/\/api\/v1\/exports\/artifacts\/[^/]+\/download$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/markdown',
      body: '# Mock export artifact\n\nDownload content.',
    })
  })


  // ==================== 11. COLLABORATION (COMMENTS & VERSIONS) ====================

  let collaborationWorkItems = [
    {
      id: 'work-item-review',
      tenant_id: 'tenant-e2e-001',
      project_id: 'project-e2e-001',
      document_id: 'doc-prd-001',
      comment_id: null,
      assigned_to: 'user-admin-001',
      created_by: 'user-admin-001',
      work_type: 'review',
      status: 'open',
      priority: 'high',
      title: '评审履约监控 PRD',
      description: '完成验收前评审。',
      due_at: '2026-06-08T10:00:00Z',
      completed_at: null,
      source_key: 'review:doc-prd-001',
      metadata_json: {},
      created_at: '2026-06-07T08:00:00Z',
      updated_at: '2026-06-07T08:00:00Z',
    },
    {
      id: 'work-item-unassigned',
      tenant_id: 'tenant-e2e-001',
      project_id: 'project-e2e-001',
      document_id: 'doc-brd-001',
      comment_id: null,
      assigned_to: null,
      created_by: 'user-admin-001',
      work_type: 'manual',
      status: 'open',
      priority: 'medium',
      title: '补齐业务验收证据',
      description: '',
      due_at: null,
      completed_at: null,
      source_key: null,
      metadata_json: {},
      created_at: '2026-06-07T08:30:00Z',
      updated_at: '2026-06-07T08:30:00Z',
    },
  ]

  let collaborationHub = {
    members: [
      {
        id: 'collab-member-pm',
        name: '周敏',
        email: 'pm@example.com',
        role: '项目经理',
        status: 'online',
        pending_count: 2,
        current_focus: '验收决策会签',
      },
      {
        id: 'collab-member-business',
        name: '林岚',
        email: 'business@example.com',
        role: '业务顾问',
        status: 'pending',
        pending_count: 4,
        current_focus: 'BRD 主流程评审',
      },
      {
        id: 'collab-member-tech',
        name: '陈启',
        email: 'tech@example.com',
        role: '技术顾问',
        status: 'online',
        pending_count: 1,
        current_focus: 'PRD 接口约束评审',
      },
      {
        id: 'collab-member-customer',
        name: '王珊',
        email: 'customer@example.com',
        role: '客户评审人',
        status: 'pending',
        pending_count: 3,
        current_focus: '验收报告签署',
      },
    ],
    review_queue: [
      {
        id: 'review-brd-001',
        document_id: 'doc-brd-001',
        project_id: 'project-e2e-001',
        title: '仓储升级 BRD 评审',
        document_type: 'BRD',
        owner: '林岚',
        role: '业务顾问',
        status: 'PASSED_WITH_FOLLOW_UPS',
        priority: 'high',
        pending_comments: 3,
        snapshot_count: 2,
        baseline_count: 1,
        updated_at: '2026-05-31T09:20:00Z',
        summary: '业务流程已通过，仍需补齐异常订单的人工兜底说明。',
        acceptance_decision: '带跟进项通过',
        action_href: '/projects/project-e2e-001/documents/doc-brd-001',
      },
      {
        id: 'review-prd-001',
        document_id: 'doc-prd-001',
        project_id: 'project-e2e-001',
        title: '履约监控 PRD 评审',
        document_type: 'PRD',
        owner: '陈启',
        role: '技术顾问',
        status: 'BLOCKED',
        priority: 'critical',
        pending_comments: 6,
        snapshot_count: 1,
        baseline_count: 0,
        updated_at: '2026-05-31T08:45:00Z',
        summary: '接口超时策略和追溯字段未确认，暂不能进入验收。',
        acceptance_decision: '退回修订',
        action_href: '/projects/project-e2e-001/documents/doc-prd-001',
      },
      {
        id: 'review-acceptance-001',
        document_id: 'doc-acceptance-001',
        project_id: 'project-e2e-001',
        title: '一期验收报告评审',
        document_type: '验收报告',
        owner: '王珊',
        role: '客户评审人',
        status: 'PASSED',
        priority: 'medium',
        pending_comments: 1,
        snapshot_count: 3,
        baseline_count: 1,
        updated_at: '2026-05-31T07:30:00Z',
        summary: '验收证据完整，遗留问题已登记到跟进清单。',
        acceptance_decision: '通过验收',
        action_href: '/projects/project-e2e-001/documents/doc-acceptance-001',
      },
    ],
    comment_todos: [
      {
        id: 'todo-001',
        document_id: 'doc-prd-001',
        document_title: '履约监控 PRD 评审',
        assignee: '陈启',
        count: 6,
        due: '今天 18:00',
        action_href: '/projects/project-e2e-001/documents/doc-prd-001',
      },
      {
        id: 'todo-002',
        document_id: 'doc-brd-001',
        document_title: '仓储升级 BRD 评审',
        assignee: '林岚',
        count: 3,
        due: '明天 12:00',
        action_href: '/projects/project-e2e-001/documents/doc-brd-001',
      },
    ],
    recent_activities: [
      {
        id: 'activity-001',
        actor: '周敏',
        action: '发起验收决策会签',
        target: '一期验收报告评审',
        created_at: '2026-05-31T09:40:00Z',
      },
      {
        id: 'activity-002',
        actor: '陈启',
        action: '退回接口超时策略',
        target: '履约监控 PRD 评审',
        created_at: '2026-05-31T09:05:00Z',
      },
    ],
    acceptance_decisions: [
      { id: 'decision-passed', label: '通过验收', status: 'PASSED', count: 1 },
      { id: 'decision-blocked', label: '退回修订', status: 'BLOCKED', count: 1 },
      { id: 'decision-followups', label: '带跟进项通过', status: 'PASSED_WITH_FOLLOW_UPS', count: 1 },
    ],
  }

  await page.route(/\/api\/v1\/collaboration\/acceptance-command-center$/, async (route) => {
    const openWorkItems = collaborationWorkItems.filter((item) => item.status !== 'done' && item.status !== 'cancelled')
    const unassignedWorkItems = openWorkItems.filter((item) => !item.assigned_to)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        release_gate: {
          status: 'blocked',
          label: '验收阻断',
          summary: '协同验收仍存在必须关闭的评审、评论或工作项阻断。',
          blockers: ['评论待办未关闭', '存在退回修订评审'],
          warnings: ['存在带跟进项通过的评审', '协同工作项待领取'],
        },
        summary: {
          total_reviews: collaborationHub.review_queue.length,
          passed_reviews: collaborationHub.review_queue.filter((item: any) => item.status === 'PASSED').length,
          blocked_reviews: collaborationHub.review_queue.filter((item: any) => item.status === 'BLOCKED').length,
          follow_up_reviews: collaborationHub.review_queue.filter((item: any) => item.status === 'PASSED_WITH_FOLLOW_UPS').length,
          pending_comments: collaborationHub.review_queue.reduce((total: number, item: any) => total + item.pending_comments, 0),
          open_work_items: openWorkItems.length,
          overdue_work_items: 0,
          unassigned_work_items: unassignedWorkItems.length,
          active_members: collaborationHub.members.filter((item: any) => item.status === 'online' || item.status === 'pending').length,
        },
        risk_items: [
          {
            code: 'blocked_reviews',
            severity: 'critical',
            title: '退回修订评审',
            detail: '存在不能进入发布验收的文档评审。',
            count: 1,
            href: '/collaboration',
          },
          {
            code: 'pending_comments',
            severity: 'high',
            title: '评论待办未关闭',
            detail: '仍有评审评论需要责任人确认和关闭。',
            count: 10,
            href: '/collaboration',
          },
          {
            code: 'unassigned_work_items',
            severity: 'medium',
            title: '协同工作项待领取',
            detail: '存在未分配责任人的开放协同工作项。',
            count: unassignedWorkItems.length,
            href: '/collaboration',
          },
        ],
        priority_actions: [
          {
            code: 'close_review_blockers',
            title: '关闭评审与评论阻断',
            description: '优先处理退回修订、未读评论和评论关闭责任。',
            href: '/collaboration',
            priority: 'critical',
          },
          {
            code: 'assign_work_items',
            title: '领取待办工作项',
            description: '将未分配事项落实到责任人。',
            href: '/collaboration',
            priority: 'medium',
          },
        ],
        review_queue: collaborationHub.review_queue,
        comment_todos: collaborationHub.comment_todos,
        acceptance_decisions: collaborationHub.acceptance_decisions,
      }),
    })
  })

  await page.route(/\/api\/v1\/collaboration\/review-hub$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(collaborationHub),
    })
  })

  await page.route(/\/api\/v1\/collaboration\/review-items\/[^/]+\/(assign-me|mark-read|pass-acceptance|return-revision)$/, async (route) => {
    const url = route.request().url()
    const match = url.match(/\/review-items\/([^/]+)\/([^/]+)$/)
    const reviewId = match?.[1] || ''
    const action = match?.[2] || ''
    const updatedAt = new Date().toISOString()

    collaborationHub = {
      ...collaborationHub,
      review_queue: collaborationHub.review_queue.map((item: any) => {
        if (item.id !== reviewId) return item

        if (action === 'assign-me') {
          return { ...item, owner: '我', updated_at: updatedAt }
        }

        if (action === 'mark-read') {
          return { ...item, pending_comments: 0, updated_at: updatedAt }
        }

        if (action === 'pass-acceptance') {
          return { ...item, status: 'PASSED', acceptance_decision: '通过验收', updated_at: updatedAt }
        }

        if (action === 'return-revision') {
          return { ...item, status: 'BLOCKED', acceptance_decision: '退回修订', updated_at: updatedAt }
        }

        return item
      }),
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(collaborationHub.review_queue.find((item: any) => item.id === reviewId)),
    })
  })

  await page.route(/\/api\/v1\/collaboration\/work-items(?:\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const created = {
        id: `work-item-created-${collaborationWorkItems.length + 1}`,
        tenant_id: 'tenant-e2e-001',
        document_id: null,
        comment_id: null,
        assigned_to: null,
        created_by: 'user-admin-001',
        description: '',
        work_type: 'manual',
        status: 'open',
        due_at: null,
        completed_at: null,
        source_key: null,
        metadata_json: {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ...payload,
      }
      collaborationWorkItems = [created, ...collaborationWorkItems]
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(created) })
      return
    }

    const url = new URL(route.request().url())
    const assignment = url.searchParams.get('assignment')
    const status = url.searchParams.get('status')
    const search = (url.searchParams.get('search') || '').toLowerCase()
    const filtered = collaborationWorkItems.filter((item) => {
      if (assignment === 'mine' && item.assigned_to !== 'user-admin-001') return false
      if (assignment === 'unassigned' && item.assigned_to) return false
      if (status && item.status !== status) return false
      if (search && !`${item.title} ${item.description}`.toLowerCase().includes(search)) return false
      return true
    })
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: filtered,
        total: filtered.length,
        page: 1,
        page_size: 100,
        has_more: false,
        mine_count: collaborationWorkItems.filter((item) => item.assigned_to === 'user-admin-001' && item.status !== 'done').length,
        unassigned_count: collaborationWorkItems.filter((item) => !item.assigned_to && item.status !== 'done').length,
        overdue_count: 0,
        status_counts: Object.fromEntries(['open', 'in_progress', 'blocked', 'done', 'cancelled'].map((value) => [
          value,
          collaborationWorkItems.filter((item) => item.status === value).length,
        ])),
      }),
    })
  })

  await page.route(/\/api\/v1\/collaboration\/work-items\/[^/]+\/(claim|complete|reopen)$/, async (route) => {
    const match = route.request().url().match(/\/work-items\/([^/]+)\/(claim|complete|reopen)$/)
    const workItemId = match?.[1]
    const action = match?.[2]
    collaborationWorkItems = collaborationWorkItems.map((item) => {
      if (item.id !== workItemId) return item
      if (action === 'claim') return { ...item, assigned_to: 'user-admin-001', status: 'in_progress' }
      if (action === 'complete') return { ...item, status: 'done', completed_at: new Date().toISOString() }
      return { ...item, status: 'open', completed_at: null }
    })
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(collaborationWorkItems.find((item) => item.id === workItemId)),
    })
  })

  await page.route(/\/api\/v1\/collaboration\/documents\/[^/]+\/comments$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const parent = comments.find((comment) => comment.id === payload.parent_comment_id)
      const createdComment = {
        id: payload.parent_comment_id ? 'comment-reply-created' : 'comment-created',
        documentId: 'doc-e2e-001',
        authorId: 'user-admin-001',
        content: payload.content || '',
        anchor: payload.anchor || parent?.anchor,
        parentCommentId: payload.parent_comment_id || null,
        resolved: false,
        createdAt: new Date().toISOString(),
      }
      comments = [createdComment, ...comments]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(createdComment),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(comments),
      })
    }
  })

  await page.route(/\/api\/v1\/collaboration\/comments\/[^/]+\/resolve$/, async (route) => {
    const commentId = route.request().url().split('/').slice(-2)[0]
    comments = comments.map((comment) =>
      comment.id === commentId || comment.parentCommentId === commentId
        ? { ...comment, resolved: true, updatedAt: new Date().toISOString() }
        : comment
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(comments.find((comment) => comment.id === commentId) || { success: true }),
    })
  })

  await page.route(/\/api\/v1\/documents\/[^/]+\/versions$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const docId = route.request().url().split('/').slice(-2)[0] || 'doc-e2e-001'
      const updatedAt = new Date().toISOString()
      const versionNumber = Math.max(...versions.map((version) => version.versionNumber || 1), 1) + 1
      const createdVersion = {
        id: 'version-created',
        documentId: docId,
        versionNumber,
        description: payload.changes_summary || 'Manual save',
        content: payload.content || '',
        createdBy: 'user-admin-001',
        createdAt: updatedAt,
      }
      versions = [createdVersion, ...versions]
      documents = documents.map((document) =>
        document.id === docId
          ? {
              ...document,
              content: payload.content || document.content,
              version: versionNumber,
              updatedAt,
              updated_at: updatedAt,
            }
          : document
      )
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(createdVersion),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: versions,
        }),
      })
    }
  })

  await page.route(/\/api\/v1\/documents\/[^/]+\/baselines$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const docId = route.request().url().split('/').slice(-2)[0] || 'doc-e2e-001'
      const createdBaseline = {
        id: 'baseline-created',
        documentId: docId,
        versionId: payload.version_id,
        name: payload.baseline_name,
        reason: payload.baseline_reason || '',
        approvedBy: 'user-admin-001',
        approvedAt: new Date().toISOString(),
        createdAt: new Date().toISOString(),
      }
      baselines = [createdBaseline, ...baselines]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(createdBaseline),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: baselines,
          total: baselines.length,
          page: 1,
          page_size: 10,
          has_more: false,
        }),
      })
    }
  })

  await page.route(/\/api\/v1\/documents\/[^/]+\/baselines\/[^/]+\/rollback$/, async (route) => {
    const docId = route.request().url().split('/').slice(-4)[0] || 'doc-e2e-001'
    const updatedAt = new Date().toISOString()
    documents = documents.map((document) =>
      document.id === docId
        ? {
            ...document,
            content: '# User Requirements\n\nBaseline restored content.',
            updatedAt,
            updated_at: updatedAt,
          }
        : document
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(findDocument(docId)),
    })
  })

  await page.route(/\/api\/v1\/collaboration\/documents\/[^/]+\/snapshots$/, async (route) => {
    if (route.request().method() === 'POST') {
      const payload = JSON.parse(route.request().postData() || '{}')
      const docId = route.request().url().split('/').slice(-2)[0] || 'doc-e2e-001'
      const document = findDocument(docId)
      const createdSnapshot = {
        id: 'snapshot-created',
        documentId: docId,
        userId: 'user-admin-001',
        snapshotData: {
          title: payload.title || document.name,
          content: payload.content ?? document.content,
          status: document.status,
        },
        snapshotType: payload.snapshot_type || 'manual',
        version: document.version || 1,
        createdAt: new Date().toISOString(),
      }
      snapshots = [createdSnapshot, ...snapshots]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(createdSnapshot),
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(snapshots),
      })
    }
  })

  await page.route(/\/api\/v1\/collaboration\/snapshots\/[^/]+\/restore$/, async (route) => {
    const snapshotId = route.request().url().split('/').slice(-2)[0]
    const snapshot = snapshots.find((item) => item.id === snapshotId) || snapshots[0]
    const docId = snapshot.documentId
    const updatedAt = new Date().toISOString()
    documents = documents.map((document) =>
      document.id === docId
        ? {
            ...document,
            content: snapshot.snapshotData?.content || '# User Requirements\n\nSnapshot restored content.',
            status: snapshot.snapshotData?.status || document.status,
            updatedAt,
            updated_at: updatedAt,
          }
        : document
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(snapshot),
    })
  })

  await page.route(/\/api\/v1\/notifications(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url())
    const includeArchived = url.searchParams.get('include_archived') === 'true'
    const archivedOnly = url.searchParams.get('archived_only') === 'true'
    const unreadOnly = url.searchParams.get('unread_only') === 'true'
    const visible = notifications.filter((item) =>
      (archivedOnly ? item.archived_at : includeArchived || !item.archived_at)
      && (!unreadOnly || !item.read_at)
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: visible,
        total: visible.length,
        page: 1,
        page_size: 25,
        has_more: false,
        unread_count: notifications.filter((item) => !item.archived_at && !item.read_at).length,
      }),
    })
  })

  await page.route(/\/api\/v1\/notifications\/summary(?:\?.*)?$/, async (route) => {
    const active = notifications.filter((item) => !item.archived_at)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        unread_count: active.filter((item) => !item.read_at).length,
        recent: active.slice(0, 5),
      }),
    })
  })

  await page.route(/\/api\/v1\/notifications\/read-all$/, async (route) => {
    let changed = 0
    notifications = notifications.map((item) => {
      if (!item.archived_at && !item.read_at) {
        changed += 1
        return { ...item, read_at: new Date().toISOString() }
      }
      return item
    })
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ changed }) })
  })

  await page.route(/\/api\/v1\/notifications\/preferences$/, async (route) => {
    if (route.request().method() === 'PATCH') {
      notificationPreference = {
        ...notificationPreference,
        ...JSON.parse(route.request().postData() || '{}'),
        updated_at: new Date().toISOString(),
      }
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(notificationPreference),
    })
  })

  await page.route(/\/api\/v1\/notifications\/([^/]+)\/acknowledge$/, async (route) => {
    const id = route.request().url().match(/\/notifications\/([^/]+)\/acknowledge$/)?.[1]
    notifications = notifications.map((item) =>
      item.id === id
        ? { ...item, acknowledged_at: new Date().toISOString(), read_at: item.read_at || new Date().toISOString() }
        : item
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(notifications.find((item) => item.id === id)),
    })
  })

  await page.route(/\/api\/v1\/ops\/notification-deliveries(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: notificationDeliveries,
        total: notificationDeliveries.length,
        sent_count: notificationDeliveries.filter((item) => item.status === 'sent').length,
        failed_count: notificationDeliveries.filter((item) => item.status === 'failed').length,
        pending_count: notificationDeliveries.filter((item) => ['pending', 'retrying'].includes(item.status)).length,
      }),
    })
  })

  await page.route(/\/api\/v1\/ops\/notification-deliveries\/([^/]+)\/retry$/, async (route) => {
    const id = route.request().url().match(/\/notification-deliveries\/([^/]+)\/retry$/)?.[1]
    notificationDeliveries = notificationDeliveries.map((item) =>
      item.id === id
        ? { ...item, status: 'sent', retry_count: String(Number(item.retry_count) + 1), error_message: null, sent_at: new Date().toISOString() }
        : item
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(notificationDeliveries.find((item) => item.id === id)),
    })
  })

  await page.route(/\/api\/v1\/notifications\/([^/]+)\/(read|archive)$/, async (route) => {
    const match = route.request().url().match(/\/notifications\/([^/]+)\/(read|archive)$/)
    const id = match?.[1]
    const action = match?.[2]
    notifications = notifications.map((item) =>
      item.id === id
        ? {
            ...item,
            read_at: item.read_at || new Date().toISOString(),
            archived_at: action === 'archive' ? new Date().toISOString() : item.archived_at,
          }
        : item
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(notifications.find((item) => item.id === id)),
    })
  })
}
