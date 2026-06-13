export const locales = ['zh-CN', 'en-US'] as const;
export type Locale = typeof locales[number];

export const defaultLocale: Locale = 'zh-CN';

// Translation dictionaries
const translations: Record<Locale, Record<string, Record<string, string>>> = {
  'zh-CN': {
    common: {
      save: '保存',
      cancel: '取消',
      delete: '删除',
      edit: '编辑',
      create: '创建',
      search: '搜索',
      loading: '加载中...',
      noData: '暂无数据',
      confirm: '确认',
      success: '操作成功',
      error: '操作失败',
    },
    auth: {
      login: '登录',
      logout: '退出登录',
      email: '邮箱',
      password: '密码',
      rememberMe: '记住我',
      forgotPassword: '忘记密码?',
      loginSuccess: '登录成功',
      loginFailed: '登录失败',
    },
    nav: {
      dashboard: '工作台',
      projects: '项目文档',
      documents: '文档',
      knowledge: '知识库',
      workflows: '工作流',
      settings: '设置',
      audit: '审计',
    },
    project: {
      createProject: '创建项目',
      projectName: '项目名称',
      projectType: '项目类型',
      client: '客户',
      status: '状态',
      members: '成员',
      files: '资料',
      documents: '文档',
      knowledge: '知识库',
      settings: '项目设置',
    },
    document: {
      urs: '用户需求说明',
      brd: '业务需求文档',
      prd: '产品需求文档',
      userStory: '用户故事',
      detailedDesign: '详细设计',
      interfaceDoc: '接口文档',
      dataDictionary: '数据字典',
      testCase: '测试用例',
      draft: '草稿',
      inReview: '审核中',
      approved: '已批准',
      published: '已发布',
      generate: '生成文档',
    },
    knowledge: {
      private: '私有',
      project: '项目可见',
      tenant: '租户可见',
      global: '全局可见',
      pendingReview: '待审核',
      approved: '已通过',
      rejected: '已拒绝',
      promote: '提升可见范围',
    },
    workflow: {
      createWorkflow: '创建工作流',
      editWorkflow: '编辑工作流',
      execute: '执行',
      pending: '待执行',
      running: '执行中',
      completed: '已完成',
      failed: '失败',
      cancelled: '已取消',
    },
    ops: {
      health: '健康状态',
      metrics: '指标',
      quotas: '配额',
      alerts: '告警',
      auditLogs: '审计日志',
    },
    error: {
      notFound: '页面不存在',
      unauthorized: '未授权',
      forbidden: '禁止访问',
      serverError: '服务器错误',
      networkError: '网络错误',
    },
  },
  'en-US': {
    common: {
      save: 'Save',
      cancel: 'Cancel',
      delete: 'Delete',
      edit: 'Edit',
      create: 'Create',
      search: 'Search',
      loading: 'Loading...',
      noData: 'No data',
      confirm: 'Confirm',
      success: 'Operation successful',
      error: 'Operation failed',
    },
    auth: {
      login: 'Login',
      logout: 'Logout',
      email: 'Email',
      password: 'Password',
      rememberMe: 'Remember me',
      forgotPassword: 'Forgot password?',
      loginSuccess: 'Login successful',
      loginFailed: 'Login failed',
    },
    nav: {
      dashboard: 'Dashboard',
      projects: 'Projects',
      documents: 'Documents',
      knowledge: 'Knowledge',
      workflows: 'Workflows',
      settings: 'Settings',
      audit: 'Audit',
    },
    project: {
      createProject: 'Create Project',
      projectName: 'Project Name',
      projectType: 'Project Type',
      client: 'Client',
      status: 'Status',
      members: 'Members',
      files: 'Files',
      documents: 'Documents',
      knowledge: 'Knowledge',
      settings: 'Project Settings',
    },
    document: {
      urs: 'User Requirements',
      brd: 'Business Requirements',
      prd: 'Product Requirements',
      userStory: 'User Story',
      detailedDesign: 'Detailed Design',
      interfaceDoc: 'Interface Doc',
      dataDictionary: 'Data Dictionary',
      testCase: 'Test Case',
      draft: 'Draft',
      inReview: 'In Review',
      approved: 'Approved',
      published: 'Published',
      generate: 'Generate Document',
    },
    knowledge: {
      private: 'Private',
      project: 'Project Visible',
      tenant: 'Tenant Visible',
      global: 'Global Visible',
      pendingReview: 'Pending Review',
      approved: 'Approved',
      rejected: 'Rejected',
      promote: 'Promote Visibility',
    },
    workflow: {
      createWorkflow: 'Create Workflow',
      editWorkflow: 'Edit Workflow',
      execute: 'Execute',
      pending: 'Pending',
      running: 'Running',
      completed: 'Completed',
      failed: 'Failed',
      cancelled: 'Cancelled',
    },
    ops: {
      health: 'Health',
      metrics: 'Metrics',
      quotas: 'Quotas',
      alerts: 'Alerts',
      auditLogs: 'Audit Logs',
    },
    error: {
      notFound: 'Page not found',
      unauthorized: 'Unauthorized',
      forbidden: 'Forbidden',
      serverError: 'Server error',
      networkError: 'Network error',
    },
  },
};

export function getTranslation(
  locale: Locale,
  key: string,
  params?: Record<string, string>
): string {
  const keys = key.split('.');
  let value: any = translations[locale] || translations[defaultLocale];

  for (const k of keys) {
    if (value && typeof value === 'object' && k in value) {
      value = value[k];
    } else {
      return key; // Return key if translation not found
    }
  }

  if (typeof value !== 'string') {
    return key;
  }

  // Interpolate parameters
  if (params) {
    return value.replace(/\{(\w+)\}/g, (_, paramKey) => {
      return params[paramKey] !== undefined ? params[paramKey] : `{${paramKey}}`;
    });
  }

  return value;
}

// Simple translation hook for React components
export function useTranslation(namespace?: string) {
  return {
    t: (key: string, params?: Record<string, string>) => {
      const fullKey = namespace ? `${namespace}.${key}` : key;
      return getTranslation(defaultLocale, fullKey, params);
    },
  };
}
