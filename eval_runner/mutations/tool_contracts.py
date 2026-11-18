"""Validate tool arguments at execution and independently reconstruct contract-fault proofs."""

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

FORBIDDEN_PROPERTY = "_unexpected_forbidden_property"


def argument_schema(tool):
    return tool.get(
        "input_schema", tool.get("parameters_schema", tool.get("schema", tool.get("parameters")))
    )


def argument_error(schema, arguments):
    if schema is None:
        return None
    try:
        Draft202012Validator.check_schema(schema)
        # Scenario schemas cannot initiate remote or local resource retrieval.
        return next(Draft202012Validator(schema, registry=Registry()).iter_errors(arguments), None)
    except (SchemaError, Unresolvable) as exc:
        raise ValueError("Tool schema is invalid or references an unavailable resource") from exc


def contract_violation(schema, arguments, original):
    if not isinstance(arguments, dict) or FORBIDDEN_PROPERTY not in arguments:
        return False
    error = argument_error(schema, arguments)
    return (
        schema is not None
        and isinstance(original, dict)
        and original != arguments
        and argument_error(schema, original) is None
        and error is not None
        and error.validator == "additionalProperties"
    )
