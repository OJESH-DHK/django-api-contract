"""The workflow this package exists for: an API changes, Postman follows."""

import copy
import json

from django_api_contract.postman import build_collection, synchronize_collection

from .conftest import all_items, find_item, identities

CUSTOMER = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
    "required": ["name", "email"],
}

SCRIPT = {
    "listen": "test",
    "script": {"type": "text/javascript", "exec": ["pm.test('is ok', () => {});"]},
}


def _retrieve(operation_id, lookup=None):
    operation = {
        "operationId": operation_id,
        "tags": ["customers"],
        "responses": {
            "200": {"description": "ok", "content": {"application/json": {"schema": CUSTOMER}}}
        },
    }
    if lookup:
        operation["parameters"] = [
            {"name": lookup, "in": "path", "required": True, "schema": {"type": "string"}}
        ]
    return operation


def initial_schema():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Customers API", "version": "1.0.0"},
        "paths": {
            "/customers/": {
                "get": _retrieve("customers-list"),
                "post": {
                    "operationId": "customers-create",
                    "tags": ["customers"],
                    "requestBody": {"content": {"application/json": {"schema": CUSTOMER}}},
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {"application/json": {"schema": CUSTOMER}},
                        }
                    },
                },
            },
            "/customers/{id}/": {"get": _retrieve("customers-retrieve", "id")},
        },
    }


def evolved_schema():
    """Lookup field renamed to public_id, plus a new DELETE endpoint."""
    schema = initial_schema()
    detail = schema["paths"].pop("/customers/{id}/")
    detail["get"]["parameters"][0]["name"] = "public_id"
    detail["delete"] = {
        "operationId": "customers-destroy",
        "tags": ["customers"],
        "parameters": [
            {"name": "public_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        "responses": {"204": {"description": "deleted"}},
    }
    schema["paths"]["/customers/{public_id}/"] = detail
    return schema


def customized_collection(settings_obj):
    collection = build_collection(initial_schema(), settings_obj)
    find_item(collection, "GET /customers/{id}/")["event"] = [copy.deepcopy(SCRIPT)]
    find_item(collection, "GET /customers/")["name"] = "List customers"
    collection["item"][0]["item"].append(
        {"name": "Manual health check", "request": {"method": "GET", "url": {"raw": "{{base_url}}/health/"}}}
    )
    return collection


def test_untouched_endpoints_are_left_alone(settings_obj):
    before = customized_collection(settings_obj)
    result = synchronize_collection(evolved_schema(), copy.deepcopy(before), settings_obj)
    assert "GET /customers/" in result.unchanged
    assert "POST /customers/" in result.unchanged


def test_renamed_lookup_updates_the_existing_request(settings_obj):
    before = customized_collection(settings_obj)
    result = synchronize_collection(evolved_schema(), copy.deepcopy(before), settings_obj)

    assert find_item(result.collection, "GET /customers/{id}/") is None
    moved = find_item(result.collection, "GET /customers/{public_id}/")
    assert moved is not None
    assert moved["request"]["url"]["raw"].endswith("/customers/:public_id/")
    assert ("GET /customers/{id}/", "GET /customers/{public_id}/") in result.renamed


def test_new_endpoint_is_created(settings_obj):
    before = customized_collection(settings_obj)
    result = synchronize_collection(evolved_schema(), copy.deepcopy(before), settings_obj)
    assert result.created == ["DELETE /customers/{public_id}/"]


def test_nothing_is_archived_or_lost(settings_obj):
    before = customized_collection(settings_obj)
    result = synchronize_collection(evolved_schema(), copy.deepcopy(before), settings_obj)
    assert result.archived == []
    assert result.removed == []


def test_custom_script_survives_the_rename(settings_obj):
    before = customized_collection(settings_obj)
    result = synchronize_collection(evolved_schema(), copy.deepcopy(before), settings_obj)
    assert find_item(result.collection, "GET /customers/{public_id}/")["event"] == [SCRIPT]


def test_custom_name_survives(settings_obj):
    before = customized_collection(settings_obj)
    result = synchronize_collection(evolved_schema(), copy.deepcopy(before), settings_obj)
    assert find_item(result.collection, "GET /customers/")["name"] == "List customers"


def test_manual_request_survives(settings_obj):
    before = customized_collection(settings_obj)
    result = synchronize_collection(evolved_schema(), copy.deepcopy(before), settings_obj)
    assert "Manual health check" in [item["name"] for item in all_items(result.collection)]


def test_second_sync_is_a_no_op(settings_obj):
    before = customized_collection(settings_obj)
    schema = evolved_schema()
    first = synchronize_collection(schema, copy.deepcopy(before), settings_obj)
    second = synchronize_collection(schema, copy.deepcopy(first.collection), settings_obj)

    assert second.created == []
    assert second.updated == []
    assert second.renamed == []
    assert json.dumps(second.collection, sort_keys=True) == json.dumps(
        first.collection, sort_keys=True
    )


def test_repeated_sync_leaves_no_duplicates(settings_obj):
    schema = evolved_schema()
    current = customized_collection(settings_obj)
    for _ in range(5):
        current = synchronize_collection(schema, copy.deepcopy(current), settings_obj).collection

    listing = identities(current)
    assert len(listing) == len(set(listing))
    names = [item["name"] for item in all_items(current)]
    assert names.count("Manual health check") == 1
    folders = [folder["name"] for folder in current["item"]]
    assert len(folders) == len(set(folders))
