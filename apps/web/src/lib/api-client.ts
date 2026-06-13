function resolveApiBaseUrl(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:18000/api/v1'

  if (typeof window === 'undefined') {
    return configuredUrl
  }

  const { protocol, hostname } = window.location
  const isRemoteBrowser = hostname !== 'localhost' && hostname !== '127.0.0.1'
  const pointsToLocalhost = configuredUrl.includes('://localhost:') || configuredUrl.includes('://127.0.0.1:')

  if (isRemoteBrowser && pointsToLocalhost) {
    if (protocol === 'https:') {
      return `${protocol}//${hostname}/api/v1`
    }

    return `${protocol}//${hostname}:18000/api/v1`
  }

  return configuredUrl
}

const API_BASE_URL = resolveApiBaseUrl()

export interface RequestOptions extends RequestInit {
  params?: Record<string, any>
}

export class ApiClient {
  private baseUrl: string
  private token: string | null

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl
    this.token = null
  }

  setToken(token: string | null) {
    this.token = token
  }

  getToken(): string | null {
    return this.token
  }

  private getAuthorizationHeader(): string | null {
    const token = this.token || this.getStoredToken()
    return token ? `Bearer ${token}` : null
  }

  private getStoredToken(): string | null {
    if (typeof window === 'undefined') return null
    return localStorage.getItem('auth_token')
  }

  async request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { params, ...fetchOptions } = options
    const isFormData = typeof FormData !== 'undefined' && fetchOptions.body instanceof FormData

    let url = `${this.baseUrl}${endpoint}`
    if (params) {
      const searchParams = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          searchParams.append(key, String(value))
        }
      })
      const queryString = searchParams.toString()
      if (queryString) {
        url += `?${queryString}`
      }
    }

    const headers: Record<string, string> = {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(fetchOptions.headers as Record<string, string>),
    }

    const authHeader = this.getAuthorizationHeader()
    if (authHeader) {
      headers['Authorization'] = authHeader
    }

    const response = await fetch(url, {
      ...fetchOptions,
      headers,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Request failed' }))
      throw new Error(error.message || error.detail || `HTTP ${response.status}`)
    }

    if (response.status === 204) {
      return undefined as T
    }

    return response.json()
  }

  async get<T>(endpoint: string, params?: Record<string, any>): Promise<T> {
    return this.request<T>(endpoint, { method: 'GET', params })
  }

  async post<T>(endpoint: string, data?: any): Promise<T> {
    const isFormDataPayload = typeof FormData !== 'undefined' && data instanceof FormData
    return this.request<T>(endpoint, {
      method: 'POST',
      body: isFormDataPayload ? data : data ? JSON.stringify(data) : undefined,
    })
  }

  async patch<T>(endpoint: string, data?: any): Promise<T> {
    const isFormDataPayload = typeof FormData !== 'undefined' && data instanceof FormData
    return this.request<T>(endpoint, {
      method: 'PATCH',
      body: isFormDataPayload ? data : data ? JSON.stringify(data) : undefined,
    })
  }

  async put<T>(endpoint: string, data: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' })
  }
}

export const apiClient = new ApiClient()

// Typed API endpoints
export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<{ access_token: string; token_type: string; expires_in: number }>('/identity/auth/login', { email, password }),
  logout: () => apiClient.post('/identity/auth/logout'),
  me: () => apiClient.get<User>('/identity/auth/me'),
}

export const projectsApi = {
  list: (params?: { page?: number; pageSize?: number; status?: 'active' | 'archived' | 'all' }) =>
    apiClient.get<{ items: Project[]; total: number; page: number; page_size: number; has_more: boolean }>('/projects', {
      page: params?.page,
      page_size: params?.pageSize,
      status: params?.status,
    }).then(normalizeProjectList),
  getDeliveryOverview: (params?: { limit?: number }) =>
    apiClient.get<SystemDeliveryOverview>('/projects/delivery-overview', { limit: params?.limit }),
  getDeliveryPortfolio: () =>
    apiClient.get<SystemDeliveryPortfolio>('/projects/delivery-portfolio'),
  get: async (id: string) => normalizeProject(await apiClient.get<Project>(`/projects/${id}`)),
  create: async (data: ProjectCreatePayload) => normalizeProject(await apiClient.post<Project>('/projects', data)),
  listLaunchBlueprints: () =>
    apiClient.get<ProjectLaunchBlueprint[]>('/projects/launch-blueprints'),
  launch: async (data: ProjectLaunchPayload) => {
    const response = await apiClient.post<ProjectLaunchResponse>('/projects/launch', data)
    return { ...response, project: normalizeProject(response.project) }
  },
  getLaunchPlan: async (id: string) => {
    const response = await apiClient.get<ProjectLaunchResponse>(`/projects/${id}/launch-plan`)
    return { ...response, project: normalizeProject(response.project) }
  },
  retryLaunch: async (id: string) => {
    const response = await apiClient.post<ProjectLaunchResponse>(`/projects/${id}/launch-plan/retry`, {})
    return { ...response, project: normalizeProject(response.project) }
  },
  getDeliveryPlan: (id: string) =>
    apiClient.get<ProjectDeliveryPlan>(`/projects/${id}/delivery-plan`),
  initializeDeliveryPlan: (id: string) =>
    apiClient.post<ProjectDeliveryPlan>(`/projects/${id}/delivery-plan/initialize`, {}),
  createMilestone: (id: string, data: ProjectMilestoneCreateInput) =>
    apiClient.post<ProjectMilestone>(`/projects/${id}/milestones`, data),
  updateMilestone: (id: string, milestoneId: string, data: Partial<ProjectMilestoneCreateInput>) =>
    apiClient.patch<ProjectMilestone>(`/projects/${id}/milestones/${milestoneId}`, data),
  deleteMilestone: (id: string, milestoneId: string) =>
    apiClient.delete(`/projects/${id}/milestones/${milestoneId}`),
  reorderMilestones: (id: string, milestoneIds: string[]) =>
    apiClient.post<ProjectDeliveryPlan>(`/projects/${id}/milestones/reorder`, { milestone_ids: milestoneIds }),
  startMilestone: (id: string, milestoneId: string) =>
    apiClient.post<ProjectMilestone>(`/projects/${id}/milestones/${milestoneId}/start`, {}),
  completeMilestone: (id: string, milestoneId: string) =>
    apiClient.post<ProjectMilestone>(`/projects/${id}/milestones/${milestoneId}/complete`, {}),
  reopenMilestone: (id: string, milestoneId: string) =>
    apiClient.post<ProjectMilestone>(`/projects/${id}/milestones/${milestoneId}/reopen`, {}),
  update: async (id: string, data: Partial<Project>) => normalizeProject(await apiClient.patch<Project>(`/projects/${id}`, data)),
  archive: async (id: string) => normalizeProject(await apiClient.post<Project>(`/projects/${id}/archive`, {})),
  restore: async (id: string) => normalizeProject(await apiClient.post<Project>(`/projects/${id}/restore`, {})),
  delete: (id: string) => apiClient.delete(`/projects/${id}`),
  getDeliveryWorkbench: (id: string) =>
    apiClient.get<ProjectDeliveryWorkbench>(`/projects/${id}/delivery-workbench`),
  getDocumentWorkbench: (id: string) =>
    apiClient.get<ProjectDeliveryWorkbench>(`/projects/${id}/document-workbench`),
  getDocumentLifecyclePolicy: (id: string) =>
    apiClient.get<ProjectDocumentLifecyclePolicy>(`/projects/${id}/document-lifecycle-policy`),
  updateDocumentLifecyclePolicy: (id: string, data: ProjectDocumentLifecyclePolicyUpdate) =>
    apiClient.put<ProjectDocumentLifecyclePolicy>(`/projects/${id}/document-lifecycle-policy`, data),
}

function normalizeProject(project: any): Project {
  return {
    ...project,
    documentCount: project.documentCount ?? project.document_count ?? 0,
    document_count: project.document_count ?? project.documentCount ?? 0,
    createdAt: project.createdAt ?? project.created_at ?? new Date().toISOString(),
    created_at: project.created_at ?? project.createdAt ?? new Date().toISOString(),
    updatedAt: project.updatedAt ?? project.updated_at ?? project.created_at ?? project.createdAt ?? new Date().toISOString(),
    updated_at: project.updated_at ?? project.updatedAt ?? project.created_at ?? project.createdAt ?? new Date().toISOString(),
  }
}

function normalizeProjectList(response: any): { items: Project[]; total: number; page: number; page_size: number; has_more: boolean } {
  const rawItems = response.items ?? response.projects ?? []
  return {
    ...response,
    items: rawItems.map(normalizeProject),
    total: response.total ?? rawItems.length,
    page: response.page ?? 1,
    page_size: response.page_size ?? rawItems.length,
    has_more: response.has_more ?? false,
  }
}

