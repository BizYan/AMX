from enum import Enum
from typing import Optional

class ErrorCode(str, Enum):
    # Authentication (1000-1099)
    AUTH_INVALID_CREDENTIALS = "auth.invalid_credentials"
    AUTH_TOKEN_EXPIRED = "auth.token_expired"
    AUTH_TOKEN_INVALID = "auth.token_invalid"
    AUTH_TOKEN_BLACKLISTED = "auth.token_blacklisted"
    AUTH_USER_NOT_FOUND = "auth.user_not_found"
    AUTH_USER_DISABLED = "auth.user_disabled"
    AUTH_INSUFFICIENT_PERMISSION = "auth.insufficient_permission"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_LOGOUT_FAILED = "auth.logout_failed"

    # Tenant (2000-2099)
    TENANT_NOT_FOUND = "tenant.not_found"
    TENANT_ALREADY_EXISTS = "tenant.already_exists"
    TENANT_CANNOT_DELETE = "tenant.cannot_delete"
    TENANT_QUOTA_EXCEEDED = "tenant.quota_exceeded"

    # Project (3000-3099)
    PROJECT_NOT_FOUND = "project.not_found"
    PROJECT_ALREADY_EXISTS = "project.already_exists"
    PROJECT_ACCESS_DENIED = "project.access_denied"
    PROJECT_CANNOT_DELETE = "project.cannot_delete"
    PROJECT_MEMBER_NOT_FOUND = "project.member_not_found"
    PROJECT_MEMBER_ALREADY_EXISTS = "project.member_already_exists"

    # Document (4000-4099)
    DOCUMENT_NOT_FOUND = "document.not_found"
    DOCUMENT_ALREADY_EXISTS = "document.already_exists"
    DOCUMENT_INVALID_SCHEMA = "document.invalid_schema"
    DOCUMENT_VERSION_CONFLICT = "document.version_conflict"
    DOCUMENT_CANNOT_DELETE = "document.cannot_delete"
    DOCUMENT_QUALITY_FAILED = "document.quality_failed"

    # Knowledge (5000-5099)
    KNOWLEDGE_NOT_FOUND = "knowledge.not_found"
    KNOWLEDGE_ALREADY_EXISTS = "knowledge.already_exists"
    KNOWLEDGE_ACCESS_DENIED = "knowledge.access_denied"
    KNOWLEDGE_APPROVAL_PENDING = "knowledge.approval_pending"

    # Provider (6000-6099)
    PROVIDER_NOT_FOUND = "provider.not_found"
    PROVIDER_NOT_CONFIGURED = "provider.not_configured"
    PROVIDER_CONNECTION_FAILED = "provider.connection_failed"
    PROVIDER_CIRCUIT_OPEN = "provider.circuit_open"
    PROVIDER_RATE_LIMITED = "provider.rate_limited"
    PROVIDER_TIMEOUT = "provider.timeout"

    # Change Request (7000-7099)
    CHANGE_NOT_FOUND = "change.not_found"
    CHANGE_CANNOT_APPROVE = "change.cannot_approve"
    CHANGE_CANNOT_REJECT = "change.cannot_reject"
    CHANGE_CANNOT_APPLY = "change.cannot_apply"
    CHANGE_STALE_VERSION = "change.stale_version"

    # Agent (8000-8099)
    AGENT_RUN_NOT_FOUND = "agent.run_not_found"
    AGENT_TASK_FAILED = "agent.task_failed"
    AGENT_TASK_TIMEOUT = "agent.task_timeout"
    AGENT_DLQ_FULL = "agent.dlq_full"
    AGENT_WORKFLOW_ERROR = "agent.workflow_error"

    # Export (9000-9099)
    EXPORT_NOT_FOUND = "export.not_found"
    EXPORT_FAILED = "export.failed"
    EXPORT_INVALID_TEMPLATE = "export.invalid_template"
    EXPORT_QUOTA_EXCEEDED = "export.quota_exceeded"

    # General (0000-0099)
    VALIDATION_ERROR = "validation.error"
    INTERNAL_ERROR = "internal.error"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    CONFLICT = "conflict"
    INVALID_PARAMETER = "invalid_parameter"

