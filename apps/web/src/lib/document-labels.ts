const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  urs: '用户需求规格说明书',
  brd: '业务需求文档',
  prd: '产品需求文档',
  user_story: '用户故事',
  detailed_design: '详细设计说明',
  design: '设计说明',
  interface: '接口说明',
  test_case: '测试用例',
  data_dictionary: '数据字典',
}

const DOCUMENT_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  writing: '编写中',
  pending_review: '待评审',
  review: '评审中',
  under_review: '评审中',
  in_review: '评审中',
  revision_required: '待修订',
  approved: '已批准',
  published: '已发布',
  rejected: '已退回',
  archived: '已归档',
  missing: '未生成',
}

export function getDocumentTypeLabel(type?: string | null) {
  if (!type) return '未分类'
  return DOCUMENT_TYPE_LABELS[type.toLowerCase()] || type
}

export function getDocumentStatusLabel(status?: string | null) {
  if (!status) return '草稿'
  return DOCUMENT_STATUS_LABELS[status.toLowerCase()] || status
}
