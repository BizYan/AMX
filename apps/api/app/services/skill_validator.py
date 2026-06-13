"""Skill and Tool Contract Validation Service

Provides comprehensive validation for SkillContract and ToolContract schemas,
including JSON Schema validity checking and registry validation.
"""

import json
from typing import Any

from app.domains.agent.schemas import SkillContractSchema, ToolContractSchema
from app.domains.agent.service import SkillService


class SkillContractValidationError(Exception):
    """Raised when skill contract validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Skill contract validation failed: {'; '.join(errors)}")


class ToolContractValidationError(Exception):
    """Raised when tool contract validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Tool contract validation failed: {'; '.join(errors)}")


class SkillValidator:
    """Service for validating skill and tool contracts."""

    def __init__(self, skill_service: SkillService | None = None):
        """Initialize skill validator.

        Args:
            skill_service: Optional SkillService instance for registry validation.
                          If not provided, creates a new one.
        """
        self.skill_service = skill_service or SkillService()

    def validate_skill_contract(
        self,
        contract: dict[str, Any],
        check_registry: bool = True,
    ) -> tuple[bool, list[str]]:
        """Validate a skill contract dictionary.

        Args:
            contract: Skill contract dict to validate
            check_registry: Whether to check if skill exists in registry

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check required fields
        required_fields = ["name", "description", "input_schema", "output_schema"]
        for field in required_fields:
            if field not in contract:
                errors.append(f"Missing required field: '{field}'")

        # Early exit if critical fields missing
        if errors:
            return False, errors

        # Validate name field
        name = contract.get("name", "")
        if not isinstance(name, str) or not name.strip():
            errors.append("'name' must be a non-empty string")

        # Validate description field
        description = contract.get("description", "")
        if not isinstance(description, str) or not description.strip():
            errors.append("'description' must be a non-empty string")

        # Validate input_schema
        if "input_schema" in contract:
            input_schema_valid, input_errors = self._validate_json_schema(
                contract["input_schema"],
                "input_schema",
            )
            errors.extend(input_errors)

        # Validate output_schema
        if "output_schema" in contract:
            output_schema_valid, output_errors = self._validate_json_schema(
                contract["output_schema"],
                "output_schema",
            )
            errors.extend(output_errors)

        # Check skill exists in registry (if check_registry is True)
        if check_registry and name:
            skill = self.skill_service.get_skill(name)
            if not skill:
                errors.append(f"Skill '{name}' not found in registry. Available skills: {list(self.skill_service.BUILTIN_SKILLS.keys())}")

        return len(errors) == 0, errors

    def validate_tool_contract(
        self,
        contract: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate a tool contract dictionary.

        Args:
            contract: Tool contract dict to validate

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check required fields for tools
        required_fields = ["name", "description", "input_schema", "output_schema", "handler"]
        for field in required_fields:
            if field not in contract:
                errors.append(f"Missing required field: '{field}'")

        # Early exit if critical fields missing
        if errors:
            return False, errors

        # Validate name field
        name = contract.get("name", "")
        if not isinstance(name, str) or not name.strip():
            errors.append("'name' must be a non-empty string")

        # Validate description field
        description = contract.get("description", "")
        if not isinstance(description, str) or not description.strip():
            errors.append("'description' must be a non-empty string")

        # Validate handler field
        handler = contract.get("handler", "")
        if not isinstance(handler, str) or not handler.strip():
            errors.append("'handler' must be a non-empty string")

        # Validate input_schema
        if "input_schema" in contract:
            input_schema_valid, input_errors = self._validate_json_schema(
                contract["input_schema"],
                "input_schema",
            )
            errors.extend(input_errors)

        # Validate output_schema
        if "output_schema" in contract:
            output_schema_valid, output_errors = self._validate_json_schema(
                contract["output_schema"],
                "output_schema",
            )
            errors.extend(output_errors)

        return len(errors) == 0, errors

    def validate_skill_contracts(
        self,
        contracts: list[dict[str, Any]],
        check_registry: bool = True,
    ) -> tuple[bool, list[str]]:
        """Validate a list of skill contracts.

        Args:
            contracts: List of skill contract dicts
            check_registry: Whether to check if skills exist in registry

        Returns:
            Tuple of (all_valid, list of error messages)
        """
        if not contracts:
            return True, []

        all_errors = []

        for i, contract in enumerate(contracts):
            is_valid, errors = self.validate_skill_contract(
                contract,
                check_registry=check_registry,
            )
            if not is_valid:
                for error in errors:
                    all_errors.append(f"Contract[{i}]: {error}")

        return len(all_errors) == 0, all_errors

    def validate_tool_contracts(
        self,
        contracts: list[dict[str, Any]],
    ) -> tuple[bool, list[str]]:
        """Validate a list of tool contracts.

        Args:
            contracts: List of tool contract dicts

        Returns:
            Tuple of (all_valid, list of error messages)
        """
        if not contracts:
            return True, []

        all_errors = []

        for i, contract in enumerate(contracts):
            is_valid, errors = self.validate_tool_contract(contract)
            if not is_valid:
                for error in errors:
                    all_errors.append(f"Contract[{i}]: {error}")

        return len(all_errors) == 0, all_errors

    def _validate_json_schema(
        self,
        schema: dict[str, Any],
        field_name: str,
    ) -> tuple[bool, list[str]]:
        """Validate a JSON Schema structure.

        Args:
            schema: Schema dict to validate
            field_name: Name of field being validated (for error messages)

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        if not isinstance(schema, dict):
            return False, [f"'{field_name}' must be a dict"]

        # JSON Schema must have 'type' field
        if "type" not in schema:
            errors.append(f"'{field_name}' must have a 'type' field")

        # Validate 'type' value if present
        valid_types = ["object", "array", "string", "number", "integer", "boolean", "null"]
        if "type" in schema:
            schema_type = schema["type"]
            if schema_type not in valid_types:
                errors.append(
                    f"'{field_name}.type' must be one of: {', '.join(valid_types)}"
                )

        # Validate 'properties' if present
        if "properties" in schema:
            if not isinstance(schema["properties"], dict):
                errors.append(f"'{field_name}.properties' must be a dict")
            else:
                for prop_name, prop_value in schema["properties"].items():
                    if not isinstance(prop_value, dict):
                        errors.append(
                            f"'{field_name}.properties['{prop_name}']' must be a dict"
                        )

        # Validate 'required' if present
        if "required" in schema:
            if not isinstance(schema["required"], list):
                errors.append(f"'{field_name}.required' must be an array")
            else:
                for req_item in schema["required"]:
                    if not isinstance(req_item, str):
                        errors.append(
                            f"'{field_name}.required' items must be strings"
                        )

        # Validate 'items' if present (for array type)
        if "items" in schema:
            if not isinstance(schema["items"], dict):
                errors.append(f"'{field_name}.items' must be a dict")

        # Validate 'enum' if present
        if "enum" in schema:
            if not isinstance(schema["enum"], list):
                errors.append(f"'{field_name}.enum' must be an array")

        return len(errors) == 0, errors

    def validate_workflow_contracts(
        self,
        skill_contracts: list[dict[str, Any]] | None,
        tool_contracts: list[dict[str, Any]] | None,
    ) -> tuple[bool, list[str]]:
        """Validate both skill and tool contracts for a workflow version.

        Args:
            skill_contracts: List of skill contract dicts
            tool_contracts: List of tool contract dicts

        Returns:
            Tuple of (all_valid, list of error messages)
        """
        all_errors = []

        # Validate skill contracts
        if skill_contracts:
            skill_valid, skill_errors = self.validate_skill_contracts(skill_contracts)
            if not skill_valid:
                all_errors.append(f"Skill contracts invalid: {skill_errors}")

        # Validate tool contracts
        if tool_contracts:
            tool_valid, tool_errors = self.validate_tool_contracts(tool_contracts)
            if not tool_valid:
                all_errors.append(f"Tool contracts invalid: {tool_errors}")

        return len(all_errors) == 0, all_errors

    def get_builtin_skill_names(self) -> list[str]:
        """Get list of all registered builtin skill names.

        Returns:
            List of skill names
        """
        return list(self.skill_service.BUILTIN_SKILLS.keys())

    def is_skill_registered(self, skill_name: str) -> bool:
        """Check if a skill is registered in the builtin registry.

        Args:
            skill_name: Name of the skill

        Returns:
            True if registered, False otherwise
        """
        return skill_name in self.skill_service.BUILTIN_SKILLS

    def get_skill_info(self, skill_name: str) -> dict[str, Any] | None:
        """Get skill information from registry.

        Args:
            skill_name: Name of the skill

        Returns:
            Skill info dict if found, None otherwise
        """
        return self.skill_service.get_skill(skill_name)