import copy

from django_api_contract.diff import ChangeKind, Severity, compare_schemas, render_diff


def make_schema(properties=None, required=None, parameters=None, response=None, security=None):
    body_schema = {
        "type": "object",
        "properties": properties if properties is not None else {"name": {"type": "string"}},
        "required": required if required is not None else [],
    }
    operation = {
        "operationId": "customers-create",
        "tags": ["customers"],
        "parameters": parameters or [],
        "requestBody": {"content": {"application/json": {"schema": body_schema}}},
        "responses": {
            "201": {
                "description": "created",
                "content": {
                    "application/json": {
                        "schema": response
                        or {"type": "object", "properties": {"id": {"type": "integer"}}}
                    }
                },
            }
        },
    }
    if security is not None:
        operation["security"] = security
    return {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1.0.0"},
        "paths": {"/api/v1/customers/": {"post": operation}},
    }


ENDPOINT = "POST /api/v1/customers/"


def details(diff):
    return [change.detail for change in diff.sorted_changes()]


def test_no_changes_between_identical_schemas():
    schema = make_schema()
    assert compare_schemas(schema, copy.deepcopy(schema)).is_empty


def test_added_endpoint_is_non_breaking():
    old = make_schema()
    new = copy.deepcopy(old)
    new["paths"]["/api/v1/orders/"] = {"get": {"responses": {"200": {"description": "ok"}}}}
    diff = compare_schemas(old, new)
    assert diff.added_endpoints == ["GET /api/v1/orders/"]
    assert diff.breaking == []


def test_removed_endpoint_is_breaking():
    old = make_schema()
    new = copy.deepcopy(old)
    new["paths"] = {}
    diff = compare_schemas(old, new)
    assert diff.removed_endpoints == [ENDPOINT]
    assert diff.breaking[0].kind is ChangeKind.REMOVED


def test_new_optional_request_field_is_non_breaking():
    old = make_schema()
    new = make_schema(properties={"name": {"type": "string"}, "phone": {"type": "string"}})
    diff = compare_schemas(old, new)
    assert diff.breaking == []
    assert "request field phone added" in details(diff)


def test_new_required_request_field_is_breaking():
    old = make_schema()
    new = make_schema(
        properties={"name": {"type": "string"}, "email": {"type": "string"}},
        required=["email"],
    )
    diff = compare_schemas(old, new)
    assert any("email added as required" in change.detail for change in diff.breaking)


def test_optional_becoming_required_is_breaking():
    old = make_schema()
    new = make_schema(required=["name"])
    diff = compare_schemas(old, new)
    assert any("optional to required" in change.detail for change in diff.breaking)


def test_required_becoming_optional_is_non_breaking():
    old = make_schema(required=["name"])
    new = make_schema()
    diff = compare_schemas(old, new)
    assert diff.breaking == []


def test_request_field_type_change_is_breaking():
    old = make_schema()
    new = make_schema(properties={"name": {"type": "integer"}})
    diff = compare_schemas(old, new)
    breaking = diff.breaking[0]
    assert breaking.before == "string"
    assert breaking.after == "integer"


def test_response_field_removal_is_breaking():
    old = make_schema()
    new = make_schema(response={"type": "object", "properties": {}})
    diff = compare_schemas(old, new)
    assert any("response field id removed" in change.detail for change in diff.breaking)


def test_response_field_addition_is_non_breaking():
    old = make_schema()
    new = make_schema(
        response={
            "type": "object",
            "properties": {"id": {"type": "integer"}, "created": {"type": "string"}},
        }
    )
    assert compare_schemas(old, new).breaking == []


def test_response_type_change_is_breaking():
    old = make_schema()
    new = make_schema(response={"type": "object", "properties": {"id": {"type": "string"}}})
    assert compare_schemas(old, new).breaking


def test_dropping_an_enum_value_is_breaking():
    old = make_schema(properties={"tier": {"type": "string", "enum": ["free", "pro"]}})
    new = make_schema(properties={"tier": {"type": "string", "enum": ["free"]}})
    diff = compare_schemas(old, new)
    assert any("dropped enum value" in change.detail for change in diff.breaking)