ERROR_MESSAGES = {
    # zh-CN translations
    "zh-CN": {
        "auth.invalid_credentials": "用户名或密码错误",
        "auth.token_expired": "登录已过期，请重新登录",
        "auth.token_invalid": "无效的访问令牌",
        "auth.token_blacklisted": "访问令牌已被撤销",
        "auth.user_not_found": "用户不存在",
        "auth.user_disabled": "用户账号已被禁用",
        "auth.insufficient_permission": "权限不足",
        "auth.login_failed": "登录失败",
        "auth.logout_failed": "退出登录失败",
        "tenant.not_found": "租户不存在",
        "tenant.already_exists": "租户已存在",
        "tenant.cannot_delete": "无法删除租户",
        "tenant.quota_exceeded": "租户配额已用尽",
        "project.not_found": "项目不存在",
        "project.already_exists": "项目已存在",
        "project.access_denied": "无权访问此项目",
        "project.cannot_delete": "无法删除项目",
        "project.member_not_found": "项目成员不存在",
        "project.member_already_exists": "项目成员已存在",
        "document.not_found": "文档不存在",
        "document.already_exists": "文档已存在",
        "document.invalid_schema": "文档格式无效",
        "document.version_conflict": "文档版本冲突",
        "document.cannot_delete": "无法删除文档",
        "document.quality_failed": "文档质量检查未通过",
        "knowledge.not_found": "知识条目不存在",
        "knowledge.already_exists": "知识条目已存在",
        "knowledge.access_denied": "无权访问此知识",
        "knowledge.approval_pending": "待审核",
        "provider.not_found": "Provider不存在",
        "provider.not_configured": "Provider未配置",
        "provider.connection_failed": "Provider连接失败",
        "provider.circuit_open": "Provider熔断中，请稍后重试",
        "provider.rate_limited": "Provider调用超限",
        "provider.timeout": "Provider响应超时",
        "change.not_found": "变更请求不存在",
        "change.cannot_approve": "无法批准此变更",
        "change.cannot_reject": "无法拒绝此变更",
        "change.cannot_apply": "无法应用此变更",
        "change.stale_version": "文档版本已过期",
        "agent.run_not_found": "Agent运行不存在",
        "agent.task_failed": "Agent任务执行失败",
        "agent.task_timeout": "Agent任务执行超时",
        "agent.dlq_full": "死信队列已满",
        "agent.workflow_error": "工作流执行错误",
        "export.not_found": "导出任务不存在",
        "export.failed": "导出失败",
        "export.invalid_template": "导出模板无效",
        "export.quota_exceeded": "导出配额已用尽",
        "validation.error": "数据验证失败",
        "internal.error": "内部错误",
        "not_found": "资源不存在",
        "already_exists": "资源已存在",
        "conflict": "资源冲突",
        "invalid_parameter": "无效参数",
    },
    # en-US translations
    "en-US": {
        "auth.invalid_credentials": "Invalid username or password",
        "auth.token_expired": "Session expired, please login again",
        "auth.token_invalid": "Invalid access token",
        "auth.token_blacklisted": "Access token has been revoked",
        "auth.user_not_found": "User not found",
        "auth.user_disabled": "User account has been disabled",
        "auth.insufficient_permission": "Insufficient permissions",
        "auth.login_failed": "Login failed",
        "auth.logout_failed": "Logout failed",
        "tenant.not_found": "Tenant not found",
        "tenant.already_exists": "Tenant already exists",
        "tenant.cannot_delete": "Cannot delete tenant",
        "tenant.quota_exceeded": "Tenant quota exceeded",
        "project.not_found": "Project not found",
        "project.already_exists": "Project already exists",
        "project.access_denied": "Access denied to this project",
        "project.cannot_delete": "Cannot delete project",
        "project.member_not_found": "Project member not found",
        "project.member_already_exists": "Project member already exists",
        "document.not_found": "Document not found",
        "document.already_exists": "Document already exists",
        "document.invalid_schema": "Invalid document schema",
        "document.version_conflict": "Document version conflict",
        "document.cannot_delete": "Cannot delete document",
        "document.quality_failed": "Document quality check failed",
        "knowledge.not_found": "Knowledge entry not found",
        "knowledge.already_exists": "Knowledge entry already exists",
        "knowledge.access_denied": "Access denied to this knowledge",
        "knowledge.approval_pending": "Pending approval",
        "provider.not_found": "Provider not found",
        "provider.not_configured": "Provider not configured",
        "provider.connection_failed": "Provider connection failed",
        "provider.circuit_open": "Provider circuit open, please retry later",
        "provider.rate_limited": "Provider rate limit exceeded",
        "provider.timeout": "Provider response timeout",
        "change.not_found": "Change request not found",
        "change.cannot_approve": "Cannot approve this change",
        "change.cannot_reject": "Cannot reject this change",
        "change.cannot_apply": "Cannot apply this change",
        "change.stale_version": "Document version is stale",
        "agent.run_not_found": "Agent run not found",
        "agent.task_failed": "Agent task execution failed",
        "agent.task_timeout": "Agent task execution timeout",
        "agent.dlq_full": "Dead letter queue is full",
        "agent.workflow_error": "Workflow execution error",
        "export.not_found": "Export task not found",
        "export.failed": "Export failed",
        "export.invalid_template": "Invalid export template",
        "export.quota_exceeded": "Export quota exceeded",
        "validation.error": "Data validation failed",
        "internal.error": "Internal error",
        "not_found": "Resource not found",
        "already_exists": "Resource already exists",
        "conflict": "Resource conflict",
        "invalid_parameter": "Invalid parameter",
    }
}


def get_error_message(code: str, locale: str = "zh-CN") -> str:
    """Get translated error message"""
    messages = ERROR_MESSAGES.get(locale, ERROR_MESSAGES["en-US"])
    return messages.get(code, code)


def get_error_code(error: Exception) -> str:
    """Map exception to error code"""
    # Implementation to map exceptions to error codes
    pass