function cleanGeneratedContent(content?: string | null) {
  return (content || '')
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/^<think>[\s\S]*?(?=#\s|##\s|###\s)/i, '')
    .trim()
}

function localizeDocumentTitle(title?: string | null, type?: string | null) {
  const value = title || '未命名文档'
  if (/^URS Document\b/i.test(value)) return '用户需求规格说明书'
  if (/^BRD Document\b/i.test(value)) return '业务需求文档'
  if (/^PRD Document\b/i.test(value)) return '产品需求文档'
  if (!title && type === 'urs') return '用户需求规格说明书'
  return value
}

function normalizeDocument(doc: any): Document {
  const type = doc.type ?? doc.doc_type ?? 'urs'
  const title = localizeDocumentTitle(doc.name ?? doc.title, type)

  return {
    ...doc,
    id: doc.id,
    projectId: doc.projectId ?? doc.project_id,
    project_id: doc.project_id ?? doc.projectId,
    name: title,
    title,
    type,
    doc_type: doc.doc_type ?? doc.type ?? 'urs',
    status: doc.status ?? doc.metadata?.status ?? 'draft',
    content: cleanGeneratedContent(doc.content),
    metadata: doc.metadata ?? doc.metadata_json ?? {},
    metadata_json: doc.metadata_json ?? doc.metadata ?? {},
    createdAt: doc.createdAt ?? doc.created_at,
    created_at: doc.created_at ?? doc.createdAt,
    updatedAt: doc.updatedAt ?? doc.updated_at ?? doc.created_at ?? doc.createdAt,
    updated_at: doc.updated_at ?? doc.updatedAt ?? doc.created_at ?? doc.createdAt,
  }
}

function normalizeDocumentList(response: any): { items: Document[]; total: number; page: number; page_size: number; has_more: boolean } {
  return {
    ...response,
    items: (response.items || []).map(normalizeDocument),
  }
}

export const documentsApi = {
  list: async (params?: { projectId?: string; docType?: string; status?: string; page?: number; pageSize?: number; includePlaceholders?: boolean }) =>
    normalizeDocumentList(await apiClient.get('/documents', {
      project_id: params?.projectId,
      doc_type: params?.docType,
      status: params?.status,
      page: params?.page,
      page_size: params?.pageSize,
      include_placeholders: params?.includePlaceholders,
    })),
  get: async (id: string) => normalizeDocument(await apiClient.get(`/documents/${id}`)),
  create: async (data: Partial<Document>) => normalizeDocument(await apiClient.post('/documents', data)),
  update: async (id: string, data: Partial<Document>) => normalizeDocument(await apiClient.patch(`/documents/${id}`, data)),
  updateStatus: async (id: string, data: { status: string; approved_by?: string; reason?: string; action?: string }) =>
    normalizeDocument(await apiClient.post(`/documents/${id}/status`, data)),
  getStatusCapabilities: (id: string) =>
    apiClient.get<DocumentStatusCapabilities>(`/documents/${id}/status-capabilities`),
  getStatusHistory: (id: string) =>
    apiClient.get<DocumentStatusTransition[]>(`/documents/${id}/status-history`),
  delete: (id: string) => apiClient.delete(`/documents/${id}`),
  generate: async (data: DocumentGeneratePayload) =>
    apiClient.post<DocumentGenerateResult>('/documents/generate', data),
  startGenerationSession: async (data: DocumentGenerationSessionCreateInput) =>
    apiClient.post<DocumentGenerationSession>('/documents/generation-sessions', data),
  listGenerationSessions: async (params: { projectId: string; status?: string }) =>
    apiClient.get<DocumentGenerationSession[]>('/documents/generation-sessions', {
      project_id: params.projectId,
      status: params.status,
    }),
  getGenerationSession: async (sessionId: string) =>
    apiClient.get<DocumentGenerationSession>(`/documents/generation-sessions/${sessionId}`),
  cancelGenerationSession: async (sessionId: string) =>
    apiClient.post<DocumentGenerationSession>(`/documents/generation-sessions/${sessionId}/cancel`),
  continueGenerationSession: async (sessionId: string, data: DocumentGenerationMessageInput) =>
    apiClient.post<DocumentGenerationTurnResult>(`/documents/generation-sessions/${sessionId}/messages`, data),
  finalizeGenerationSession: async (sessionId: string) =>
    apiClient.post<DocumentGenerateResult>(`/documents/generation-sessions/${sessionId}/finalize`),
  getStatistics: () => apiClient.get<DocumentStatistics>('/documents/statistics/summary'),
}

interface SourceFileApiPayload {
  id: string
  project_id?: string
  projectId?: string
  original_filename?: string
  originalFilename?: string
  filename?: string
  name?: string
  content_type?: string
  contentType?: string
  size?: number | string
  status?: string
  metadata?: Record<string, any>
  metadata_json?: Record<string, any>
  ingestion_stage?: string
  ingestion_summary?: string
  extracted_knowledge_count?: number
  required_action?: string
  error_message?: string | null
  created_at?: string
  createdAt?: string
}

interface SourceFileListApiPayload {
  items?: SourceFileApiPayload[]
  total?: number
  page?: number
  page_size?: number
  has_more?: boolean
}

function normalizeSourceFileStatus(status: string | undefined): SourceFile['status'] {
  if (status === 'pending' || status === 'processing' || status === 'ready' || status === 'failed') {
    return status
  }

  return 'ready'
}

function normalizeSourceFile(file: SourceFileApiPayload): SourceFile {
  const createdAt = file.created_at ?? file.createdAt ?? new Date().toISOString()
  const filename = file.filename ?? file.name ?? file.original_filename ?? file.originalFilename ?? 'unnamed'
  const projectId = file.projectId ?? file.project_id ?? ''

  return {
    id: file.id,
    projectId,
    project_id: projectId,
    name: file.original_filename ?? file.originalFilename ?? filename,
    filename,
    type: file.content_type ?? file.contentType ?? 'application/octet-stream',
    size: Number(file.size ?? 0),
    status: normalizeSourceFileStatus(file.status),
    metadata: file.metadata ?? file.metadata_json ?? {},
    ingestionStage: file.ingestion_stage ?? file.metadata?.ingestionStage ?? file.metadata_json?.ingestionStage,
    ingestionSummary: file.ingestion_summary ?? file.metadata?.ingestionSummary ?? file.metadata_json?.ingestionSummary,
    extractedKnowledgeCount:
      file.extracted_knowledge_count ??
      file.metadata?.extractedKnowledgeCount ??
      file.metadata_json?.extractedKnowledgeCount,
    requiredAction: file.required_action ?? file.metadata?.requiredAction ?? file.metadata_json?.requiredAction,
    errorMessage: file.error_message ?? file.metadata?.errorMessage ?? file.metadata_json?.errorMessage,
    createdAt,
    created_at: createdAt,
  }
}

function normalizeSourceFileList(response: SourceFileListApiPayload): { items: SourceFile[]; total: number; page: number; page_size: number; has_more: boolean } {
  const rawItems = response.items ?? []
  return {
    ...response,
    items: rawItems.map(normalizeSourceFile),
    total: response.total ?? rawItems.length,
    page: response.page ?? 1,
    page_size: response.page_size ?? rawItems.length,
    has_more: response.has_more ?? false,
  }
}

export const sourceFilesApi = {
  list: (projectId: string, params?: { page?: number; pageSize?: number }) =>
    apiClient.get<SourceFileListApiPayload>(
      `/projects/${projectId}/files`,
      {
        page: params?.page,
        page_size: params?.pageSize,
      }
    ).then(normalizeSourceFileList),
  upload: (projectId: string, formData: FormData) =>
    apiClient.post<SourceFileApiPayload>(`/projects/${projectId}/files`, formData).then(normalizeSourceFile),
  delete: (projectId: string, fileId: string) =>
    apiClient.delete(`/projects/${projectId}/files/${fileId}`),
  downloadUrl: (projectId: string, fileId: string) =>
    `${API_BASE_URL}/projects/${projectId}/files/${fileId}/download`,
}

export const projectMembersApi = {
  list: (projectId: string, params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: ProjectMember[]; total: number; page: number; page_size: number; has_more: boolean }>(`/projects/${projectId}/members`, {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  invite: (projectId: string, email: string) =>
    apiClient.post<{ token: string; expires_at: string }>(`/projects/${projectId}/invitations?email=${encodeURIComponent(email)}`),
  remove: (projectId: string, userId: string) =>
    apiClient.delete(`/projects/${projectId}/members/${userId}`),
}

export const changeApi = {
  getAuditCommandCenter: (params?: { projectId?: string }) =>
    apiClient.get<ChangeAuditCommandCenter>('/change/command-center', { project_id: params?.projectId }),
  list: (params?: { projectId?: string; status?: string; page?: number; pageSize?: number }) =>
    apiClient.get<{ items: ChangeRequest[]; total: number; page: number; page_size: number; has_more: boolean }>('/change', {
      project_id: params?.projectId,
      status: params?.status,
      page: params?.page,
      page_size: params?.pageSize,
    }),
  get: (id: string) => apiClient.get<ChangeRequest>(`/change/${id}`),
  create: (data: Partial<ChangeRequest>) => apiClient.post<ChangeRequest>('/change', data),
  submit: (id: string) => apiClient.post<ChangeRequest>(`/change/${id}/submit`),
  approve: (id: string) => apiClient.post<ChangeRequest>(`/change/${id}/approve`, {}),
  reject: (id: string, reason = '界面操作退回') => apiClient.post<ChangeRequest>(`/change/${id}/reject`, { reason }),
  apply: (id: string) => apiClient.post<ChangeRequest>(`/change/${id}/apply`, {}),
  cancel: (id: string) => apiClient.post<ChangeRequest>(`/change/${id}/cancel`, {}),
  getTraceabilityMatrix: (projectId: string) =>
    apiClient.get<{ items: TraceabilityRow[]; total: number }>(`/change/traceability/matrix?project_id=${projectId}`),
  getTraceabilityCoverage: (projectId: string) =>
    apiClient.get<TraceabilityCoverage>('/change/traceability/coverage', { project_id: projectId }),
  acceptTraceabilitySuggestions: (projectId: string, suggestionIds?: string[]) =>
    apiClient.request<TraceabilitySuggestionAcceptance>('/change/traceability/coverage/accept-suggestions', {
      method: 'POST',
      params: { project_id: projectId },
      body: JSON.stringify({ suggestion_ids: suggestionIds }),
    }),
  listDocumentReferences: (documentId: string, direction: 'all' | 'incoming' | 'outgoing' = 'all') =>
    apiClient.get<{ items: DocumentReference[]; total: number }>(`/documents/${documentId}/references`, { direction }),
  createDocumentReference: (documentId: string, data: DocumentReferenceCreatePayload) =>
    apiClient.post<DocumentReference>(`/documents/${documentId}/references`, data),
  createDocumentImpactAnalysis: (documentId: string, data: DocumentImpactAnalysisCreatePayload = {}) =>
    apiClient.post<DocumentImpactAnalysis>(`/documents/${documentId}/impact-analysis`, data),
  getDocumentImpactAnalysis: (analysisId: string) =>
    apiClient.get<DocumentImpactAnalysis>(`/change/impact-analyses/${analysisId}`),
  applySyncProposal: (proposalId: string, data: SyncProposalDecisionPayload = {}) =>
    apiClient.post<DocumentSyncProposal>(`/change/sync-proposals/${proposalId}/apply`, data),
  rejectSyncProposal: (proposalId: string, data: SyncProposalDecisionPayload = {}) =>
    apiClient.post<DocumentSyncProposal>(`/change/sync-proposals/${proposalId}/reject`, data),
}

export const identityApi = {
  listUsers: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: TenantUser[]; total: number }>('/identity/users', {
      skip: params?.page && params?.pageSize ? (params.page - 1) * params.pageSize : undefined,
      limit: params?.pageSize,
    }),
  listRoles: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: Role[]; total: number }>('/identity/roles', {
      skip: params?.page && params?.pageSize ? (params.page - 1) * params.pageSize : undefined,
      limit: params?.pageSize,
    }),
  createUser: (data: UserCreatePayload) => apiClient.post<TenantUser>('/identity/users', data),
  updateUser: (id: string, data: Partial<UserCreatePayload> & { is_active?: boolean }) =>
    apiClient.patch<TenantUser>(`/identity/users/${id}`, data),
  deleteUser: (id: string) => apiClient.delete(`/identity/users/${id}`),
  createRole: (data: RoleCreatePayload) => apiClient.post<Role>('/identity/roles', data),
  updateRole: (id: string, data: Partial<RoleCreatePayload>) =>
    apiClient.patch<Role>(`/identity/roles/${id}`, data),
  deleteRole: (id: string) => apiClient.delete<void>(`/identity/roles/${id}`),
  assignRole: (roleId: string, userId: string) =>
    apiClient.post<void>(`/identity/roles/${roleId}/assign`, {
      role_id: roleId,
      user_id: userId,
    }),
  revokeRole: (roleId: string, userId: string) =>
    apiClient.delete<void>(`/identity/roles/${roleId}/assign/${userId}`),
  listPolicies: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: Policy[]; total: number; page: number; page_size: number; has_more: boolean }>('/identity/policies', {
      skip: params?.page && params?.pageSize ? (params.page - 1) * params.pageSize : undefined,
      limit: params?.pageSize,
    }),
  createPolicy: (data: PolicyCreatePayload) => apiClient.post<Policy>('/identity/policies', data),
  updatePolicy: (id: string, data: Partial<PolicyCreatePayload>) =>
    apiClient.patch<Policy>(`/identity/policies/${id}`, data),
  deletePolicy: (id: string) => apiClient.delete<void>(`/identity/policies/${id}`),
  listFieldPermissions: (roleId: string, resourceType: string) =>
    apiClient.get<FieldPermission[]>(`/identity/field-permissions/${roleId}/${resourceType}`),
  setFieldPermission: (data: FieldPermissionCreatePayload) =>
    apiClient.post<FieldPermission>('/identity/field-permissions', data),
  getPermissionDiagnostics: () => apiClient.get<PermissionDiagnostics>('/identity/permission-diagnostics'),
  getPermissionCommandCenter: () => apiClient.get<PermissionCommandCenter>('/identity/permission-command-center'),
  simulatePermission: (data: PermissionSimulationInput) =>
    apiClient.post<PermissionSimulationResult>('/identity/permission-simulations', data),
  listApiKeys: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: TenantApiKey[]; total: number; page: number; page_size: number; has_more: boolean }>('/identity/api-keys', {
      skip: params?.page && params?.pageSize ? (params.page - 1) * params.pageSize : undefined,
      limit: params?.pageSize,
    }),
  createApiKey: (data: TenantApiKeyCreatePayload) =>
    apiClient.post<TenantApiKeyCreateResponse>('/identity/api-keys', data),
  revokeApiKey: (id: string) => apiClient.delete<void>(`/identity/api-keys/${id}`),
  getCurrentUser: () => apiClient.get<AuthMeResponse>('/identity/auth/me'),
  getTenants: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: Tenant[]; total: number }>('/identity/tenants', {
      page: params?.page,
      page_size: params?.pageSize,
    }),
}

export const knowledgeApi = {
  query: (params: { query: string; limit?: number; projectId?: string; mode?: 'fulltext' | 'hybrid' | 'vector' }) =>
    apiClient.get<{ results: KnowledgeResult[] }>('/knowledge/search', {
      q: params.query,
      type: params.mode ?? 'fulltext',
      top_k: params.limit,
      project_id: params.projectId,
    }),
  addNodes: (nodes: Partial<KnowledgeEntryCreateInput>[]) =>
    apiClient.post('/knowledge/entries/bulk', { entries: nodes }),
  getGraph: async (params?: { projectId?: string }) => {
    const entries = await knowledgeApi.getEntries({ projectId: params?.projectId, pageSize: 100 })
    return {
      nodes: entries.items.map((entry) => ({
        id: entry.id,
        type: entry.entry_type,
        properties: {
          name: entry.metadata?.title || entry.metadata?.name || entry.content?.slice(0, 32) || entry.id.slice(0, 8),
          description: entry.content,
          source: entry.metadata?.source || '系统',
          ...entry.metadata,
        },
        projectId: entry.project_id,
      })),
      edges: [],
    }
  },
  getEntries: (params?: { projectId?: string; entryType?: string; sourceFileId?: string; page?: number; pageSize?: number }) =>
    apiClient.get<{ items: KnowledgeEntry[]; total: number }>('/knowledge/entries', {
      project_id: params?.projectId,
      entry_type: params?.entryType,
      source_file_id: params?.sourceFileId,
      page: params?.page,
      page_size: params?.pageSize,
    }),
  getLinks: (params?: { projectId?: string }) =>
    apiClient.get<{ items: KnowledgeLink[] }>('/knowledge/links', params),
}

function uploadTemplateVersion(id: string, formData: FormData) {
  const descriptionValue = formData.get('description')
  const description = typeof descriptionValue === 'string' ? descriptionValue : ''
  const params = new URLSearchParams({ template_id: id })

  if (description) {
    params.set('description', description)
  }

  return apiClient.post<TemplateVersion>(`/templates/upload?${params.toString()}`, formData)
}

export const templatesApi = {
  list: (params?: { docType?: string; skip?: number; limit?: number }) =>
    apiClient.get<{ items: Template[]; total: number } | Template[]>('/templates/', params),
  get: (id: string) => apiClient.get<Template>(`/templates/${id}`),
  create: (data: Partial<Template>) => apiClient.post<Template>('/templates', data),
  delete: (id: string) => apiClient.delete(`/templates/${id}`),
  getVersions: (id: string) =>
    apiClient.get<TemplateVersionsResponse>(`/templates/${id}/versions`).then(normalizeTemplateVersions),
  listSections: (templateId: string, params?: { versionId?: string }) =>
    apiClient.get<TemplateSection[]>(`/templates/${templateId}/sections`, {
      version_id: params?.versionId,
    }),
  seedSections: (templateId: string, params?: { versionId?: string }) => {
    const searchParams = new URLSearchParams()
    if (params?.versionId) searchParams.set('version_id', params.versionId)
    const query = searchParams.toString()
    return apiClient.post<TemplateSection[]>(`/templates/${templateId}/sections/seed${query ? `?${query}` : ''}`, {})
  },
  createSection: (templateId: string, data: TemplateSectionCreateInput) =>
    apiClient.post<TemplateSection>(`/templates/${templateId}/sections`, data),
  updateSection: (sectionId: string, data: Partial<TemplateSectionCreateInput>) =>
    apiClient.patch<TemplateSection>(`/templates/sections/${sectionId}`, data),
  deleteSection: (sectionId: string) => apiClient.delete(`/templates/sections/${sectionId}`),
  replaceSectionSkills: (sectionId: string, skillIds: string[]) =>
    apiClient.put<TemplateSectionSkillBinding[]>(`/templates/sections/${sectionId}/skills`, { skill_ids: skillIds }),
  activateVersion: (id: string, versionId: string) =>
    apiClient.post<TemplateVersion>(`/templates/${id}/versions/${versionId}/activate`),
  parseUpload: (formData: FormData, docType: string) =>
    apiClient.post<ParsedTemplate>(`/templates/parse-upload?doc_type=${encodeURIComponent(docType)}`, formData),
  upload: uploadTemplateVersion,
  uploadVersion: uploadTemplateVersion,
}

