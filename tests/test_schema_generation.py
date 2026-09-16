import copy

import pytest

from django_api_contract.exceptions import SchemaValidationError
from django_api_contract.schema import generate_schema, normalize_schema, validate_schema
from django_api_contract.schema.normalizer import iter_operations
from django_api_contract.schema.validator import collect_problems


def test_schema_covers_every_registered_route(schema):
    paths = set(schema["paths"])
    assert "/api/v1/customers/" in paths
    assert "/api/v1/customers/{public_id}/" in paths
    assert "/api/v1/customers/import/" in paths
    assert "/api/v1/subscriptions/" in paths


def test_schema_validates_cleanly(schema):
    assert collect_problems(schema) == []


def test_generation_is_deterministic():
    first = normalize_schema(generate_schema())
    second = normalize_schema(generate_schema())
    assert first == second


def test_normalization_is_idempotent(schema):
    assert normalize_schema(copy.deepcopy(schema)) == schema


def test_paths_and_methods_are_sorted(schema):
    assert list(schema["paths"]) == sorted(schema["paths"])
    detail = schema["paths"]["/api/v1/customers/{public_id}/"]
    methods = [key for key in detail if key in {"get", "put", "patch", "delete"}]
    assert methods == ["get", "put", "patch", "delete"]


def test_required_lists_are_sorted(schema):
    for definition in schema["components"]["schemas"].values():
        required = definition.get("required")
        if required:
            assert required == sorted(required)


def test_nested_serializer_is_exposed(schema):
    customer = schema["components"]["schemas"]["Customer"]
    assert customer["properties"]["addresses"]["type"] == "array"
    assert "$ref" in customer["properties"]["addresses"]["items"]


def test_choice_field_becomes_an_enum(schema):
    tier = schema["components"]["schemas"]["Customer"]["properties"]["tier"]
    target = tier.get("$ref") or tier.get("allOf", [{}])[0].get("$ref")
    assert target, "tier should reference an enum component"
    enum = schema["components"]["schemas"][target.rsplit("/", 1)[-1]]
    assert set(enum["enum"]) == {"free", "pro", "enterprise"}


def test_nullable_field_is_marked(schema):
    phone = schema["components"]["schemas"]["Customer"]["properties"]["phone"]
    assert phone.get("nullable") is True


def test_read_only_fields_are_marked(schema):
    customer = schema["components"]["schemas"]["Customer"]
    assert customer["properties"]["created_at"].get("readOnly") is True


def test_file_upload_endpoint_uses_multipart(schema):
    operation = schema["paths"]["/api/v1/customers/import/"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]


def test_pagination_parameters_are_present(schema):
    parameters = schema["paths"]["/api/v1/customers/"]["get"]["parameters"]
    assert any(parameter["name"] == "page" for parameter in parameters)


def test_iter_operations_is_ordered(schema):
    operations = iter_operations(schema)
    assert operations == sorted(
        operations,
        key=lambda entry: (entry[0], ["get", "post", "put", "patch", "delete"].index(entry[1])),
    )


def test_validate_rejects_undeclared_path_parameter(schema):
    broken = copy.deepcopy(schema)
    operation = broken["paths"]["/api/v1/customers/{public_id}/"]["get"]
    operation["parameters"] = [
        parameter for parameter in operation["parameters"] if parameter["name"] != "public_id"
    ]
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_schema(broken)
    assert any("public_id" in problem for problem in excinfo.value.problems)


def test_validate_rejects_duplicate_operation_ids(schema):
    broken = copy.deepcopy(schema)
    broken["paths"]["/api/v1/customers/"]["get"]["operationId"] = "duplicated"
    broken["paths"]["/api/v1/customers/"]["post"]["operationId"] = "duplicated"
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_schema(broken)
    assert any("duplicate operationId" in problem for problem in excinfo.value.problems)


def test_validate_rejects_unresolved_reference(schema):
    broken = copy.deepcopy(schema)
    broken["paths"]["/api/v1/customers/"]["get"]["responses"]["200"] = {
        "description": "ok",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}},
    }
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_schema(broken)
    assert any("Missing" in problem for problem in excinfo.value.problems)


def test_validate_rejects_operation_without_responses(schema):
    broken = copy.deepcopy(schema)
    broken["paths"]["/api/v1/customers/"]["get"]["responses"] = {}
    with pytest.raises(SchemaValidationError):
        validate_schema(broken)
