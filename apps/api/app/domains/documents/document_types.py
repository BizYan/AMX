"""Document Type Schemas

Pydantic models for the eight core document types: URS, BRD, PRD, User Story,
Detailed Design, Interface Document, Data Dictionary, and Test Case.
"""

from typing import Any

from pydantic import BaseModel, Field


class URSSchema(BaseModel):
    """User Requirements Specification schema.

    Captures all user requirements including business objectives, functional
    and non-functional requirements, constraints, and acceptance criteria.
    """

    project_name: str = Field(..., description="Name of the project")
    business_objectives: list[str] = Field(
        default_factory=list,
        description="High-level business objectives",
    )
    user_personas: list[dict[str, Any]] = Field(
        default_factory=list,
        description="User persona descriptions with roles, goals, and pain points",
    )
    functional_requirements: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Functional requirements with id, description, priority, and acceptance criteria",
    )
    non_functional_requirements: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Non-functional requirements with id, type, and description",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Project constraints and limitations",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Key assumptions",
    )
    glossary: dict[str, str] = Field(
        default_factory=dict,
        description="Terminology glossary",
    )


class BRDSchema(BaseModel):
    """Business Requirements Document schema.

    Defines business context, stakeholder analysis, business rules,
    and links to URS functional requirements.
    """

    project_name: str = Field(..., description="Name of the project")
    executive_summary: str = Field(..., description="Executive summary of the project")
    business_context: str = Field(..., description="Business context and background")
    stakeholder_analysis: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Stakeholder analysis with roles, interests, and influence",
    )
    business_rules: list[str] = Field(
        default_factory=list,
        description="Business rules that govern the system",
    )
    functional_requirements: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Functional requirements linked to URS",
    )
    data_requirements: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Data requirements with entity, attributes, and relationships",
    )
    process_flows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Business process flows",
    )
    edge_cases: list[str] = Field(
        default_factory=list,
        description="Edge cases and exception handling",
    )


class PRDSchema(BaseModel):
    """Product Requirements Document schema.

    Defines product goals, user stories linked to BRD, feature specifications,
    UI/UX requirements, and success metrics.
    """

    project_name: str = Field(..., description="Name of the project")
    goals: list[str] = Field(
        default_factory=list,
        description="Product goals and objectives",
    )
    user_stories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="User stories linked to BRD requirements",
    )
    feature_specifications: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed feature specifications",
    )
    ui_ux_requirements: dict[str, Any] = Field(
        default_factory=dict,
        description="UI/UX requirements including layout, navigation, and styling",
    )
    technical_constraints: list[str] = Field(
        default_factory=list,
        description="Technical constraints and non-negotiables",
    )
    success_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Success metrics and KPIs",
    )


class UserStorySchema(BaseModel):
    """User Story schema.

    Individual user story following the format: As a [user type],
    I want [goal] so that [benefit].
    """

    story_id: str = Field(..., description="Unique story identifier (e.g., US-001)")
    title: str = Field(..., description="Short story title")
    user_type: str = Field(..., description="Type of user (e.g., Admin, Customer)")
    goal: str = Field(..., description="What the user wants to accomplish")
    benefit: str = Field(..., description="Value or benefit to the user")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Acceptance criteria for the story",
    )
    priority: str = Field(
        ...,
        description="Priority level (must-have/should-have/could-have/won't-have)",
    )
    estimation_points: int | None = Field(
        None,
        description="Story points for estimation",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of dependent stories or requirements",
    )
    linked_requirements: list[str] = Field(
        default_factory=list,
        description="Linked requirement IDs from URS/BRD",
    )


class DetailedDesignSchema(BaseModel):
    """Detailed Design Document schema.

    Technical design document covering module architecture, class diagrams,
    sequence diagrams, data models, and API specifications.
    """

    module_name: str = Field(..., description="Name of the module or component")
    overview: str = Field(..., description="Module overview and purpose")
    class_diagram: dict[str, Any] | None = Field(
        None,
        description="Class diagram structure",
    )
    sequence_diagrams: list[dict[str, Any]] | None = Field(
        None,
        description="Sequence diagrams for key operations",
    )
    data_models: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Data model definitions",
    )
    api_specifications: list[dict[str, Any]] = Field(
        default_factory=list,
        description="API endpoint specifications",
    )
    error_handling: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Error handling strategies",
    )
    security_considerations: list[str] = Field(
        default_factory=list,
        description="Security considerations and requirements",
    )
    linked_user_stories: list[str] = Field(
        default_factory=list,
        description="Linked user story IDs",
    )


class InterfaceDocumentSchema(BaseModel):
    """Interface Document schema.

    API interface specification including endpoints, authentication,
    data formats, and rate limits.
    """

    api_name: str = Field(..., description="Name of the API")
    base_url: str = Field(..., description="Base URL for the API")
    authentication: str = Field(..., description="Authentication mechanism")
    endpoints: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Endpoint definitions with method, path, description, schemas",
    )
    data_formats: list[str] = Field(
        default_factory=list,
        description="Supported data formats (JSON, XML, etc.)",
    )
    rate_limits: dict[str, Any] | None = Field(
        None,
        description="Rate limit configuration",
    )
    versioning_strategy: str = Field(
        ...,
        description="API versioning strategy",
    )


class DataDictionarySchema(BaseModel):
    """Data Dictionary schema.

    Database schema documentation including tables, columns, indexes,
    relationships, and data retention policies.
    """

    tables: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Table definitions with name, description, and columns",
    )
    indexes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Index definitions",
    )
    relationships: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Relationship definitions between tables",
    )
    data_retention_policy: dict[str, Any] | None = Field(
        None,
        description="Data retention and archival policy",
    )


class TestCaseSchema(BaseModel):
    """Test Case schema.

    Test case definition including preconditions, test steps,
    test data, and priority.
    """

    test_case_id: str = Field(..., description="Unique test case identifier (e.g., TC-001)")
    test_suite: str = Field(..., description="Test suite or feature area")
    title: str = Field(..., description="Test case title")
    precondition: str = Field(..., description="Prerequisites for the test")
    test_steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Test steps with step_number, action, and expected_result",
    )
    test_data: dict[str, Any] | None = Field(
        None,
        description="Test data configuration",
    )
    priority: str = Field(
        ...,
        description="Priority level (critical/high/medium/low)",
    )
    linked_user_story: str = Field(..., description="Linked user story ID")
    linked_detailed_design: str | None = Field(
        None,
        description="Linked detailed design document ID",
    )
    automated: bool = Field(
        False,
        description="Whether the test case is automated",
    )


# Document type to schema mapping
DOCUMENT_TYPE_SCHEMAS = {
    "urs": URSSchema,
    "brd": BRDSchema,
    "prd": PRDSchema,
    "user_story": UserStorySchema,
    "detailed_design": DetailedDesignSchema,
    "interface": InterfaceDocumentSchema,
    "data_dictionary": DataDictionarySchema,
    "test_case": TestCaseSchema,
}


def get_schema_for_doc_type(doc_type: str) -> type[BaseModel]:
    """Get the schema class for a document type.

    Args:
        doc_type: Document type string (e.g., 'urs', 'brd')

    Returns:
        Pydantic model class for the document type

    Raises:
        ValueError: If doc_type is not recognized
    """
    if doc_type not in DOCUMENT_TYPE_SCHEMAS:
        raise ValueError(f"Unknown document type: {doc_type}")
    return DOCUMENT_TYPE_SCHEMAS[doc_type]