export const providersApi = {
  list: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: Provider[]; total: number; page: number; page_size: number; has_more: boolean }>('/providers', {
      page: params?.page,
      page_size: params?.pageSize,
    }).then((response: any) => ({
      ...response,
      items: (response.items || []).map(normalizeProvider),
    })),
  get: async (id: string) => normalizeProvider(await apiClient.get(`/providers/${id}`)),
  create: async (data: Partial<Provider>) => normalizeProvider(await apiClient.post('/providers', {
    name: data.name,
    provider_type: data.type,
    config: data.config || {},
  })),
  update: async (id: string, data: Partial<Provider>) => normalizeProvider(await apiClient.patch(`/providers/${id}`, {
    name: data.name,
    config: data.config,
    status: data.isActive === undefined ? undefined : data.isActive ? 'active' : 'inactive',
  })),
  readiness: () => apiClient.get<ProviderReadinessSummary>('/providers/readiness'),
  delete: (id: string) => apiClient.delete(`/providers/${id}`),
  test: (id: string, data?: ProviderTestRequest) => apiClient.post<ProviderTestResult>(`/providers/${id}/test`, data),
}

export const integrationsApi = {
  list: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<PaginatedList<IntegrationProvider>>('/integrations', {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  create: (data: IntegrationProviderCreateInput) =>
    apiClient.post<IntegrationProvider>('/integrations', data),
  update: (id: string, data: Partial<IntegrationProviderCreateInput>) =>
    apiClient.patch<IntegrationProvider>(`/integrations/${id}`, data),
  delete: (id: string) => apiClient.delete(`/integrations/${id}`),
  test: (id: string) => apiClient.post<IntegrationTestResult>(`/integrations/${id}/test`),
  sync: (id: string) => apiClient.post<IntegrationSyncResult>(`/integrations/${id}/sync`),
  listProjectBindings: (id: string) =>
    apiClient.get<IntegrationProjectBinding[]>(`/integrations/${id}/project-bindings`),
  createProjectBinding: (id: string, data: IntegrationProjectBindingCreateInput) =>
    apiClient.post<IntegrationProjectBinding>(`/integrations/${id}/project-bindings`, data),
  updateProjectBinding: (bindingId: string, data: Partial<IntegrationProjectBindingCreateInput>) =>
    apiClient.patch<IntegrationProjectBinding>(`/integrations/project-bindings/${bindingId}`, data),
  previewProjectBinding: (bindingId: string, limit = 20) =>
    apiClient.post<IntegrationSyncPreview>(`/integrations/project-bindings/${bindingId}/preview?limit=${limit}`, {}),
  syncProjectBinding: (bindingId: string) =>
    apiClient.post<IntegrationProjectSyncRun>(`/integrations/project-bindings/${bindingId}/sync`, {}),
  listProjectBindingRuns: (bindingId: string, limit = 30) =>
    apiClient.get<IntegrationProjectSyncRun[]>(`/integrations/project-bindings/${bindingId}/runs`, { limit }),
  retryProjectBindingRun: (runId: string) =>
    apiClient.post<IntegrationProjectSyncRun>(`/integrations/sync-runs/${runId}/retry`, {}),
  getOperationsSummary: () =>
    apiClient.get<IntegrationOperationsSummary>('/integrations/operations/summary'),
  getProductionCommandCenter: () =>
    apiClient.get<IntegrationProductionCommandCenter>('/integrations/operations/command-center'),
  listWebhooks: (id: string, params?: { page?: number; pageSize?: number }) =>
    apiClient.get<PaginatedList<WebhookSubscription>>(`/integrations/${id}/webhooks`, {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  createWebhook: (id: string, data: WebhookSubscriptionCreateInput) =>
    apiClient.post<WebhookSubscription>(`/integrations/${id}/webhooks`, data),
  updateWebhook: (integrationId: string, webhookId: string, data: Partial<WebhookSubscriptionCreateInput>) =>
    apiClient.patch<WebhookSubscription>(`/integrations/${integrationId}/webhooks/${webhookId}`, data),
  deleteWebhook: (integrationId: string, webhookId: string) =>
    apiClient.delete(`/integrations/${integrationId}/webhooks/${webhookId}`),
  listOutboxEvents: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<PaginatedList<OutboxEvent>>('/integrations/outbox/events', {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  publishOutbox: (batchSize = 100) =>
    apiClient.post<{ processed: number; published: number; failed: number }>(`/integrations/outbox/publish?batch_size=${batchSize}`),
}

function normalizeProvider(provider: any): Provider {
  const status = provider.status
  const isActive = provider.isActive ?? provider.is_active ?? (status === 'active' || status === 'healthy')
  return {
    ...provider,
    id: String(provider.id),
    name: provider.name,
    type: provider.type ?? provider.provider_type ?? 'custom',
    config: provider.config ?? provider.config_json ?? {},
    isActive,
  }
}

function normalizeAgentProfileSummary(profile: AgentProfile): Agent {
  return {
    id: profile.id,
    name: profile.name,
    description: profile.description || '',
    skills: profile.skill_bindings?.map((binding) => binding.skill?.name || binding.skill_id) || [],
    status: profile.status === 'active' ? 'idle' : 'error',
  }
}

export const agentApi = {
  list: async () => {
    const response = await apiClient.get<{ items: AgentProfile[] }>('/agent/agent-profiles')
    return response.items.map(normalizeAgentProfileSummary)
  },
  get: async (id: string) => normalizeAgentProfileSummary(await apiClient.get<AgentProfile>(`/agent/agent-profiles/${id}`)),
  run: async (id: string, params?: { input?: string; input_data?: Record<string, any>; project_id?: string }) => {
    const command = await agentApi.runAgentProfile(id, {
      project_id: params?.project_id,
      input_data: params?.input_data ?? (params?.input ? { input: params.input } : {}),
    })
    return {
      id: command.run_id,
      run_id: command.run_id,
      status: command.status,
      output: command.message,
      artifacts: [],
    } satisfies AgentRunResult
  },
  runAgentProfile: (agentProfileId: string, data?: { project_id?: string; input_data?: Record<string, any> }) =>
    apiClient.post<AgentRunCommandResult>('/agent/agent-runs', {
      agent_profile_id: agentProfileId,
      project_id: data?.project_id,
      input_data: data?.input_data || {},
    }),
  stop: (runId: string) => agentApi.cancelRun(runId),
  listSkillCatalog: (params?: { skillType?: string; status?: string; docType?: string; search?: string; page?: number; pageSize?: number }) =>
    apiClient.get<{ items: SkillCatalogEntry[]; total: number; page: number; page_size: number; has_more: boolean }>('/agent/skills/catalog', {
      skill_type: params?.skillType,
      status: params?.status,
      doc_type: params?.docType,
      search: params?.search,
      page: params?.page,
      page_size: params?.pageSize,
    }),
  createSkillCatalogEntry: (data: SkillCatalogCreateInput) =>
    apiClient.post<SkillCatalogEntry>('/agent/skills/catalog', data),
  updateSkillCatalogEntry: (skillId: string, data: Partial<SkillCatalogCreateInput>) =>
    apiClient.patch<SkillCatalogEntry>(`/agent/skills/catalog/${skillId}`, data),
  publishSkillCatalogEntry: (skillId: string) =>
    apiClient.post<SkillCatalogEntry>(`/agent/skills/catalog/${skillId}/publish`),
  disableSkillCatalogEntry: (skillId: string) =>
    apiClient.post<SkillCatalogEntry>(`/agent/skills/catalog/${skillId}/disable`),
  testSkillCatalogEntry: (skillId: string, data: { input_data?: Record<string, any>; context?: Record<string, any> }) =>
    apiClient.post<SkillCatalogTestResult>(`/agent/skills/catalog/${skillId}/test`, data),
  listAgentProfiles: (params?: { agentType?: string; status?: string; docType?: string; search?: string; page?: number; pageSize?: number }) =>
    apiClient.get<{ items: AgentProfile[]; total: number; page: number; page_size: number; has_more: boolean }>('/agent/agent-profiles', {
      agent_type: params?.agentType,
      status: params?.status,
      doc_type: params?.docType,
      search: params?.search,
      page: params?.page,
      page_size: params?.pageSize,
    }),
  createAgentProfile: (data: AgentProfileCreateInput) =>
    apiClient.post<AgentProfile>('/agent/agent-profiles', data),
  updateAgentProfile: (agentProfileId: string, data: Partial<AgentProfileCreateInput>) =>
    apiClient.patch<AgentProfile>(`/agent/agent-profiles/${agentProfileId}`, data),
  replaceAgentProfileSkills: (agentProfileId: string, skillIds: string[]) =>
    apiClient.put<AgentProfile>(`/agent/agent-profiles/${agentProfileId}/skills`, { skill_ids: skillIds }),
  activateAgentProfile: (agentProfileId: string) =>
    apiClient.post<AgentProfile>(`/agent/agent-profiles/${agentProfileId}/activate`),
  disableAgentProfile: (agentProfileId: string) =>
    apiClient.post<AgentProfile>(`/agent/agent-profiles/${agentProfileId}/disable`),
  listRuns: (params?: {
    projectId?: string
    status?: string
    runType?: string
    workflowDefinitionId?: string
    workflowVersionId?: string
    agentProfileId?: string
    search?: string
    page?: number
    pageSize?: number
  }) =>
    apiClient.get<{ items: AgentRun[]; total: number; page: number; page_size: number; has_more: boolean }>('/agent/agent-runs', {
      project_id: params?.projectId,
      status: params?.status,
      run_type: params?.runType,
      workflow_definition_id: params?.workflowDefinitionId,
      workflow_version_id: params?.workflowVersionId,
      agent_profile_id: params?.agentProfileId,
      search: params?.search,
      page: params?.page,
      page_size: params?.pageSize,
    }),
  getRun: (runId: string) => apiClient.get<AgentRun>(`/agent/agent-runs/${runId}`),
  listRunTasks: (runId: string, params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: AgentTask[]; total: number; page: number; page_size: number; has_more: boolean }>(`/agent/agent-runs/${runId}/tasks`, {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  listRunEvents: (runId: string, params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: AgentEvent[]; total: number; page: number; page_size: number; has_more: boolean }>(`/agent/agent-runs/${runId}/events`, {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  retryRun: (runId: string) =>
    apiClient.post<AgentRunRetryResult>(`/agent/agent-runs/${runId}/retry`),
  cancelRun: (runId: string) =>
    apiClient.post<AgentRun>(`/agent/agent-runs/${runId}/cancel`),
  controlRun: (runId: string, data: AgentRunControlActionInput) =>
    apiClient.post<AgentRun>(`/agent/agent-runs/${runId}/control-actions`, data),
  getOrchestrationDashboard: () =>
    apiClient.get<OrchestrationDashboard>('/agent/orchestration/dashboard'),
  bootstrapOrchestration: () =>
    apiClient.post<OrchestrationBootstrapResult>('/agent/orchestration/bootstrap'),
  listWorkflows: (params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: WorkflowDefinition[]; total: number }>('/agent/workflows', {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  listWorkflowTemplates: () =>
    apiClient.get<{ items: WorkflowTemplate[]; total: number }>('/agent/workflows/templates'),
  getWorkflow: (workflowId: string) => apiClient.get<WorkflowDefinition>(`/agent/workflows/${workflowId}`),
  createWorkflow: (data: { name: string; description?: string; category?: string }) =>
    apiClient.post<WorkflowDefinition>('/agent/workflows', data),
  createWorkflowFromTemplate: (data: { template_id: string; name?: string; description?: string; publish?: boolean }) =>
    apiClient.post<WorkflowDefinition>('/agent/workflows/from-template', data),
  updateWorkflow: (workflowId: string, data: { name?: string; description?: string; category?: string; is_active?: boolean }) =>
    apiClient.patch<WorkflowDefinition>(`/agent/workflows/${workflowId}`, data),
  listWorkflowVersions: (workflowId: string, params?: { page?: number; pageSize?: number }) =>
    apiClient.get<{ items: WorkflowVersion[]; total: number }>(`/agent/workflows/${workflowId}/versions`, {
      page: params?.page,
      page_size: params?.pageSize,
    }),
  createWorkflowVersion: (workflowId: string, data: { dag_json: any; skill_contracts?: any[]; tool_contracts?: any[] }) =>
    apiClient.post<WorkflowVersion>(`/agent/workflows/${workflowId}/versions`, data),
  activateWorkflowVersion: (workflowId: string, versionId: string) =>
    apiClient.post<{ version_id: string; workflow_definition_id: string; is_active: boolean; message: string }>(`/agent/workflows/${workflowId}/versions/${versionId}/activate`),
  validateWorkflowDag: (data: { dag_json: any }) =>
    apiClient.post<WorkflowDagValidation>('/agent/workflows/validate', data),
  previewWorkflowDag: (data: { dag_json: any; input_data?: Record<string, any> }) =>
    apiClient.post<WorkflowDagPreview>('/agent/workflows/preview', data),
  getWorkflowProductionPreflight: (workflowId: string, params?: { projectId?: string }) =>
    apiClient.get<WorkflowProductionPreflight>(`/agent/workflows/${workflowId}/production-preflight`, {
      project_id: params?.projectId,
    }),
  executeWorkflow: (data: { workflow_id: string; project_id: string; version_id?: string; input_data?: Record<string, any> }) =>
    apiClient.post<{ run_id: string; status: AgentRun['status']; message: string }>('/agent/workflows/execute', data),
}

export const auditApi = {
  listLogs: (params?: {
    tenantId?: string;
    userId?: string;
    action?: string;
    resourceType?: string;
    startDate?: string;
    endDate?: string;
    page?: number;
    pageSize?: number;
  }) => apiClient.get<{ items: AuditLog[]; total: number; page: number; page_size: number; has_more: boolean }>('/identity/audit-logs', {
    tenant_id: params?.tenantId,
    user_id: params?.userId,
    resource_type: params?.resourceType,
    start_date: params?.startDate,
    end_date: params?.endDate,
    action: params?.action,
    page: params?.page,
    page_size: params?.pageSize,
  }),
}

export const notificationsApi = {
  list: (params?: {
    page?: number
    pageSize?: number
    unreadOnly?: boolean
    includeArchived?: boolean
    archivedOnly?: boolean
    category?: string
    priority?: string
    search?: string
    acknowledgement?: 'required' | 'acknowledged'
    escalated?: boolean
  }) =>
    apiClient.get<UserNotificationList>('/notifications', {
      page: params?.page,
      page_size: params?.pageSize,
      unread_only: params?.unreadOnly,
      include_archived: params?.includeArchived,
      archived_only: params?.archivedOnly,
      category: params?.category,
      priority: params?.priority,
      search: params?.search,
      acknowledgement: params?.acknowledgement,
      escalated: params?.escalated,
    }),
  summary: (limit = 5) =>
    apiClient.get<UserNotificationSummary>('/notifications/summary', { limit }),
  markRead: (notificationId: string) =>
    apiClient.post<UserNotification>(`/notifications/${notificationId}/read`, {}),
  markAllRead: () =>
    apiClient.post<{ changed: number }>('/notifications/read-all', {}),
  archive: (notificationId: string) =>
    apiClient.post<UserNotification>(`/notifications/${notificationId}/archive`, {}),
  acknowledge: (notificationId: string) =>
    apiClient.post<UserNotification>(`/notifications/${notificationId}/acknowledge`, {}),
  getPreferences: () =>
    apiClient.get<NotificationPreference>('/notifications/preferences'),
  updatePreferences: (data: Partial<NotificationPreference>) =>
    apiClient.patch<NotificationPreference>('/notifications/preferences', data),
}

export const opsApi = {
  getHealth: () => apiClient.get<HealthStatus>('/ops/health'),
  getProductionCommandCenter: () => apiClient.get<ProductionOpsCommandCenter>('/ops/production-command-center'),
  getCapabilityReadiness: () => apiClient.get<CapabilityReadiness>('/ops/capabilities/readiness'),
  getCapabilityActivationPlan: () => apiClient.get<CapabilityActivationResponse>('/ops/capabilities/activation-plan'),
  runCapabilityActivation: (data: CapabilityActivationRequest) =>
    apiClient.post<CapabilityActivationResponse>('/ops/capabilities/activation-run', data),
  getCapabilityCommissioning: () => apiClient.get<CapabilityCommissioningResponse>('/ops/capabilities/commissioning'),
  runCapabilityCommissioning: (data: CapabilityCommissioningRunRequest) =>
    apiClient.post<CapabilityCommissioningResponse>('/ops/capabilities/commissioning/run', data),
  getMetrics: () => apiClient.get<PlatformMetrics>('/ops/metrics'),
  getQuota: () => apiClient.get<QuotaStatus>('/ops/quota'),
  getQuotaCommandCenter: (tenantId: string) =>
    apiClient.get<QuotaCommandCenter>('/ops/quota-command-center', { tenant_id: tenantId }),
  getTenantMetrics: (tenantId: string) =>
    apiClient.get<TenantMetrics>(`/ops/metrics/tenant/${tenantId}`),
  listQuotas: (tenantId: string) =>
    apiClient.get<{ quotas: QuotaUsage[]; total: number }>('/ops/quotas', { tenant_id: tenantId }),
  listCircuitBreakers: () => apiClient.get<{ breakers: CircuitBreaker[] }>('/ops/circuit-breakers'),
  getUsageStats: (tenantId: string) =>
    apiClient.get<UsageStatsResult>('/ops/usage-stats', { tenant_id: tenantId }),
  getRateLimits: (tenantId: string) =>
    apiClient.get<RateLimitsResult>('/ops/rate-limits', { tenant_id: tenantId }),
  listNotificationDeliveries: (tenantId: string, params?: { status?: string; channel?: string; limit?: number }) =>
    apiClient.get<NotificationDeliveryList>('/ops/notification-deliveries', {
      tenant_id: tenantId,
      status: params?.status,
      channel: params?.channel,
      limit: params?.limit,
    }),
  retryNotificationDelivery: (eventId: string) =>
    apiClient.post<NotificationDelivery>(`/ops/notification-deliveries/${eventId}/retry`, {}),
}

export interface CircuitBreaker {
  name: string
  state: string
  failure_count: number
  last_failure_time: string | null
}

export const exportsApi = {
  list: () =>
    apiClient.get<ExportJob[] | { exports?: ExportJob[] }>('/exports').then((response) =>
      Array.isArray(response) ? response : response.exports || []
    ),
  getReadiness: (projectId: string) =>
    apiClient.get<ExportReadiness>('/exports/readiness', { project_id: projectId }),
  getReleaseEvidence: (projectId: string) =>
    apiClient.get<ExportReleaseEvidence>('/exports/release-evidence', { project_id: projectId }),
  createWord: (data: { document_id: string; template_id: string; title: string; variables?: Record<string, any> }) =>
    apiClient.post<{ job_id: string; status: string; message: string }>('/exports/word', data),
  createMarkdown: (data: { document_id: string; title: string; variables?: Record<string, any> }) =>
    apiClient.post<{ job_id: string; status: string; message: string }>('/exports/markdown', data),
  createPptx: (data: { document_id: string; template_id: string; title: string; variables?: Record<string, any> }) =>
    apiClient.post<{ job_id: string; status: string; message: string }>('/exports/pptx', data),
  createProjectPackage: (data: ProjectPackageExportPayload) =>
    apiClient.post<{ job_id: string; status: string; message: string }>('/exports/project-package', data),
  getJobStatus: (jobId: string) =>
    apiClient.get<ExportJobStatus>(`/exports/jobs/${jobId}`),
  downloadArtifact: (artifactId: string) =>
    `${API_BASE_URL}/exports/artifacts/${artifactId}/download`,
}

export const collaborationApi = {
  getReviewHub: () =>
    apiClient.get<CollaborationReviewHub>('/collaboration/review-hub'),
  getAcceptanceCommandCenter: () =>
    apiClient.get<CollaborationAcceptanceCommandCenter>('/collaboration/acceptance-command-center'),
  performReviewAction: (reviewId: string, action: CollaborationReviewAction) =>
    apiClient.post<CollaborationReviewItem>(`/collaboration/review-items/${reviewId}/${action}`, {}),
  listWorkItems: (params?: {
    status?: string
    priority?: string
    assignment?: 'all' | 'mine' | 'unassigned'
    projectId?: string
    overdueOnly?: boolean
    search?: string
    page?: number
    pageSize?: number
  }) =>
    apiClient.get<CollaborationWorkItemBoard>('/collaboration/work-items', {
      status: params?.status,
      priority: params?.priority,
      assignment: params?.assignment,
      project_id: params?.projectId,
      overdue_only: params?.overdueOnly,
      search: params?.search,
      page: params?.page,
      page_size: params?.pageSize,
    }),
  createWorkItem: (data: CollaborationWorkItemCreate) =>
    apiClient.post<CollaborationWorkItem>('/collaboration/work-items', data),
  updateWorkItem: (workItemId: string, data: Partial<CollaborationWorkItemCreate> & { status?: string }) =>
    apiClient.patch<CollaborationWorkItem>(`/collaboration/work-items/${workItemId}`, data),
  claimWorkItem: (workItemId: string) =>
    apiClient.post<CollaborationWorkItem>(`/collaboration/work-items/${workItemId}/claim`, {}),
  completeWorkItem: (workItemId: string) =>
    apiClient.post<CollaborationWorkItem>(`/collaboration/work-items/${workItemId}/complete`, {}),
  reopenWorkItem: (workItemId: string) =>
    apiClient.post<CollaborationWorkItem>(`/collaboration/work-items/${workItemId}/reopen`, {}),
  getComments: (documentId: string) =>
    apiClient.get<any[]>(`/collaboration/documents/${documentId}/comments`).then((items) =>
      items.map(normalizeComment)
    ),
  addComment: async (
    documentId: string,
    data: { content: string; anchor?: string; parent_comment_id?: string }
  ) => normalizeComment(await apiClient.post<Comment>(`/collaboration/documents/${documentId}/comments`, data)),
  resolveComment: async (commentId: string) =>
    normalizeComment(await apiClient.post<Comment>(`/collaboration/comments/${commentId}/resolve`, {})),
  getVersions: (documentId: string) =>
    apiClient.get<any>(`/documents/${documentId}/versions`).then((response) =>
      (Array.isArray(response) ? response : response.items || []).map((item: any) => ({
        ...item,
        documentId: item.documentId ?? item.document_id,
        versionNumber: item.versionNumber ?? item.version,
        description: item.description ?? item.changes_summary ?? '',
        createdBy: item.createdBy ?? item.created_by,
        createdAt: item.createdAt ?? item.created_at,
      }))
    ),
  createVersion: (documentId: string, data: { content: string; changes_summary?: string }) =>
    apiClient.post<Version>(`/documents/${documentId}/versions`, data),
  getBaselines: (documentId: string) =>
    apiClient.get<any>(`/documents/${documentId}/baselines`).then((response) =>
      (Array.isArray(response) ? response : response.items || []).map((item: any) => ({
        ...item,
        documentId: item.documentId ?? item.document_id,
        versionId: item.versionId ?? item.version_id,
        name: item.name ?? item.baseline_name,
        reason: item.reason ?? item.baseline_reason,
        approvedBy: item.approvedBy ?? item.approved_by,
        approvedAt: item.approvedAt ?? item.approved_at,
        createdAt: item.createdAt ?? item.created_at,
      }))
    ),
  createBaseline: (documentId: string, data: { version_id: string; baseline_name: string; baseline_reason?: string }) =>
    apiClient.post<DocumentBaseline>(`/documents/${documentId}/baselines`, data),
  rollbackBaseline: async (documentId: string, baselineId: string) =>
    normalizeDocument(await apiClient.post(`/documents/${documentId}/baselines/${baselineId}/rollback`, {})),
  getSnapshots: (documentId: string) =>
    apiClient.get<any[]>(`/collaboration/documents/${documentId}/snapshots`).then((items) =>
      items.map((item) => ({
        ...item,
        documentId: item.documentId ?? item.document_id,
        userId: item.userId ?? item.user_id,
        snapshotData: item.snapshotData ?? item.snapshot_data ?? {},
        snapshotType: item.snapshotType ?? item.snapshot_type,
        createdAt: item.createdAt ?? item.created_at,
      }))
    ),
  createSnapshot: async (
    documentId: string,
    data: { snapshot_type: 'auto' | 'manual'; title?: string; content?: string }
  ) => normalizeDocumentSnapshot(
    await apiClient.post<DocumentSnapshot>(`/collaboration/documents/${documentId}/snapshots`, data)
  ),
  restoreSnapshot: async (snapshotId: string) => normalizeDocumentSnapshot(
    await apiClient.post<DocumentSnapshot>(`/collaboration/snapshots/${snapshotId}/restore`, {})
  ),
}

// Types
export interface User {
  id: string
  email: string
  name: string
  role: string
  tenantId: string
  tenant_id?: string
  full_name?: string
  is_active?: boolean
}

export interface UserNotification {
  id: string
  tenant_id: string
  user_id: string
  actor_id: string | null
  project_id: string | null
  category: string
  priority: 'low' | 'normal' | 'high' | 'urgent' | string
  title: string
  body: string
  action_url: string | null
  entity_type: string | null
  entity_id: string | null
  metadata_json: Record<string, any>
  read_at: string | null
  archived_at: string | null
  expires_at: string | null
  ack_required: boolean
  acknowledged_at: string | null
  ack_deadline_at: string | null
  escalation_level: number
  escalated_at: string | null
  created_at: string
  updated_at: string
}

export interface UserNotificationList {
  items: UserNotification[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  unread_count: number
}

export interface UserNotificationSummary {
  unread_count: number
  recent: UserNotification[]
}

export interface NotificationPreference {
  id: string
  tenant_id: string
  user_id: string
  in_app_enabled: boolean
  email_enabled: boolean
  enabled_categories: string[]
  min_priority: 'low' | 'normal' | 'high' | 'urgent' | string
  daily_digest: boolean
  ack_timeout_minutes: number
  created_at: string
  updated_at: string
}

export interface NotificationDelivery {
  id: string
  tenant_id: string | null
  channel: string
  recipient: string | null
  title: string
  body: string
  status: string
  retry_count: string
  error_message: string | null
  metadata_json: Record<string, any>
  sent_at: string | null
  next_retry_at: string | null
  created_at: string
  updated_at: string
}

export interface NotificationDeliveryList {
  items: NotificationDelivery[]
  total: number
  sent_count: number
  failed_count: number
  pending_count: number
}

export interface Project {
  id: string
  name: string
  description: string
  slug?: string
  status?: string
  documentCount: number
  createdAt: string
  updatedAt: string
  document_count?: number
  created_at?: string
  updated_at?: string
}

export interface SystemDeliveryProjectDigest {
  project_id: string
  name: string
  status: string
  updated_at: string
  readiness_score: number
  readiness_label: string
  blocker_count: number
  document_count: number
  source_file_count: number
  knowledge_entry_count: number
  open_change_count: number
  review_queue_count: number
  export_ready: boolean
  delivery_phase_key: string
  delivery_phase_label: string
  release_gate_status: 'passed' | 'blocked' | 'attention' | 'empty' | string
  next_action_label: string
  next_action_href: string
  next_action_priority: string
}

export interface SystemDeliveryModuleHealth {
  key: string
  label: string
  status: 'healthy' | 'attention' | 'blocked' | string
  score: number
  summary: string
  action_href: string
}

export interface SystemDeliveryAction {
  project_id: string
  project_name: string
  code: string
  label: string
  description: string
  href: string
  priority: string
}

export interface SystemDeliveryPhaseSummary {
  key: string
  label: string
  status: 'healthy' | 'attention' | 'blocked' | 'empty' | string
  project_count: number
  blocked_project_count: number
  ready_project_count: number
  score: number
  summary: string
  action_href: string
}

export interface SystemDeliveryReleaseGate {
  key: string
  label: string
  status: 'passed' | 'blocked' | 'empty' | string
  passed_count: number
  total_count: number
  score: number
  blockers: string[]
  action_href: string
}

export interface SystemDeliveryOperatingPlanItem {
  project_id: string
  project_name: string
  phase_key: string
  phase_label: string
  action_code: string
  action_label: string
  action_description: string
  action_href: string
  priority: string
  status: 'passed' | 'blocked' | 'attention' | string
}

export interface SystemCompletionCapability {
  key: string
  label: string
  status: 'ready' | 'attention' | 'blocked' | string
  score: number
  summary: string
  evidence: Record<string, number | string | boolean>
  blockers: string[]
  action_label: string
  action_href: string
}

export interface SystemCompletionGap {
  key: string
  capability_key: string
  severity: 'critical' | 'high' | 'medium' | string
  title: string
  detail: string
  action_label: string
  action_href: string
}

export interface SystemProductionGateCheck {
  capability_key: string
  label: string
  status: 'ready' | 'attention' | 'blocked' | string
  score: number
  detail: string
  action_label: string
  action_href: string
}

export interface SystemProductionGate {
  status: 'passed' | 'attention' | 'blocked' | string
  score: number
  production_ready: boolean
  ready_count: number
  attention_count: number
  blocking_count: number
  total_count: number
  checks: SystemProductionGateCheck[]
}

export interface SystemDeliveryMilestoneDigest {
  milestone_id: string
  project_id: string
  project_name: string
  title: string
  status: string
  priority: string
  owner_id: string | null
  owner_name: string
  due_at: string | null
  is_overdue: boolean
  gate_blocker_count: number
  action_href: string
}

export interface SystemDeliveryOwnerLoad {
  owner_id: string | null
  owner_name: string
  active_count: number
  blocked_count: number
  overdue_count: number
  project_count: number
  action_href: string
}

export interface SystemDeliveryMilestonePortfolio {
  totals: Record<string, number>
  status_counts: Record<string, number>
  upcoming: SystemDeliveryMilestoneDigest[]
  blocked: SystemDeliveryMilestoneDigest[]
  owner_load: SystemDeliveryOwnerLoad[]
}

export interface SystemDeliveryPortfolio {
  generated_at: string
  project_count: number
  portfolio: SystemDeliveryMilestonePortfolio
}

export interface SystemDeliveryOverview {
  generated_at: string
  readiness_score: number
  totals: Record<string, number>
  module_health: SystemDeliveryModuleHealth[]
  projects: SystemDeliveryProjectDigest[]
  critical_actions: SystemDeliveryAction[]
  phase_summary: SystemDeliveryPhaseSummary[]
  release_gates: SystemDeliveryReleaseGate[]
  operating_plan: SystemDeliveryOperatingPlanItem[]
  completion_capabilities: SystemCompletionCapability[]
  completion_gaps: SystemCompletionGap[]
  completion_score: number
  production_gate: SystemProductionGate
  milestone_portfolio: SystemDeliveryMilestonePortfolio
}

export interface ProjectCreatePayload {
  name: string
  description?: string
  slug: string
}

export interface ProjectLaunchBlueprint {
  key: string
  name: string
  description: string
  scenarios: string[]
  document_types: string[]
  workflow_template_ids: string[]
  checks: string[]
  next_actions: string[]
}

export interface ProjectLaunchPayload {
  blueprint_key: string
  name: string
  description?: string
  slug: string
  member_ids: string[]
  document_types: string[]
  workflow_template_ids: string[]
}

export interface ProjectLaunchPlan {
  id: string
  tenant_id: string
  project_id: string
  blueprint_key: string
  status: 'pending' | 'running' | 'ready' | 'attention' | 'failed' | string
  config_json: Record<string, any>
  checks_json: Array<{ key: string; label: string; status: string }>
  results_json: Record<string, any>
  error_message: string | null
  attempt_count: number
  created_by: string
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface ProjectLaunchResponse {
  project: Project
  plan: ProjectLaunchPlan
}

export interface ProjectMilestoneGate {
  key: string
  status: 'passed' | 'blocked' | string
  message: string
  action_href?: string
}

export interface ProjectMilestone {
  id: string
  tenant_id: string
  project_id: string
  plan_id: string
  owner_id: string | null
  key: string
  title: string
  description: string
  status: 'planned' | 'in_progress' | 'blocked' | 'completed' | string
  priority: 'low' | 'medium' | 'high' | 'critical' | string
  order_index: number
  planned_start_at: string | null
  due_at: string | null
  completed_at: string | null
  required_document_types_json: string[]
  required_workflow_template_ids_json: string[]
  gate_results_json: ProjectMilestoneGate[]
  metadata_json: Record<string, any>
  created_at: string
  updated_at: string
}

export interface ProjectDeliveryPlanSummary {
  total_count: number
  completed_count: number
  blocked_count: number
  overdue_count: number
  progress_percent: number
  next_milestone_id: string | null
  blockers: string[]
}

export interface ProjectDeliveryPlan {
  id: string
  tenant_id: string
  project_id: string
  blueprint_key: string
  status: 'active' | 'attention' | 'completed' | string
  summary_json: Record<string, any>
  settings_json: Record<string, any>
  created_by: string
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  milestones: ProjectMilestone[]
  summary: ProjectDeliveryPlanSummary
}

export interface ProjectMilestoneCreateInput {
  key: string
  title: string
  description?: string
  owner_id?: string | null
  priority?: 'low' | 'medium' | 'high' | 'critical'
  planned_start_at?: string | null
  due_at?: string | null
  required_document_types?: string[]
  required_workflow_template_ids?: string[]
}

export interface ProjectDeliveryDocumentItem {
  id: string
  title: string
  doc_type: string
  status: string
  version: number
  updated_at: string
}

export interface ProjectDeliveryChainItem {
  doc_type: string
  label: string
  document_id: string | null
  title: string | null
  status: string
  version: number | null
  updated_at: string | null
  missing: boolean
  completion_ratio?: number
  quality_level?: string | null
  upstream_dependencies?: string[]
  blockers?: string[]
  action_href?: string | null
}

export interface ProjectDeliveryRisk {
  code: string
  severity: 'high' | 'medium' | 'low' | string
  title: string
  description: string
  target_href: string
}

export interface ProjectDeliveryNextAction {
  code: string
  label: string
  description: string
  href: string
  priority: 'high' | 'medium' | 'low' | string
}

export interface ProjectDocumentWorkflowLane {
  key: string
  label: string
  count: number
  attention_count: number
  document_ids: string[]
  href: string
}

export interface ProjectDocumentQualityGate {
  key: string
  label: string
  status: 'passed' | 'warning' | 'blocked' | string
  score: number
  message: string
  target_href: string
}

export interface ProjectDocumentTemplateCoverage {
  doc_type: string
  label: string
  template_available: boolean
  active_template_count: number
  section_count: number
  skill_binding_count: number
  action_href: string
}

export interface ProjectDocumentExportPackage {
  ready: boolean
  required_document_count: number
  completed_document_count: number
  approved_or_published_count: number
  latest_job_id: string | null
  latest_job_status: string | null
  blockers: string[]
  action_href: string
}

export interface ProjectDocumentCollaborationSummary {
  member_count: number
  unresolved_comment_count: number
  review_queue_count: number
  active_session_count: number
  open_change_count: number
  action_href: string
}

export interface ProjectDocumentPackageManifestItem {
  doc_type: string
  label: string
  required: boolean
  included: boolean
  release_ready: boolean
  document_id: string | null
  title: string | null
  status: string
  version: number | null
  export_order: number
  blockers: string[]
  action_href: string
}

export interface ProjectDocumentTraceabilityAction {
  code: string
  status: 'missing_reference' | 'pending_sync' | string
  source_document_id: string | null
  source_title: string | null
  source_doc_type: string | null
  target_document_id: string | null
  target_title: string | null
  target_doc_type: string | null
  reference_type: string
  reason: string
  action_href: string
}

export interface ProjectDocumentCollaborationAction {
  code: string
  label: string
  description: string
  count: number
  priority: 'high' | 'medium' | 'low' | string
  action_href: string
}

export interface ProjectDocumentControlAction {
  code: string
  label: string
  href: string
  priority: 'high' | 'medium' | 'low' | string
}

export interface ProjectDocumentControlMatrixItem {
  doc_type: string
  label: string
  stage: 'missing' | 'authoring' | 'review' | 'release_ready' | 'published' | 'blocked' | string
  stage_label: string
  document_id: string | null
  title: string | null
  status: string
  version: number | null
  completion_ratio: number
  quality_level: string | null
  template_ready: boolean
  source_ready: boolean
  release_ready: boolean
  package_included: boolean
  upstream_missing: string[]
  traceability_gap_count: number
  blockers: string[]
  primary_action: ProjectDocumentControlAction
  secondary_actions: ProjectDocumentControlAction[]
}

export interface ProjectDocumentSourceCoverage {
  status: 'ready' | 'warning' | 'blocked' | string
  label: string
  source_file_total: number
  ready_source_file_count: number
  pending_source_file_count: number
  failed_source_file_count: number
  knowledge_entry_count: number
  blockers: string[]
  action_href: string
}

export interface ProjectDeliverySessionItem {
  id: string
  doc_type: string
  title: string
  status: string
  current_section_key: string | null
  confirmed_sections: number
  section_count: number
  updated_at: string
}

export interface ProjectDeliveryReadiness {
  ready: boolean
  export_ready: boolean
  review_ready: boolean
  blockers: string[]
}

export interface ProjectDeliveryWorkbench {
  project_id: string
  generated_at: string
  totals: {
    documents: number
    source_files: number
    knowledge_entries: number
    members: number
    change_requests: number
  }
  document_status_counts: Record<string, number>
  document_type_counts: Record<string, number>
  source_file_status_counts: Record<string, number>
  change_status_counts: Record<string, number>
  traceability: {
    active_references: number
    open_impact_analyses: number
    pending_sync_proposals: number
  }
  delivery_chain: ProjectDeliveryChainItem[]
  review_queue: ProjectDeliveryDocumentItem[]
  recent_documents: ProjectDeliveryDocumentItem[]
  risks: ProjectDeliveryRisk[]
  next_actions: ProjectDeliveryNextAction[]
  active_sessions?: ProjectDeliverySessionItem[]
  readiness?: ProjectDeliveryReadiness | null
  workflow_lanes?: ProjectDocumentWorkflowLane[]
  quality_gates?: ProjectDocumentQualityGate[]
  template_coverage?: ProjectDocumentTemplateCoverage[]
  export_package?: ProjectDocumentExportPackage | null
  collaboration_summary?: ProjectDocumentCollaborationSummary | null
  package_manifest?: ProjectDocumentPackageManifestItem[]
  traceability_actions?: ProjectDocumentTraceabilityAction[]
  collaboration_actions?: ProjectDocumentCollaborationAction[]
  control_matrix?: ProjectDocumentControlMatrixItem[]
  source_coverage?: ProjectDocumentSourceCoverage | null
}

export interface Document {
  id: string
  projectId: string
  project_id?: string
  name: string
  title?: string
  type: string
  doc_type?: string
  status?: string
  content: string
  metadata: Record<string, any>
  metadata_json?: Record<string, any>
  createdAt: string
  created_at?: string
  updatedAt: string
  updated_at?: string
}

export interface DocumentGeneratePayload {
  project_id: string
  doc_type: string
  context: Record<string, any>
  title?: string
}

export interface DocumentGenerateResult {
  document_id: string
  doc_type: string
  title: string
  content: string
  status: string
  version: number
  generated_at: string
}

export interface ProjectMember {
  user_id: string
  role_id: string | null
  project_id: string
  created_at: string
  updated_at: string
}

export interface KnowledgeResult {
  node: KnowledgeNode
  score: number
  highlights: string[]
}

export interface KnowledgeNode {
  id: string
  type: string
  properties: Record<string, any>
  projectId?: string
}

export interface KnowledgeEdge {
  id: string
  source: string
  target: string
  type: string
  properties: Record<string, any>
}

export interface KnowledgeEntry {
  id: string
  entry_type: string
  content: string
  metadata: Record<string, any>
  project_id?: string
  source_file_id?: string
  created_at: string
  updated_at?: string
}

export interface KnowledgeEntryCreateInput {
  project_id: string
  source_file_id?: string | null
  entry_type: string
  content: string
  metadata?: Record<string, any>
  sharing_scope?: string
  generate_embedding?: boolean
}

export interface KnowledgeLink {
  id: string
  source_entry_id: string
  target_entry_id: string
  link_type: string
  metadata: Record<string, any>
}

export interface Template {
  id: string
  name: string
  description: string | null
  doc_type: string
  version_count: number
  is_active: string
  created_at: string
  updated_at: string
}

export interface TemplateVersion {
  id: string
  version: number
  file_hash: string
  is_active: string
  placeholder_schema: TemplatePlaceholder[] | null
  page_types: TemplatePageType[] | null
  created_at: string
}

export interface TemplatePlaceholder {
  name: string
  description?: string | null
  default_value?: string | null
  field_type: string
  required: boolean
  occurrence_count?: number
}

export interface TemplatePageType {
  page_number?: number
  page_type?: string
  title_placeholder?: string | null
  content_placeholders?: string[]
  name?: string
  count?: number
}

export interface ParsedTemplate {
  placeholders: TemplatePlaceholder[]
  page_types: TemplatePageType[]
  file_hash?: string | null
  total_pages: number
  is_valid: boolean
  warnings: string[]
  errors: string[]
  invalid_placeholders: string[]
  duplicate_placeholders: string[]
  content_format: string
}

export interface TemplateSectionSkillBinding {
  id: string
  tenant_id: string | null
  section_id: string
  skill_id: string
  order_index: number
  is_required: boolean
  prompt_override: string | null
  created_by: string
  created_at: string | null
  updated_at: string | null
  skill: SkillCatalogEntry | null
}

export interface TemplateSection {
  id: string
  tenant_id: string | null
  template_version_id: string
  parent_section_id: string | null
  section_key: string
  title: string
  level: number
  position: number
  content_requirement: string
  prompt: string
  required_inputs: string[]
  quality_rules: Array<{ rule: string; severity?: string }>
  created_by: string
  created_at: string
  updated_at: string
  deleted_at: string | null
  skill_bindings: TemplateSectionSkillBinding[]
}

export interface TemplateSectionCreateInput {
  template_version_id?: string | null
  parent_section_id?: string | null
  section_key: string
  title: string
  level?: number
  position?: number
  content_requirement?: string
  prompt?: string
  required_inputs?: string[]
  quality_rules?: Array<{ rule: string; severity?: string }>
}

type TemplateVersionsResponse = { items?: TemplateVersion[] } | TemplateVersion[]

function normalizeTemplateVersions(response: TemplateVersionsResponse): TemplateVersion[] {
  return Array.isArray(response) ? response : response.items ?? []
}

export interface Provider {
  id: string
  name: string
  type: string
  config: Record<string, any>
  isActive: boolean
}

export interface ProviderTestResult {
  success: boolean
  message: string
  latency_ms?: number | null
  output?: Record<string, any> | null
  status: string
  mode: string
  capability_type?: string | null
  configured: boolean
  production_ready: boolean
  sandbox_fallback: boolean
}

export interface ProviderTestRequest {
  capability_type: string
  params?: Record<string, any>
  allow_sandbox?: boolean
}

export interface ProviderReadinessItem {
  provider_id: string
  name: string
  provider_type: string
  status: string
  readiness: 'ready' | 'sandbox' | 'unconfigured' | 'inactive' | string
  reason: string
  recommended_action: string
}

export interface ProviderRequiredTypeReadiness {
  provider_type: string
  label: string
  live_count: number
  sandbox_count: number
  unconfigured_count: number
  status: 'ready' | 'sandbox' | 'unconfigured' | 'missing' | string
}

export interface ProviderReadinessSummary {
  tenant_id: string
  total_providers: number
  live_providers: number
  sandbox_providers: number
  unconfigured_providers: number
  inactive_providers: number
  readiness_score: number
  production_ready: boolean
  missing_required_types: string[]
  required_types: ProviderRequiredTypeReadiness[]
  items: ProviderReadinessItem[]
  recommended_actions: string[]
}

export interface PaginatedList<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface IntegrationProvider {
  id: string
  tenant_id: string | null
  provider_type: string
  name: string
  config_json: Record<string, any>
  is_enabled: boolean
  last_sync_at: string | null
  created_at: string
  updated_at: string
}

export interface IntegrationProviderCreateInput {
  provider_type: string
  name: string
  config_json: Record<string, any>
  is_enabled?: boolean
}

export interface IntegrationTestResult {
  status: string
  message: string
  details?: Record<string, any> | null
}

export interface IntegrationSyncResult {
  success: boolean
  status: string
  message: string
  last_sync_at?: string
  details?: Record<string, any> | null
}

export interface IntegrationProjectBindingCreateInput {
  project_id: string
  name: string
  scope: Record<string, any>
  field_mapping: Record<string, string>
  is_enabled?: boolean
}

export interface IntegrationProjectBinding {
  id: string
  tenant_id: string | null
  integration_provider_id: string
  project_id: string
  name: string
  scope_json: Record<string, any>
  field_mapping_json: Record<string, string>
  cursor_json: Record<string, any>
  is_enabled: boolean
  last_sync_status: string | null
  last_synced_at: string | null
  last_error: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface IntegrationNormalizedItem {
  external_id: string
  title: string
  content: string
  external_url: string | null
  external_updated_at: string | null
  metadata: Record<string, any>
}

export interface IntegrationSyncPreview {
  binding_id: string
  total: number
  items: IntegrationNormalizedItem[]
  cursor: Record<string, any>
}

export interface IntegrationProjectSyncRun {
  id: string
  tenant_id: string | null
  binding_id: string
  status: 'running' | 'completed' | 'partial' | 'failed' | string
  mode: string
  cursor_before_json: Record<string, any>
  cursor_after_json: Record<string, any>
  total_count: number
  created_count: number
  updated_count: number
  unchanged_count: number
  failed_count: number
  error_message: string | null
  details_json: Record<string, any>
  requested_by: string | null
  started_at: string
  completed_at: string | null
  created_at: string
}

export interface IntegrationOperationsEvidence {
  integration_count: number
  enabled_integration_count: number
  configured_integration_count: number
  synced_integration_count: number
  webhook_count: number
  active_webhook_count: number
  successful_delivery_count: number
  failed_delivery_count: number
  pending_outbox_count: number
  failed_outbox_count: number
  project_binding_count?: number
  completed_project_sync_count?: number
  synced_asset_count?: number
}

export interface IntegrationOperationsSummary {
  status: string
  score: number
  summary: string
  evidence: IntegrationOperationsEvidence
  blockers: string[]
  recommended_actions: string[]
}

export interface IntegrationProductionReleaseGate {
  status: 'passed' | 'attention' | 'blocked' | string
  label: string
  summary: string
  blockers: string[]
  warnings: string[]
}

export interface IntegrationProductionRiskItem {
  code: string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  title: string
  detail: string
  count: number
  href: string
}

export interface IntegrationProductionPriorityAction {
  code: string
  title: string
  description: string
  href: string
  priority: 'critical' | 'high' | 'medium' | 'low' | string
}

export interface IntegrationProductionCommandCenter {
  release_gate: IntegrationProductionReleaseGate
  summary: Record<string, number>
  risk_items: IntegrationProductionRiskItem[]
  priority_actions: IntegrationProductionPriorityAction[]
  operations_summary: IntegrationOperationsSummary
}

export interface WebhookSubscription {
  id: string
  tenant_id: string | null
  integration_provider_id: string
  url: string
  events: string[]
  is_active: boolean
  secret?: string | null
  created_at: string
  updated_at: string
}

export interface WebhookSubscriptionCreateInput {
  url: string
  events: string[]
  is_active?: boolean
  secret?: string | null
}

export interface OutboxEvent {
  id: string
  tenant_id: string | null
  aggregate_type: string
  aggregate_id: string
  event_type: string
  payload: Record<string, any>
  published: boolean
  published_at: string | null
  created_at: string
}

export interface CapabilityReadinessItem {
  key: string
  label: string
  status: 'ready' | 'degraded' | 'blocked' | string
  score: number
  summary: string
  evidence: Record<string, any>
  blockers: string[]
  recommended_actions: string[]
}

export interface CapabilityReadiness {
  generated_at: string
  tenant_id: string | null
  overall_status: 'ready' | 'degraded' | 'blocked' | string
  overall_score: number
  production_ready: boolean
  capabilities: CapabilityReadinessItem[]
}

export interface CapabilityActivationAction {
  key: string
  label: string
  capability_key: string
  action_type: 'safe' | 'manual' | string
  status: 'planned' | 'completed' | 'skipped' | 'manual' | 'blocked' | 'failed' | 'running' | string
  can_execute: boolean
  requires_confirmation: boolean
  description: string
  evidence: Record<string, any>
  result: Record<string, any>
}

export interface CapabilityActivationRequest {
  dry_run?: boolean
  confirm?: boolean
  actions?: string[] | null
}

export interface CapabilityActivationResponse {
  generated_at: string
  tenant_id: string | null
  dry_run: boolean
  executed: boolean
  readiness_before: CapabilityReadiness
  readiness_after: CapabilityReadiness | null
  actions: CapabilityActivationAction[]
  summary: Record<string, any>
  next_steps: string[]
}

export interface CapabilityCommissioningAction {
  label: string
  href: string
  api_endpoint?: string | null
  method?: string | null
  description: string
}

export interface CapabilityCommissioningCheck {
  key: string
  capability_key: string
  label: string
  status: 'passed' | 'failed' | 'warning' | 'not_run' | string
  severity: 'critical' | 'high' | 'medium' | 'info' | string
  summary: string
  evidence: Record<string, any>
  blockers: string[]
  action: CapabilityCommissioningAction
  can_run: boolean
  configuration_requirements?: Record<string, any>
  validation_steps?: string[]
  evidence_requirements?: string[]
  run_status?: 'passed' | 'failed' | 'skipped' | string | null
  run_result: Record<string, any>
}

export interface CapabilityCommissioningRunRequest {
  checks?: string[] | null
}

export interface CapabilityCommissioningResponse {
  generated_at: string
  tenant_id: string | null
  production_usable: boolean
  executed: boolean
  overall_status: 'ready' | 'degraded' | 'blocked' | string
  overall_score: number
  readiness: CapabilityReadiness
  checks: CapabilityCommissioningCheck[]
  summary: Record<string, any>
  next_steps: string[]
}

export interface ProductionOpsReleaseGate {
  status: 'ready' | 'attention' | 'blocked' | string
  can_release: boolean
  readiness_score: number
  commissioning_score: number
  summary: string
}

export interface ProductionOpsBlocker {
  key: string
  capability_key: string
  label: string
  severity: 'critical' | 'high' | 'medium' | 'info' | string
  source: 'readiness' | 'commissioning' | string
  summary: string
  action_label?: string | null
  action_href?: string | null
  api_endpoint?: string | null
}

export interface ProductionOpsPriorityAction {
  key: string
  label: string
  href: string
  capability_key: string
  severity: 'critical' | 'high' | 'medium' | 'info' | string
  description: string
  api_endpoint?: string | null
}

export interface ProductionOpsCommandCenter {
  generated_at: string
  tenant_id: string | null
  release_gate: ProductionOpsReleaseGate
  summary: Record<string, number>
  blockers: ProductionOpsBlocker[]
  priority_actions: ProductionOpsPriorityAction[]
  readiness: CapabilityReadiness
  commissioning: CapabilityCommissioningResponse
  next_steps: string[]
}

export interface QuotaCommandCenterGate {
  status: 'passed' | 'attention' | 'blocked' | string
  can_operate: boolean
  label: string
  summary: string
  blockers: string[]
  warnings: string[]
}

export interface QuotaCommandCenterSummary {
  api_used: number
  api_limit: number
  api_remaining: number
  api_usage_percent: number
  total_requests: number
  successful_requests: number
  failed_requests: number
  failure_rate_percent: number
  average_latency_ms: number
  daily_burn: number
  projected_days_remaining: number | null
  risky_endpoint_count: number
  provider_risk_count: number
  open_breaker_count: number
}

export interface QuotaCommandCenterRisk {
  code: string
  severity: 'critical' | 'high' | 'medium' | string
  title: string
  detail: string
  count: number
  href: string
}

export interface QuotaCommandCenterAction {
  code: string
  title: string
  description: string
  href: string
  priority: 'critical' | 'high' | 'medium' | string
}

export interface QuotaCommandCenterRateLimitRisk {
  endpoint: string
  limit: number
  remaining: number
  used_percentage: number
  reset_at: string
}

export interface QuotaCommandCenter {
  generated_at: string
  tenant_id: string
  release_gate: QuotaCommandCenterGate
  summary: QuotaCommandCenterSummary
  risk_items: QuotaCommandCenterRisk[]
  priority_actions: QuotaCommandCenterAction[]
  rate_limit_risks: QuotaCommandCenterRateLimitRisk[]
}

export interface Agent {
  id: string
  name: string
  description: string
  skills: string[]
  status: 'idle' | 'running' | 'error'
}

export interface AgentRunResult {
  id: string
  run_id?: string
  status?: AgentRun['status']
  output: string
  artifacts: any[]
}

export interface AgentRunCommandResult {
  run_id: string
  status: AgentRun['status']
  message: string
}

export interface AgentRunRetryResult {
  run_id: string
  status: AgentRun['status']
  message: string
}

export interface Export {
  id: string
  projectId: string
  format: string
  status: 'pending' | 'completed' | 'failed'
  url?: string
  createdAt: string
}

export interface Comment {
  id: string
  documentId: string
  authorId: string
  content: string
  anchor?: string | null
  parentCommentId?: string | null
  resolved: boolean
  createdAt: string
}

function normalizeComment(item: any): Comment {
  return {
    ...item,
    documentId: item.documentId ?? item.document_id,
    authorId: item.authorId ?? item.user_id,
    parentCommentId: item.parentCommentId ?? item.parent_comment_id ?? null,
    resolved: item.resolved ?? item.is_resolved ?? false,
    createdAt: item.createdAt ?? item.created_at,
  }
}

export interface CollaborationMember {
  id: string
  name: string
  email: string
  role: '项目经理' | '业务顾问' | '技术顾问' | '客户评审人' | string
  status: 'online' | 'pending' | 'offline' | string
  pending_count: number
  current_focus: string
}

export interface CollaborationReviewItem {
  id: string
  document_id: string
  project_id: string
  title: string
  document_type: 'BRD' | 'PRD' | '验收报告' | string
  owner: string
  role: string
  status: 'PASSED' | 'BLOCKED' | 'PASSED_WITH_FOLLOW_UPS' | string
  priority: 'low' | 'medium' | 'high' | 'critical' | string
  pending_comments: number
  snapshot_count?: number
  baseline_count?: number
  updated_at: string
  summary: string
  acceptance_decision: string
  action_href?: string
}

export interface CollaborationCommentTodo {
  id: string
  document_id?: string
  document_title: string
  assignee: string
  count: number
  due: string
  action_href: string
}

export interface CollaborationActivity {
  id: string
  actor: string
  action: string
  target: string
  created_at: string
}

export interface CollaborationAcceptanceDecision {
  id: string
  label: string
  status: 'PASSED' | 'BLOCKED' | 'PASSED_WITH_FOLLOW_UPS' | string
  count: number
}

export interface CollaborationReviewHub {
  members: CollaborationMember[]
  review_queue: CollaborationReviewItem[]
  comment_todos: CollaborationCommentTodo[]
  recent_activities: CollaborationActivity[]
  acceptance_decisions: CollaborationAcceptanceDecision[]
}

export interface CollaborationAcceptanceSummary {
  total_reviews: number
  passed_reviews: number
  blocked_reviews: number
  follow_up_reviews: number
  pending_comments: number
  open_work_items: number
  overdue_work_items: number
  unassigned_work_items: number
  active_members: number
}

export interface CollaborationAcceptanceGate {
  status: 'passed' | 'attention' | 'blocked' | string
  label: string
  summary: string
  blockers: string[]
  warnings: string[]
}

export interface CollaborationAcceptanceRisk {
  code: string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  title: string
  detail: string
  count: number
  href: string
}

export interface CollaborationAcceptanceAction {
  code: string
  title: string
  description: string
  href: string
  priority: 'critical' | 'high' | 'medium' | 'low' | string
}

export interface CollaborationAcceptanceCommandCenter {
  release_gate: CollaborationAcceptanceGate
  summary: CollaborationAcceptanceSummary
  risk_items: CollaborationAcceptanceRisk[]
  priority_actions: CollaborationAcceptanceAction[]
  review_queue: CollaborationReviewItem[]
  comment_todos: CollaborationCommentTodo[]
  acceptance_decisions: CollaborationAcceptanceDecision[]
}

export type CollaborationReviewAction = 'assign-me' | 'mark-read' | 'pass-acceptance' | 'return-revision'

export interface CollaborationWorkItem {
  id: string
  tenant_id: string
  project_id: string
  document_id?: string | null
  comment_id?: string | null
  assigned_to?: string | null
  assigned_to_name?: string | null
  created_by: string
  project_name?: string
  work_type: 'review' | 'comment_resolution' | 'follow_up' | 'manual' | string
  status: 'open' | 'in_progress' | 'blocked' | 'done' | 'cancelled' | string
  priority: 'low' | 'medium' | 'high' | 'critical' | string
  title: string
  description: string
  due_at?: string | null
  completed_at?: string | null
  source_key?: string | null
  metadata_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CollaborationWorkItemBoard {
  items: CollaborationWorkItem[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  mine_count: number
  unassigned_count: number
  overdue_count: number
  status_counts: Record<string, number>
}

export interface CollaborationWorkItemCreate {
  project_id: string
  document_id?: string
  comment_id?: string
  assigned_to?: string
  title: string
  description?: string
  work_type?: string
  priority?: string
  due_at?: string
}

export interface Version {
  id: string
  documentId: string
  versionNumber: number
  description: string
  content?: string
  createdBy: string
  createdAt: string
}

export interface DocumentBaseline {
  id: string
  documentId: string
  versionId: string
  name: string
  reason?: string | null
  approvedBy?: string | null
  approvedAt?: string | null
  createdAt: string
}

export interface DocumentSnapshot {
  id: string
  documentId: string
  userId: string
  snapshotData: Record<string, any>
  snapshotType: 'auto' | 'manual'
  version: number
  createdAt: string
}

function normalizeDocumentSnapshot(item: any): DocumentSnapshot {
  return {
    ...item,
    documentId: item.documentId ?? item.document_id,
    userId: item.userId ?? item.user_id,
    snapshotData: item.snapshotData ?? item.snapshot_data ?? {},
    snapshotType: item.snapshotType ?? item.snapshot_type,
    createdAt: item.createdAt ?? item.created_at,
  }
}

export interface DocumentStatusTransition {
  from_status: string
  to_status: string
  action: string
  reason?: string | null
  changed_by?: string | null
  changed_at: string
  unresolved_comment_count: number
  policy_revision: number
}

export interface ProjectDocumentLifecycleStatus {
  key: string
  label: string
}

export interface ProjectDocumentLifecycleTransition {
  from_status: string
  to_status: string
}

export interface ProjectDocumentLifecyclePublishGates {
  require_approved: boolean
  require_resolved_comments: boolean
  require_resolved_placeholders: boolean
}

export interface ProjectDocumentLifecyclePolicyUpdate {
  statuses: ProjectDocumentLifecycleStatus[]
  transitions: ProjectDocumentLifecycleTransition[]
  require_reason_for: string[]
  publish_gates: ProjectDocumentLifecyclePublishGates
}

export interface ProjectDocumentLifecyclePolicy extends ProjectDocumentLifecyclePolicyUpdate {
  revision: number
}

export interface DocumentStatusCapability {
  status: string
  label: string
  permission_action: string
  allowed: boolean
  authorization_reason: string
  blockers: string[]
}

export interface DocumentStatusCapabilities {
  current_status: string
  policy_revision: number
  capabilities: DocumentStatusCapability[]
}

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy'
  timestamp: string
}

export interface PlatformMetrics {
  timestamp: string
  total_tenants: number
  active_users_24h: number
  total_api_calls_24h: number
  error_rate_percent: number
  avg_latency_ms: number
}

export interface QuotaStatus {
  used: number
  limit: number
  resetAt: string
}

export interface AgentRun {
  id: string
  tenant_id: string | null
  project_id: string | null
  workflow_version_id: string | null
  agent_profile_id?: string | null
  workflow?: {
    version_id: string
    workflow_definition_id: string
    workflow_name?: string | null
    category?: string | null
    version?: number | null
    is_active?: boolean
  } | null
  agent_profile?: {
    id: string
    name: string
    agent_type: string
    status: string
    applicable_doc_types?: string[]
  } | null
  agent_name?: string | null
  run_type?: 'workflow' | 'agent_profile' | 'direct_skill' | string
  metadata_json?: Record<string, any>
  input_data: Record<string, any>
  output_data?: Record<string, any> | null
  progress_percent?: number | null
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  created_at: string
  task_summary?: AgentRunTaskSummary
  event_summary?: AgentRunEventSummary
  duration_ms?: number | null
  can_retry?: boolean
  can_cancel?: boolean
  gate_summary?: Record<string, any>
  can_resume?: boolean
  requires_human_action?: boolean
  status_hint?: string | null
}

export interface AgentRunTaskSummary {
  total: number
  pending: number
  running: number
  completed: number
  failed: number
  last_task_id?: string | null
  last_task_status?: string | null
  last_error_message?: string | null
}

export interface AgentRunEventSummary {
  total: number
  last_event_type?: string | null
  last_event_at?: string | null
}

export interface AgentRunControlActionInput {
  action: 'approve' | 'reject' | 'resume' | 'skip'
  node_id?: string | null
  comment?: string | null
  output_data?: Record<string, any>
}

export interface OrchestrationKpis {
  active_agents: number
  published_skills: number
  active_workflows: number
  executable_workflows: number
  total_runs: number
  running_runs: number
  failed_runs: number
  recoverable_runs: number
}

export interface OrchestrationRecommendation {
  severity: 'critical' | 'high' | 'medium' | 'info' | string
  code: string
  title: string
  detail: string
  action_label?: string | null
  action_href?: string | null
}

export interface OrchestrationDashboard {
  generated_at: string
  readiness_score: number
  kpis: OrchestrationKpis
  run_status_counts: Record<string, number>
  workflow_category_counts: Record<string, number>
  recent_runs: AgentRun[]
  recommendations: OrchestrationRecommendation[]
  template_count: number
}

export interface OrchestrationBootstrapResult {
  message: string
  initialized: {
    published_skills?: number
    active_agents?: number
    executable_agents?: number
    active_workflows?: number
    executable_workflows?: number
    [key: string]: number | undefined
  }
  dashboard: OrchestrationDashboard
}

export interface AgentEvent {
  id: string
  agent_run_id: string
  tenant_id: string | null
  event_type: string
  event_data: Record<string, any>
  created_at: string
}

export interface SkillCatalogTestResult {
  skill_id: string
  skill_name: string
  success: boolean
  output_data: Record<string, any> | null
  error_message: string | null
  execution_time_ms: number | null
  mode: string
  run_id?: string | null
  task_id?: string | null
}

export interface SkillCatalogEntry {
  id: string
  tenant_id: string | null
  name: string
  display_name: string | null
  effective_display_name: string
  description: string | null
  skill_type: string
  category: string
  input_schema_json: Record<string, any>
  output_schema_json: Record<string, any>
  supported_doc_types: string[]
  supported_industries: string[]
  version: string
  status: 'draft' | 'published' | 'disabled' | string
  is_builtin: boolean
  governance_scope: 'system' | 'platform' | 'tenant' | 'project' | 'personal' | string
  visibility: string
  managed_by: string
  is_locked: boolean
  can_edit: boolean
  can_publish: boolean
  can_disable: boolean
  locked_reason: string | null
  implementation_ref: string | null
  metadata_json: Record<string, any>
  last_test_at?: string | null
  last_test_result?: 'passed' | 'failed' | 'unknown' | string | null
  created_by: string
  created_at: string | null
  updated_at: string | null
  deleted_at: string | null
}

export interface SkillCatalogCreateInput {
  name: string
  display_name?: string
  description?: string
  skill_type?: string
  category?: string
  input_schema_json?: Record<string, any>
  output_schema_json?: Record<string, any>
  supported_doc_types?: string[]
  supported_industries?: string[]
  version?: string
  status?: string
  governance_scope?: string
  visibility?: string
  implementation_ref?: string
  metadata_json?: Record<string, any>
}

export interface DocumentGenerationSessionCreateInput {
  project_id: string
  doc_type: string
  title?: string
  template_id?: string | null
  context?: Record<string, any>
}

export interface DocumentGenerationMessageInput {
  message: string
  action?: 'answer' | 'confirm' | 'skip' | 'revise' | string
}

export interface DocumentGenerationSection {
  id: string
  tenant_id: string | null
  session_id: string
  section_key: string
  title: string
  position: number
  status: 'pending' | 'drafted' | 'confirmed' | 'skipped' | string
  prompt: string
  content_requirement: string
  content: string
  pending_questions_json: string[]
  confirmed_facts_json: string[]
  quality_json: Record<string, any>
  required_inputs: string[]
  quality_rules: Record<string, any>[]
  created_at: string
  updated_at: string
}

export interface DocumentGenerationStep {
  id: string
  tenant_id: string | null
  session_id: string
  step_index: number
  role: 'user' | 'assistant' | string
  action_type: string
  section_key: string | null
  message: string
  patch_json: Record<string, any>
  quality_json: Record<string, any>
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface DocumentGenerationSession {
  id: string
  tenant_id: string | null
  project_id: string
  document_id: string | null
  template_id: string | null
  doc_type: string
  title: string
  status: 'active' | 'finalized' | 'cancelled' | string
  generation_mode: string
  current_section_key: string | null
  context_json: Record<string, any>
  stash_json: Record<string, any>
  quality_summary_json: Record<string, any>
  created_by: string
  finalized_at: string | null
  created_at: string
  updated_at: string
  sections: DocumentGenerationSection[]
  steps: DocumentGenerationStep[]
}

export interface DocumentGenerationTurnResult {
  session: DocumentGenerationSession
  current_section: DocumentGenerationSection
  assistant_message: string
  section_summaries: Record<string, any>[]
  write_log: Record<string, any>[]
  skill_trace: Record<string, any>[]
  quality_gate: Record<string, any>
  pending_confirmations: Record<string, any>[]
}

export interface AgentSkillBinding {
  id: string
  tenant_id: string | null
  agent_profile_id: string
  skill_id: string
  order_index: number
  is_required: boolean
  skill: SkillCatalogEntry | null
}

export interface AgentProfile {
  id: string
  tenant_id: string | null
  name: string
  description: string | null
  agent_type: string
  applicable_doc_types: string[]
  default_template_id: string | null
  tool_names: string[]
  workflow_definition_id: string | null
  human_review_required: boolean
  status: 'draft' | 'active' | 'disabled' | string
  system_prompt: string | null
  created_by: string
  skill_bindings: AgentSkillBinding[]
  last_run?: AgentRun | null
  created_at: string | null
  updated_at: string | null
  deleted_at: string | null
}

export interface AgentProfileCreateInput {
  name: string
  description?: string
  agent_type?: string
  applicable_doc_types?: string[]
  default_template_id?: string | null
  tool_names?: string[]
  workflow_definition_id?: string | null
  human_review_required?: boolean
  status?: string
  system_prompt?: string
  skill_ids?: string[]
}

export interface AgentTask {
  id: string
  agent_run_id: string
  tenant_id: string | null
  node_id: string
  skill_name: string | null
  tool_name: string | null
  input_data: Record<string, any>
  output_data: Record<string, any> | null
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  retries: number
  max_retries: number
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface WorkflowDefinition {
  id: string
  name: string
  description?: string | null
  category?: string
  version_count?: number
  graph_data?: any
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface WorkflowTemplate {
  template_id: string
  name: string
  display_name: string
  description: string
  category: string
  dag_json: any
  node_count: number
  skill_names: string[]
  recommended_doc_types: string[]
  readiness_checks: string[]
}

export interface WorkflowVersion {
  id: string
  workflow_definition_id: string
  version: number
  dag_json: any
  skill_contracts_json: any[]
  tool_contracts_json: any[]
  is_active: boolean
  created_at: string
}

export interface WorkflowDagValidationIssue {
  severity: 'error' | 'warning' | string
  code?: string
  node_id: string | null
  message: string
}

export interface WorkflowDagValidation {
  valid: boolean
  issues: WorkflowDagValidationIssue[]
  execution_order: string[]
}

export interface WorkflowDagPreview {
  valid: boolean
  issues: WorkflowDagValidationIssue[]
  execution_order: string[]
  parallel_groups: Array<{ group_id: string; node_ids: string[]; label?: string }>
  approval_gates: Array<{ node_id: string; label: string; approver_role?: string; required?: boolean }>
  condition_paths: Array<{ node_id: string; expression: string; true_path?: string[]; false_path?: string[] }>
  estimated_steps: number
  blocking_issues: WorkflowDagValidationIssue[]
}

export interface WorkflowProductionPreflightCheck {
  code: string
  severity: 'critical' | 'high' | 'medium' | 'info' | string
  title: string
  detail: string
  status: 'passed' | 'warning' | 'failed' | string
  action_label?: string | null
  action_href?: string | null
}

export interface WorkflowProductionPreflight {
  workflow_id: string
  workflow_name: string
  project_id: string | null
  active_version_id: string | null
  release_gate: {
    status: 'passed' | 'attention' | 'blocked' | string
    label: string
    summary: string
    blockers: string[]
    warnings: string[]
  }
  preview: WorkflowDagPreview
  checks: WorkflowProductionPreflightCheck[]
  recent_runs: AgentRun[]
  next_actions: WorkflowProductionPreflightCheck[]
}

export interface AuditLog {
  id: string
  tenant_id: string | null
  user_id: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  extra_data: Record<string, any> | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

export interface TenantMetrics {
  tenant_id: string
  timestamp: string
  api_calls_today: number
  api_calls_this_month: number
  storage_used_bytes: number
  storage_limit_bytes: number
  document_count: number
  user_count: number
  active_agents: number
}

export interface QuotaUsage {
  quota_type: string
  used_amount: number
  limit_amount: number
  period: string
  reset_at: string
}

export interface UsageStatsResult {
  tenant_id: string
  timestamp: string
  total_requests: number
  successful_requests: number
  failed_requests: number
  average_latency_ms: number
}

export interface RateLimitsResult {
  tenant_id: string
  timestamp: string
  rate_limits: Array<{
    endpoint: string
    limit: number
    remaining: number
    reset_at: string
  }>
}

export interface ChangeRequest {
  id: string
  project_id: string
  title?: string
  change_type?: string
  description: string
  status: 'draft' | 'open' | 'approved' | 'rejected' | 'applied' | 'cancelled'
  priority: 'critical' | 'low' | 'medium' | 'high'
  requested_by: string
  created_at: string
  updated_at: string
}

export interface ChangeAuditCommandCenterSummary {
  total_changes: number
  draft_changes: number
  open_changes: number
  approved_unapplied_changes: number
  critical_or_high_open_changes: number
  pending_field_patches: number
  open_impact_analyses: number
  critical_or_high_open_impacts: number
  pending_sync_proposals: number
}

export interface ChangeAuditReleaseGate {
  status: 'passed' | 'attention' | 'blocked' | string
  label: string
  summary: string
  blockers: string[]
  warnings: string[]
}

export interface ChangeAuditRiskItem {
  code: string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  title: string
  detail: string
  count: number
  href: string
}

export interface ChangeAuditPriorityAction {
  code: string
  title: string
  description: string
  href: string
  priority: 'critical' | 'high' | 'medium' | 'low' | string
}

export interface ChangeAuditCommandCenter {
  scope: 'tenant' | 'project' | string
  project_id?: string | null
  release_gate: ChangeAuditReleaseGate
  summary: ChangeAuditCommandCenterSummary
  change_status_counts: Record<string, number>
  priority_counts: Record<string, number>
  impact_level_counts: Record<string, number>
  risk_items: ChangeAuditRiskItem[]
  priority_actions: ChangeAuditPriorityAction[]
}

export interface TraceabilityRow {
  id: string
  urs_doc_id: string | null
  brd_doc_id: string | null
  prd_doc_id: string | null
  user_story_doc_id: string | null
  design_doc_id: string | null
  interface_doc_id: string | null
  data_dict_doc_id: string | null
  test_case_doc_id: string | null
  status: 'complete' | 'in_progress' | 'blocked'
}

export interface TraceabilityCoverageSummary {
  total_documents: number
  published_documents: number
  referenced_documents: number
  orphan_documents: number
  coverage_rate: number
  open_impact_analyses: number
  pending_sync_proposals: number
}

export interface TraceabilityGapItem {
  code: 'missing_upstream' | 'missing_downstream' | 'unpublished' | 'orphan_document' | string
  severity: 'low' | 'medium' | 'high' | string
  document_id: string
  document_title: string
  document_type: string
  reason: string
  suggested_action: string
  related_document_id?: string | null
  related_document_title?: string | null
  related_document_type?: string | null
}

export interface TraceabilityReferenceSuggestion {
  id: string
  source_document_id: string
  source_document_title: string
  source_document_type: string
  target_document_id: string
  target_document_title: string
  target_document_type: string
  reference_type: string
  reason: string
  suggested_action: string
}

export interface TraceabilityCoverage {
  summary: TraceabilityCoverageSummary
  gaps: TraceabilityGapItem[]
  suggestions: TraceabilityReferenceSuggestion[]
}

export interface TraceabilitySuggestionAcceptanceItem {
  suggestion_id: string
  source_document_id: string
  target_document_id: string
  reference_type: string
  status: 'created' | 'skipped' | string
  reference_id?: string | null
  reason?: string | null
}

export interface TraceabilitySuggestionAcceptance {
  created: number
  skipped: number
  items: TraceabilitySuggestionAcceptanceItem[]
}

export interface DocumentReferenceCreatePayload {
  target_document_id: string
  reference_type?: string
  source_section?: string
  target_section?: string
  metadata?: Record<string, any>
}

export interface DocumentReference {
  id: string
  tenant_id?: string | null
  project_id: string
  source_document_id: string
  source_document_version: number
  target_document_id: string
  target_document_version: number
  reference_type: string
  source_section?: string | null
  target_section?: string | null
  status: 'active' | 'archived' | string
  created_by: string
  metadata_json: Record<string, any>
  created_at: string
  updated_at: string
}

export interface DocumentSyncProposal {
  id: string
  tenant_id?: string | null
  impact_analysis_id: string
  project_id: string
  reference_id?: string | null
  source_document_id: string
  target_document_id: string
  target_document_version: number
  result_document_version?: number | null
  target_section?: string | null
  impact_level: 'low' | 'medium' | 'high' | string
  reason: string
  suggested_action: string
  candidate_content?: string | null
  status: 'pending' | 'applied' | 'rejected' | string
  decided_by?: string | null
  decided_at?: string | null
  decision_note?: string | null
  metadata_json: Record<string, any>
  created_at: string
  updated_at: string
}

export interface DocumentImpactAnalysis {
  id: string
  tenant_id?: string | null
  project_id: string
  trigger_document_id: string
  trigger_document_version: number
  change_request_id?: string | null
  trigger_type: string
  impact_level: 'low' | 'medium' | 'high' | string
  status: 'open' | 'resolved' | string
  summary?: string | null
  analysis_json: Record<string, any>
  created_by: string
  resolved_at?: string | null
  created_at: string
  updated_at: string
  proposals: DocumentSyncProposal[]
}

export interface DocumentImpactAnalysisCreatePayload {
  trigger_type?: string
  summary?: string
  change_request_id?: string
}

export interface SyncProposalDecisionPayload {
  decision_note?: string
  candidate_content?: string
}

export interface TenantUser {
  id: string
  email: string
  full_name: string
  tenant_id: string
  is_active: boolean
  roles: Role[]
  created_at: string
}

export interface Role {
  id: string
  tenant_id?: string | null
  name: string
  description: string | null
  permissions: string[] | Record<string, any>
  created_at: string
  updated_at?: string
}

export interface UserCreatePayload {
  email: string
  password: string
  full_name?: string
  tenant_id?: string
}

export interface RoleCreatePayload {
  name: string
  description?: string
  permissions?: Record<string, any>
}

export interface TenantApiKey {
  id: string
  tenant_id?: string | null
  name: string
  key_prefix: string
  permissions: string[]
  status: 'active' | 'revoked' | string
  created_by_id?: string | null
  revoked_by_id?: string | null
  last_used_at?: string | null
  expires_at?: string | null
  revoked_at?: string | null
  created_at: string
  updated_at: string
}

export interface TenantApiKeyCreatePayload {
  name: string
  permissions: string[]
  expires_at?: string | null
}

export interface TenantApiKeyCreateResponse extends TenantApiKey {
  api_key: string
}

export interface Policy {
  id: string
  tenant_id?: string | null
  name: string
  description: string | null
  effect: 'allow' | 'deny' | string
  actions: string[]
  resources: string[]
  conditions: Record<string, any>
  created_at: string
  updated_at?: string
}

export interface PolicyCreatePayload {
  name: string
  description?: string
  effect: 'allow' | 'deny'
  actions: string[]
  resources: string[]
  conditions?: Record<string, any>
}

export interface FieldPermission {
  id: string
  tenant_id?: string | null
  role_id: string
  resource_type: string
  field_name: string
  permission: 'read' | 'write' | 'none' | string
  created_at: string
  updated_at?: string
}

export interface FieldPermissionCreatePayload {
  role_id: string
  resource_type: string
  field_name: string
  permission: 'read' | 'write' | 'none'
}

export interface PermissionDiagnosticCheck {
  key: string
  label: string
  resource: string
  action: string
  allowed: boolean
  reason: string
}

export interface PermissionDiagnosticFieldControl {
  role_id: string
  role_name: string
  resource_type: string
  field_name: string
  permission: 'read' | 'write' | 'none' | string
}

export interface PermissionDiagnosticPolicyEvidence {
  id: string
  name: string
  effect: 'allow' | 'deny' | string
  actions: string[]
  resources: string[]
}

export interface PermissionDiagnostics {
  generated_at: string
  tenant_id?: string | null
  user_id: string
  summary: {
    total: number
    allowed: number
    denied: number
    field_restricted: number
  }
  checks: PermissionDiagnosticCheck[]
  field_controls: PermissionDiagnosticFieldControl[]
  policy_evidence: PermissionDiagnosticPolicyEvidence[]
}

export interface PermissionCommandCenterGate {
  status: 'passed' | 'attention' | 'blocked' | string
  label: string
  summary: string
  blockers: string[]
  warnings: string[]
}

export interface PermissionCommandCenterRisk {
  code: string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  title: string
  detail: string
  count: number
  href: string
}

export interface PermissionCommandCenterAction {
  code: string
  title: string
  description: string
  href: string
  priority: 'critical' | 'high' | 'medium' | 'low' | string
}

export interface PermissionCommandCenter {
  generated_at: string
  tenant_id?: string | null
  release_gate: PermissionCommandCenterGate
  summary: Record<string, number>
  risk_items: PermissionCommandCenterRisk[]
  priority_actions: PermissionCommandCenterAction[]
  diagnostic_snapshot: Record<string, number>
  recent_audit_actions: string[]
}

export interface PermissionSimulationInput {
  user_id: string
  resource: string
  action: string
  resource_type?: string | null
  field_name?: string | null
}

export interface PermissionSimulationRoleEvidence {
  id: string
  name: string
  description: string | null
  permissions: Record<string, any>
}

export interface PermissionSimulationResult {
  generated_at: string
  tenant_id?: string | null
  requested_by_user_id: string
  target_user_id: string
  target_user_email: string
  target_user_name: string | null
  resource: string
  action: string
  allowed: boolean
  reason: string
  roles: PermissionSimulationRoleEvidence[]
  field_controls: PermissionDiagnosticFieldControl[]
  policy_evidence: PermissionDiagnosticPolicyEvidence[]
}

export interface AuthMeResponse {
  id: string
  email: string
  full_name: string
  tenant_id: string
  is_active: boolean
  roles: Role[]
}

export interface Tenant {
  id: string
  name: string
  domain: string | null
  description: string | null
  is_active: boolean
  created_at: string
}

export interface DocumentStatistics {
  total_documents: number
  by_type: Record<string, number>
  by_status: Record<string, number>
}

export interface ExportJob {
  id: string
  tenant_id: string | null
  project_id: string
  document_id: string | null
  template_id: string | null
  export_type: string
  title?: string | null
  status: 'pending' | 'processing' | 'completed' | 'failed'
  output_path: string | null
  file_hash: string | null
  error_message: string | null
  created_at: string
  completed_at: string | null
  artifacts?: Array<{
    id: string
    filename: string
    content_type: string
    file_size: number
  }>
}

export interface ProjectPackageExportPayload {
  project_id: string
  document_ids?: string[]
  title?: string
  formats?: Array<'word' | 'markdown' | 'pptx'>
  include_drafts?: boolean
  include_manifest?: boolean
  include_audit?: boolean
  watermark?: string
  variables?: Record<string, any>
}

export interface ExportJobStatus {
  job_id: string
  status: string
  progress_percent: number
  message: string | null
  completed_at: string | null
}

export interface ExportReadinessBlocker {
  document_id: string
  title: string
  doc_type: string
  status: string
  reason: string
  recommended_action: string
}

export interface ExportReadinessRequiredType {
  doc_type: string
  label: string
  ready_count: number
  blocked_count: number
  status: 'ready' | 'blocked' | 'missing' | string
}

export interface ExportReadiness {
  project_id: string
  total_documents: number
  exportable_documents: number
  blocked_documents: number
  readiness_score: number
  can_export_production: boolean
  missing_required_types: string[]
  required_types: ExportReadinessRequiredType[]
  blockers: ExportReadinessBlocker[]
  recommended_actions: string[]
}

export interface ExportReleaseEvidenceSummary {
  total_jobs: number
  completed_jobs: number
  failed_jobs: number
  artifact_count: number
  covered_formats: string[]
  missing_formats: string[]
  production_package_jobs: number
  latest_completed_at?: string | null
}

export interface ExportReleaseGate {
  status: 'passed' | 'attention' | 'blocked' | string
  label: string
  summary: string
  blockers: string[]
  warnings: string[]
}

export interface ExportReleaseRiskItem {
  code: string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  title: string
  detail: string
  count: number
  href: string
}

export interface ExportReleasePriorityAction {
  code: string
  title: string
  description: string
  href: string
  priority: 'critical' | 'high' | 'medium' | 'low' | string
}

export interface ExportReleaseArtifact {
  id: string
  tenant_id?: string | null
  job_id: string
  filename: string
  content_type: string
  file_size: number
  storage_path?: string
  file_hash?: string | null
  created_at?: string
}

export interface ExportReleaseEvidence {
  project_id: string
  release_gate: ExportReleaseGate
  readiness: ExportReadiness
  summary: ExportReleaseEvidenceSummary
  latest_job?: ExportJob | null
  recent_artifacts: ExportReleaseArtifact[]
  risk_items: ExportReleaseRiskItem[]
  priority_actions: ExportReleasePriorityAction[]
}

export interface SourceFile {
  id: string
  projectId: string
  project_id?: string
  name: string
  filename: string
  type: string
  size: number
  status: 'pending' | 'processing' | 'ready' | 'failed'
  metadata?: Record<string, any>
  ingestionStage?: string
  ingestionSummary?: string
  extractedKnowledgeCount?: number
  requiredAction?: string
  errorMessage?: string | null
  createdAt: string
  created_at?: string
}
