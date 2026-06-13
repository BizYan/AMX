from .i18n import ErrorCode, get_error_message


class AppException(Exception):
    def __init__(self, code: str, message: str = None, details: dict = None):
        self.code = code
        self.message = message or get_error_message(code)
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# Authentication errors (1000-1099)
class InvalidCredentialsError(AppException):
    code = ErrorCode.AUTH_INVALID_CREDENTIALS


class TokenExpiredError(AppException):
    code = ErrorCode.AUTH_TOKEN_EXPIRED


class TokenInvalidError(AppException):
    code = ErrorCode.AUTH_TOKEN_INVALID


class TokenBlacklistedError(AppException):
    code = ErrorCode.AUTH_TOKEN_BLACKLISTED


class UserNotFoundError(AppException):
    code = ErrorCode.AUTH_USER_NOT_FOUND


class UserDisabledError(AppException):
    code = ErrorCode.AUTH_USER_DISABLED


class InsufficientPermissionError(AppException):
    code = ErrorCode.AUTH_INSUFFICIENT_PERMISSION


class LoginFailedError(AppException):
    code = ErrorCode.AUTH_LOGIN_FAILED


class LogoutFailedError(AppException):
    code = ErrorCode.AUTH_LOGOUT_FAILED


# Tenant errors (2000-2099)
class TenantNotFoundError(AppException):
    code = ErrorCode.TENANT_NOT_FOUND


class TenantAlreadyExistsError(AppException):
    code = ErrorCode.TENANT_ALREADY_EXISTS


class TenantCannotDeleteError(AppException):
    code = ErrorCode.TENANT_CANNOT_DELETE


class TenantQuotaExceededError(AppException):
    code = ErrorCode.TENANT_QUOTA_EXCEEDED


# Project errors (3000-3099)
class ProjectNotFoundError(AppException):
    code = ErrorCode.PROJECT_NOT_FOUND


class ProjectAlreadyExistsError(AppException):
    code = ErrorCode.PROJECT_ALREADY_EXISTS


class ProjectAccessDeniedError(AppException):
    code = ErrorCode.PROJECT_ACCESS_DENIED


class ProjectCannotDeleteError(AppException):
    code = ErrorCode.PROJECT_CANNOT_DELETE


class ProjectMemberNotFoundError(AppException):
    code = ErrorCode.PROJECT_MEMBER_NOT_FOUND


class ProjectMemberAlreadyExistsError(AppException):
    code = ErrorCode.PROJECT_MEMBER_ALREADY_EXISTS


# Document errors (4000-4099)
class DocumentNotFoundError(AppException):
    code = ErrorCode.DOCUMENT_NOT_FOUND


class DocumentAlreadyExistsError(AppException):
    code = ErrorCode.DOCUMENT_ALREADY_EXISTS


class DocumentInvalidSchemaError(AppException):
    code = ErrorCode.DOCUMENT_INVALID_SCHEMA


class DocumentVersionConflictError(AppException):
    code = ErrorCode.DOCUMENT_VERSION_CONFLICT


class DocumentCannotDeleteError(AppException):
    code = ErrorCode.DOCUMENT_CANNOT_DELETE


class DocumentQualityFailedError(AppException):
    code = ErrorCode.DOCUMENT_QUALITY_FAILED


# Knowledge errors (5000-5099)
class KnowledgeNotFoundError(AppException):
    code = ErrorCode.KNOWLEDGE_NOT_FOUND


class KnowledgeAlreadyExistsError(AppException):
    code = ErrorCode.KNOWLEDGE_ALREADY_EXISTS


class KnowledgeAccessDeniedError(AppException):
    code = ErrorCode.KNOWLEDGE_ACCESS_DENIED


class KnowledgeApprovalPendingError(AppException):
    code = ErrorCode.KNOWLEDGE_APPROVAL_PENDING


# Provider errors (6000-6099)
class ProviderNotFoundError(AppException):
    code = ErrorCode.PROVIDER_NOT_FOUND


class ProviderNotConfiguredError(AppException):
    code = ErrorCode.PROVIDER_NOT_CONFIGURED


class ProviderConnectionFailedError(AppException):
    code = ErrorCode.PROVIDER_CONNECTION_FAILED


class ProviderCircuitOpenError(AppException):
    code = ErrorCode.PROVIDER_CIRCUIT_OPEN


class ProviderRateLimitedError(AppException):
    code = ErrorCode.PROVIDER_RATE_LIMITED


class ProviderTimeoutError(AppException):
    code = ErrorCode.PROVIDER_TIMEOUT


# Change request errors (7000-7099)
class ChangeNotFoundError(AppException):
    code = ErrorCode.CHANGE_NOT_FOUND


class ChangeCannotApproveError(AppException):
    code = ErrorCode.CHANGE_CANNOT_APPROVE


class ChangeCannotRejectError(AppException):
    code = ErrorCode.CHANGE_CANNOT_REJECT


class ChangeCannotApplyError(AppException):
    code = ErrorCode.CHANGE_CANNOT_APPLY


class ChangeStaleVersionError(AppException):
    code = ErrorCode.CHANGE_STALE_VERSION


# Agent errors (8000-8099)
class AgentRunNotFoundError(AppException):
    code = ErrorCode.AGENT_RUN_NOT_FOUND


class AgentTaskFailedError(AppException):
    code = ErrorCode.AGENT_TASK_FAILED


class AgentTaskTimeoutError(AppException):
    code = ErrorCode.AGENT_TASK_TIMEOUT


class AgentDLQFullError(AppException):
    code = ErrorCode.AGENT_DLQ_FULL


class AgentWorkflowError(AppException):
    code = ErrorCode.AGENT_WORKFLOW_ERROR


# Export errors (9000-9099)
class ExportNotFoundError(AppException):
    code = ErrorCode.EXPORT_NOT_FOUND


class ExportFailedError(AppException):
    code = ErrorCode.EXPORT_FAILED


class ExportInvalidTemplateError(AppException):
    code = ErrorCode.EXPORT_INVALID_TEMPLATE


class ExportQuotaExceededError(AppException):
    code = ErrorCode.EXPORT_QUOTA_EXCEEDED


# General errors (0000-0099)
class ValidationError(AppException):
    code = ErrorCode.VALIDATION_ERROR


class InternalError(AppException):
    code = ErrorCode.INTERNAL_ERROR


class NotFoundError(AppException):
    code = ErrorCode.NOT_FOUND


class AlreadyExistsError(AppException):
    code = ErrorCode.ALREADY_EXISTS


class ConflictError(AppException):
    code = ErrorCode.CONFLICT


class InvalidParameterError(AppException):
    code = ErrorCode.INVALID_PARAMETER