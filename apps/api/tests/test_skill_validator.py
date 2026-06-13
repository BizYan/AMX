"""Tests for Skill and Tool Contract Validation Service"""

import json

import pytest
from app.services.skill_validator import (
    SkillValidator,
    SkillContractValidationError,
    ToolContractValidationError,
)
from app.domains.agent.service import SkillService


class TestSkillValidator:
    """Tests for SkillValidator class."""

    @pytest.fixture
    def validator(self):
        """Create a SkillValidator instance for testing."""
        return SkillValidator()

    @pytest.fixture
    def valid_skill_contract(self):
        """Return a valid skill contract for testing."""
        return {
            "name": "MECEAnalyzer",
            "description": "Analyze content for MECE compliance",
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                },
                "required": ["content"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "score": {"type": "number"},
                },
            },
        }

    @pytest.fixture
    def valid_tool_contract(self):
        """Return a valid tool contract for testing."""
        return {
            "name": "DocumentExporter",
            "description": "Export documents to various formats",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "format": {"type": "string"},
                },
                "required": ["document_id", "format"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "file_path": {"type": "string"},
                },
            },
            "handler": "export_document",
        }

    def test_validate_valid_skill_contract(self, validator, valid_skill_contract):
        """Test validation of a valid skill contract."""
        is_valid, errors = validator.validate_skill_contract(valid_skill_contract)
        assert is_valid is True
        assert errors == []

    def test_validate_valid_tool_contract(self, validator, valid_tool_contract):
        """Test validation of a valid tool contract."""
        is_valid, errors = validator.validate_tool_contract(valid_tool_contract)
        assert is_valid is True
        assert errors == []

    def test_validate_skill_contract_missing_name(self, validator):
        """Test validation fails when name is missing."""
        contract = {
            "description": "Test description",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is False
        assert any("name" in e for e in errors)

    def test_validate_skill_contract_missing_description(self, validator):
        """Test validation fails when description is missing."""
        contract = {
            "name": "TestSkill",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is False
        assert any("description" in e for e in errors)

    def test_validate_skill_contract_missing_input_schema(self, validator):
        """Test validation fails when input_schema is missing."""
        contract = {
            "name": "TestSkill",
            "description": "Test description",
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is False
        assert any("input_schema" in e for e in errors)

    def test_validate_skill_contract_missing_output_schema(self, validator):
        """Test validation fails when output_schema is missing."""
        contract = {
            "name": "TestSkill",
            "description": "Test description",
            "input_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is False
        assert any("output_schema" in e for e in errors)

    def test_validate_skill_contract_invalid_input_schema_not_dict(self, validator):
        """Test validation fails when input_schema is not a dict."""
        contract = {
            "name": "TestSkill",
            "description": "Test description",
            "input_schema": "not a dict",
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is False
        assert any("input_schema" in e and "dict" in e for e in errors)

    def test_validate_skill_contract_input_schema_missing_type(self, validator):
        """Test validation fails when input_schema lacks type field."""
        contract = {
            "name": "TestSkill",
            "description": "Test description",
            "input_schema": {"properties": {}},
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is False
        assert any("type" in e and "input_schema" in e for e in errors)

    def test_validate_skill_contract_invalid_type_value(self, validator):
        """Test validation fails when schema type is invalid."""
        contract = {
            "name": "TestSkill",
            "description": "Test description",
            "input_schema": {"type": "invalid_type"},
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is False
        assert any("type" in e for e in errors)

    def test_validate_skill_contract_unknown_skill(self, validator):
        """Test validation fails for unknown skill not in registry."""
        contract = {
            "name": "UnknownSkill",
            "description": "Test description",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=True)
        assert is_valid is False
        assert any("UnknownSkill" in e and "not found" in e for e in errors)

    def test_validate_skill_contract_skip_registry_check(self, validator):
        """Test validation passes for unknown skill when registry check disabled."""
        contract = {
            "name": "UnknownSkill",
            "description": "Test description",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_skill_contract(contract, check_registry=False)
        assert is_valid is True
        assert errors == []

    def test_validate_tool_contract_missing_handler(self, validator):
        """Test validation fails when tool handler is missing."""
        contract = {
            "name": "TestTool",
            "description": "Test description",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }
        is_valid, errors = validator.validate_tool_contract(contract)
        assert is_valid is False
        assert any("handler" in e for e in errors)

    def test_validate_multiple_skill_contracts(self, validator):
        """Test validating multiple skill contracts."""
        contracts = [
            {
                "name": "MECEAnalyzer",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
            {
                "name": "IssueTreeAnalyzer",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ]
        is_valid, errors = validator.validate_skill_contracts(contracts)
        assert is_valid is True
        assert errors == []

    def test_validate_multiple_skill_contracts_one_invalid(self, validator):
        """Test validation fails if one contract in list is invalid."""
        contracts = [
            {
                "name": "MECEAnalyzer",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
            {
                "name": "UnknownSkill",  # Not in registry
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ]
        is_valid, errors = validator.validate_skill_contracts(contracts)
        assert is_valid is False
        assert len(errors) > 0

    def test_validate_empty_skill_contracts_list(self, validator):
        """Test validating empty list returns success."""
        is_valid, errors = validator.validate_skill_contracts([])
        assert is_valid is True
        assert errors == []

    def test_validate_empty_tool_contracts_list(self, validator):
        """Test validating empty list returns success."""
        is_valid, errors = validator.validate_tool_contracts([])
        assert is_valid is True
        assert errors == []

    def test_validate_workflow_contracts_both_valid(self, validator):
        """Test validating workflow with both skill and tool contracts."""
        skill_contracts = [
            {
                "name": "MECEAnalyzer",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ]
        tool_contracts = [
            {
                "name": "DocumentExporter",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "handler": "export",
            },
        ]
        is_valid, errors = validator.validate_workflow_contracts(skill_contracts, tool_contracts)
        assert is_valid is True
        assert errors == []

    def test_validate_workflow_contracts_skill_invalid(self, validator):
        """Test validation fails when skill contract is invalid."""
        skill_contracts = [
            {
                "name": "UnknownSkill",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ]
        tool_contracts = [
            {
                "name": "DocumentExporter",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "handler": "export",
            },
        ]
        is_valid, errors = validator.validate_workflow_contracts(skill_contracts, tool_contracts)
        assert is_valid is False

    def test_validate_workflow_contracts_tool_invalid(self, validator):
        """Test validation fails when tool contract is invalid."""
        skill_contracts = [
            {
                "name": "MECEAnalyzer",
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ]
        tool_contracts = [
            {
                "name": "BadTool",  # Missing handler
                "description": "Test",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ]
        is_valid, errors = validator.validate_workflow_contracts(skill_contracts, tool_contracts)
        assert is_valid is False

    def test_validate_workflow_contracts_none(self, validator):
        """Test validation succeeds when both are None."""
        is_valid, errors = validator.validate_workflow_contracts(None, None)
        assert is_valid is True
        assert errors == []

    def test_get_builtin_skill_names(self, validator):
        """Test getting list of builtin skill names."""
        names = validator.get_builtin_skill_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert "MECEAnalyzer" in names
        assert "IssueTreeAnalyzer" in names
        assert "DocumentReviewer" in names

    def test_is_skill_registered_valid(self, validator):
        """Test checking if a registered skill is found."""
        assert validator.is_skill_registered("MECEAnalyzer") is True
        assert validator.is_skill_registered("IssueTreeAnalyzer") is True

    def test_is_skill_registered_invalid(self, validator):
        """Test checking if an unregistered skill returns False."""
        assert validator.is_skill_registered("NonExistentSkill") is False

    def test_get_skill_info_valid(self, validator):
        """Test getting skill info for a valid skill."""
        info = validator.get_skill_info("MECEAnalyzer")
        assert info is not None
        assert info["name"] == "MECEAnalyzer"
        assert "description" in info
        assert "input_schema" in info
        assert "output_schema" in info

    def test_get_skill_info_invalid(self, validator):
        """Test getting skill info for an invalid skill returns None."""
        info = validator.get_skill_info("NonExistentSkill")
        assert info is None


class TestSkillContractValidationError:
    """Tests for SkillContractValidationError exception."""

    def test_error_contains_messages(self):
        """Test that error contains validation messages."""
        errors = ["Error 1", "Error 2"]
        error = SkillContractValidationError(errors)
        assert error.errors == errors
        assert "Error 1" in str(error)
        assert "Error 2" in str(error)


class TestToolContractValidationError:
    """Tests for ToolContractValidationError exception."""

    def test_error_contains_messages(self):
        """Test that error contains validation messages."""
        errors = ["Missing handler", "Invalid schema"]
        error = ToolContractValidationError(errors)
        assert error.errors == errors
        assert "Missing handler" in str(error)


class TestBuiltinSkillsIntegration:
    """Integration tests to verify builtin skills are properly wired."""

    def test_all_builtin_skills_have_required_fields(self):
        """Test that all builtin skills have all required contract fields."""
        skill_service = SkillService()
        validator = SkillValidator(skill_service)

        for skill_name, skill_info in skill_service.BUILTIN_SKILLS.items():
            # All skills must have these fields
            assert "name" in skill_info, f"{skill_name} missing 'name'"
            assert "description" in skill_info, f"{skill_name} missing 'description'"
            assert "input_schema" in skill_info, f"{skill_name} missing 'input_schema'"
            assert "output_schema" in skill_info, f"{skill_name} missing 'output_schema'"

            # Schemas must be valid
            is_valid, errors = validator.validate_skill_contract(
                skill_info, check_registry=False
            )
            assert is_valid, f"{skill_name} has invalid schema: {errors}"

    def test_builtin_skills_valid_schemas(self):
        """Test that all builtin skill schemas are valid JSON schemas."""
        skill_service = SkillService()

        for skill_name, skill_info in skill_service.BUILTIN_SKILLS.items():
            input_schema = skill_info.get("input_schema", {})
            output_schema = skill_info.get("output_schema", {})

            # Must have type
            assert "type" in input_schema, f"{skill_name}: input_schema missing 'type'"
            assert "type" in output_schema, f"{skill_name}: output_schema missing 'type'"

            # Type must be valid
            valid_types = ["object", "array", "string", "number", "integer", "boolean", "null"]
            assert input_schema["type"] in valid_types, f"{skill_name}: invalid input type"
            assert output_schema["type"] in valid_types, f"{skill_name}: invalid output type"

    def test_builtin_skill_names_match_registration(self):
        """Test that skill names in registry match their keys."""
        skill_service = SkillService()

        for skill_name, skill_info in skill_service.BUILTIN_SKILLS.items():
            assert skill_info["name"] == skill_name, (
                f"Skill key '{skill_name}' doesn't match name in info '{skill_info['name']}'"
            )

    def test_skill_service_has_mece(self):
        """Test that MECEAnalyzer skill is registered."""
        skill_service = SkillService()
        assert skill_service.get_skill("MECEAnalyzer") is not None

    def test_skill_service_has_issue_tree(self):
        """Test that IssueTreeAnalyzer skill is registered."""
        skill_service = SkillService()
        assert skill_service.get_skill("IssueTreeAnalyzer") is not None

    def test_skill_service_has_document_reviewer(self):
        """Test that DocumentReviewer skill is registered."""
        skill_service = SkillService()
        assert skill_service.get_skill("DocumentReviewer") is not None

    def test_skill_service_has_requirement_clarifier(self):
        """Test that RequirementClarifier skill is registered."""
        skill_service = SkillService()
        assert skill_service.get_skill("RequirementClarifier") is not None

    def test_skill_service_has_export_orchestrator(self):
        """Test that ExportOrchestrator skill is registered."""
        skill_service = SkillService()
        assert skill_service.get_skill("ExportOrchestrator") is not None

    def test_all_builtin_skills_listed(self):
        """Test that all 5 builtin skills are registered."""
        skill_service = SkillService()
        skills = skill_service.list_skills()
        skill_names = [s["name"] for s in skills]

        expected = [
            "MECEAnalyzer",
            "IssueTreeAnalyzer",
            "DocumentReviewer",
            "RequirementClarifier",
            "ExportOrchestrator",
        ]

        for expected_skill in expected:
            assert expected_skill in skill_names, f"{expected_skill} not found in skill registry"


class TestJSONSchemaValidation:
    """Tests for JSON Schema validation functionality."""

    @pytest.fixture
    def validator(self):
        return SkillValidator()

    def test_validate_object_schema(self, validator):
        """Test validation of object type schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is True
        assert errors == []

    def test_validate_array_schema(self, validator):
        """Test validation of array type schema."""
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is True
        assert errors == []

    def test_validate_nested_properties(self, validator):
        """Test validation of nested properties."""
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is True
        assert errors == []

    def test_validate_properties_must_be_dict(self, validator):
        """Test that properties values must be dicts."""
        schema = {
            "type": "object",
            "properties": {
                "name": "not a dict",  # Should be a dict
            },
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is False
        assert any("dict" in e for e in errors)

    def test_validate_required_must_be_array(self, validator):
        """Test that required must be an array."""
        schema = {
            "type": "object",
            "required": "not an array",
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is False
        assert any("required" in e and "array" in e for e in errors)

    def test_validate_required_items_must_be_strings(self, validator):
        """Test that required array items must be strings."""
        schema = {
            "type": "object",
            "required": [123, "valid"],
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is False
        assert any("strings" in e for e in errors)

    def test_validate_items_must_be_dict(self, validator):
        """Test that items for arrays must be a dict."""
        schema = {
            "type": "array",
            "items": "not a dict",
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is False
        assert any("items" in e and "dict" in e for e in errors)

    def test_validate_enum_must_be_array(self, validator):
        """Test that enum must be an array."""
        schema = {
            "type": "string",
            "enum": "not an array",
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is False
        assert any("enum" in e and "array" in e for e in errors)

    def test_validate_enum_with_valid_values(self, validator):
        """Test that valid enum passes."""
        schema = {
            "type": "string",
            "enum": ["value1", "value2", "value3"],
        }
        is_valid, errors = validator._validate_json_schema(schema, "test")
        assert is_valid is True
        assert errors == []


class TestBuiltinMethodologySkillExecution:
    """Regression tests for real input-driven methodology skill outputs."""

    @pytest.mark.asyncio
    async def test_issue_tree_uses_input_terms_instead_of_generic_demo_labels(self):
        skill_service = SkillService()

        result = await skill_service.execute_skill(
            "IssueTreeAnalyzer",
            {
                "issue": "费用报销审批超时",
                "depth": 3,
                "branch_type": "cause",
            },
            {"context": "财务复核、预算校验、主管审批和通知补偿都可能影响时效。"},
        )
        payload = json.dumps(result, ensure_ascii=False)

        assert "Aspect 1" not in payload
        assert "Detail point" not in payload
        assert "财务复核" in payload or "预算校验" in payload or "主管审批" in payload
        assert result["leaf_nodes"] >= 2

    @pytest.mark.asyncio
    async def test_prd_traceability_mapper_uses_brd_input_without_fixed_warehouse_example(self):
        skill_service = SkillService()

        result = await skill_service.execute_skill(
            "PRDTraceabilityMapper",
            {
                "brd_content": "客户需要费用报销审批支持财务复核。金额超限时必须进入主管复核并保留审计记录。",
                "product_scope": "费用报销平台",
            },
            {"document_type": "prd"},
        )
        payload = json.dumps(result, ensure_ascii=False)

        assert "费用报销" in payload
        assert "财务复核" in payload
        assert "逐单扫码复核" not in payload
        assert "出库复核" not in payload
        assert result["traceability_rows"][0]["brd_item"]

    @pytest.mark.asyncio
    async def test_knowledge_graph_and_test_case_skills_are_input_driven(self):
        skill_service = SkillService()

        graph = await skill_service.execute_skill(
            "KnowledgeGraphExtractor",
            {
                "content": "合同 评审 法务 审批 归档。法务审批通过后，合同进入归档并触发到期提醒。",
                "project_context": "合同管理系统",
            },
            {"document_type": "brd"},
        )
        graph_payload = json.dumps(graph, ensure_ascii=False)

        assert "合同" in graph_payload
        assert "法务" in graph_payload
        assert "复核员" not in graph_payload
        assert graph["entities"]

        cases = await skill_service.execute_skill(
            "TestCaseDesigner",
            {
                "feature_name": "合同到期提醒",
                "acceptance_criteria": [
                    "合同到期前 30 天通知负责人。",
                    "负责人确认后写入审计记录。",
                ],
            },
            {"document_type": "test_case"},
        )

        assert len(cases["test_cases"]) == 2
        assert cases["test_cases"][0]["expected_result"] == "合同到期前 30 天通知负责人"
        assert "合同到期提醒" in cases["summary"]