def test_adding_a_request_enum_value_is_non_breaking():
    old = make_schema(properties={"tier": {"type": "string", "enum": ["free"]}})
    new = make_schema(properties={"tier": {"type": "string", "enum": ["free", "pro"]}})
    assert compare_schemas(old, new).breaking == []


def test_adding_a_response_enum_value_is_flagged_as_possible():
    old = make_schema(
        response={"type": "object", "properties": {"s": {"enum": ["a"], "type": "string"}}}
    )
    new = make_schema(
        response={"type": "object", "properties": {"s": {"enum": ["a", "b"], "type": "string"}}}
    )
    diff = compare_schemas(old, new)
    assert diff.breaking == []
    assert diff.possibly_breaking


def test_new_optional_query_parameter_is_non_breaking():
    old = make_schema()
    new = make_schema(parameters=[{"name": "page", "in": "query", "schema": {"type": "integer"}}])
    assert compare_schemas(old, new).breaking == []


def test_new_required_query_parameter_is_breaking():
    old = make_schema()
    new = make_schema(
        parameters=[
            {"name": "tenant", "in": "query", "required": True, "schema": {"type": "string"}}
        ]
    )
    assert compare_schemas(old, new).breaking


def test_removing_a_path_parameter_is_breaking():
    old = make_schema(
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}]
    )
    new = make_schema()
    assert compare_schemas(old, new).breaking


def test_parameter_type_change_is_breaking():
    old = make_schema(
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}]
    )
    new = make_schema(
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}]
    )
    change = compare_schemas(old, new).breaking[0]
    assert (change.before, change.after) == ("integer", "string")


def test_authentication_change_is_breaking():
    old = make_schema(security=[])
    new = make_schema(security=[{"tokenAuth": []}])
    diff = compare_schemas(old, new)
    assert any(change.detail == "authentication" for change in diff.breaking)


def test_nullable_removal_in_a_response_is_breaking():
    old = make_schema(
        response={"type": "object", "properties": {"id": {"type": "integer", "nullable": True}}}
    )
    new = make_schema(response={"type": "object", "properties": {"id": {"type": "integer"}}})
    assert compare_schemas(old, new).breaking


def test_nested_object_fields_are_compared():
    nested = {
        "type": "object",
        "properties": {"address": {"type": "object", "properties": {"city": {"type": "string"}}}},
    }
    old = make_schema(properties=nested["properties"])
    new = copy.deepcopy(nested["properties"])
    new["address"]["properties"]["city"]["type"] = "integer"
    diff = compare_schemas(old, make_schema(properties=new))
    assert any("address.city" in change.detail for change in diff.breaking)


def test_array_items_are_compared():
    old = make_schema(
        properties={
            "tags": {
                "type": "array",
                "items": {"type": "object", "properties": {"n": {"type": "string"}}},
            }
        }
    )
    new = make_schema(
        properties={
            "tags": {
                "type": "array",
                "items": {"type": "object", "properties": {"n": {"type": "integer"}}},
            }
        }
    )
    assert compare_schemas(old, new).breaking


def test_success_status_change_is_possibly_breaking():
    old = make_schema()
    new = copy.deepcopy(old)
    operation = new["paths"]["/api/v1/customers/"]["post"]
    operation["responses"] = {"200": operation["responses"].pop("201")}
    diff = compare_schemas(old, new)
    assert any(change.detail == "success status code" for change in diff.possibly_breaking)


def test_report_lists_sections_and_breaking_changes():
    old = make_schema()
    new = make_schema(properties={"name": {"type": "integer"}})
    report = render_diff(compare_schemas(old, new))
    assert "Changed:" in report
    assert "Breaking changes:" in report
    assert "string -> integer" in report


def test_report_is_quiet_when_nothing_changed():
    schema = make_schema()
    assert render_diff(compare_schemas(schema, copy.deepcopy(schema))) == "No API changes."


def test_severity_values_are_stable():
    assert Severity.BREAKING.value == "breaking"
    assert Severity.POSSIBLY_BREAKING.value == "possibly-breaking"
