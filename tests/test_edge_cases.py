import copy
import json
import os

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_api_contract import service
from django_api_contract.exceptions import PostmanSyncError, SchemaGenerationError
from django_api_contract.postman import build_collection, synchronize_collection
from django_api_contract.utils import atomic_write, load_json
from django_api_contract.schema import generate_schema

from .conftest import all_items, find_item, identities

EMPTY_SCHEMA = {
    "openapi": "3.0.3",
    "info": {"title": "Empty API", "version": "1.0.0"},
    "paths": {},
}


def test_empty_api_produces_an_empty_collection(settings_obj):
    collection = build_collection(EMPTY_SCHEMA, settings_obj)
    assert collection["item"] == []
    assert collection["info"]["name"] == "Empty API"


def test_empty_api_sync_is_stable(settings_obj):
    first = build_collection(EMPTY_SCHEMA, settings_obj)
    result = synchronize_collection(EMPTY_SCHEMA, copy.deepcopy(first), settings_obj)
    assert result.collection == first


def test_large_api_stays_deterministic(settings_obj):
    schema = copy.deepcopy(EMPTY_SCHEMA)
    for index in range(200):
        schema["paths"][f"/api/v1/resource{index:03d}/"] = {
            "get": {
                "operationId": f"resource{index:03d}-list",
                "tags": [f"group{index % 7}"],
                "responses": {"200": {"description": "ok"}},
            }
        }
    first = build_collection(schema, settings_obj)
    second = build_collection(schema, settings_obj)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert len(all_items(first)) == 200


def test_endpoints_that_look_alike_stay_separate(settings_obj):
    schema = copy.deepcopy(EMPTY_SCHEMA)
    for path in ("/api/v1/customers/", "/api/v1/customers", "/api/v2/customers/"):
        schema["paths"][path] = {
            "get": {
                "operationId": f"list{path.replace('/', '-')}",
                "responses": {"200": {"description": "ok"}},
            }
        }
    collection = build_collection(schema, settings_obj)
    listing = identities(collection)
    assert len(listing) == len(set(listing)) == 3


def test_sync_rejects_a_collection_that_is_not_v21(schema, settings_obj):
    with pytest.raises(PostmanSyncError):
        synchronize_collection(schema, {"info": {"name": "broken"}}, settings_obj)


def test_mixed_manual_and_generated_folder(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    existing["item"][0]["item"].insert(0, {"name": "Manual first", "request": {"method": "GET"}})
    existing["item"].append({"name": "Utilities", "item": [{"name": "Ping", "request": {}}]})
    result = synchronize_collection(schema, existing, settings_obj)
    folder_names = [folder["name"] for folder in result.collection["item"]]
    assert "Utilities" in folder_names
    names = [item["name"] for item in all_items(result.collection)]
    assert "Manual first" in names and "Ping" in names


def test_operation_without_tags_lands_in_the_default_folder(settings_obj):
    schema = copy.deepcopy(EMPTY_SCHEMA)
    schema["paths"]["/ping/"] = {
        "get": {"operationId": "ping", "responses": {"200": {"description": "ok"}}}
    }
    collection = build_collection(schema, settings_obj)
    assert collection["item"][0]["name"] == "Default"


def test_recursive_schema_does_not_hang(settings_obj):
    schema = copy.deepcopy(EMPTY_SCHEMA)
    schema["components"] = {
        "schemas": {
            "Node": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "child": {"$ref": "#/components/schemas/Node"},
                },
            }
        }
    }
    schema["paths"]["/nodes/"] = {
        "post": {
            "operationId": "node-create",
            "requestBody": {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Node"}}
                }
            },
            "responses": {"201": {"description": "created"}},
        }
    }
    collection = build_collection(schema, settings_obj)
    body = json.loads(all_items(collection)[0]["request"]["body"]["raw"])
    assert body["name"] == "string"


def test_atomic_write_replaces_the_file(tmp_path):
    target = tmp_path / "out.json"
    atomic_write(str(target), "first\n")
    atomic_write(str(target), "second\n")
    assert target.read_text() == "second\n"


def test_atomic_write_creates_missing_directories(tmp_path):
    target = tmp_path / "nested" / "deep" / "out.json"
    atomic_write(str(target), "{}\n")
    assert target.exists()


def test_failed_write_leaves_the_original_intact(tmp_path, monkeypatch):
    target = tmp_path / "out.json"
    atomic_write(str(target), "original\n")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(str(target), "replacement\n")

    assert target.read_text() == "original\n"
    leftovers = [name for name in os.listdir(tmp_path) if name.startswith(".api-contract-")]
    assert leftovers == []


def test_generation_failure_does_not_touch_existing_files(settings_obj, monkeypatch):
    atomic_write(settings_obj.openapi_path, '{"kept": true}\n')
    atomic_write(settings_obj.postman_path, '{"kept": true}\n')

    def boom(*args, **kwargs):
        raise SchemaGenerationError("router exploded")

    monkeypatch.setattr(service, "generate_schema", boom)
    with pytest.raises(SchemaGenerationError):
        service.build_contract(settings_obj)

    assert load_json(settings_obj.openapi_path) == {"kept": True}
    assert load_json(settings_obj.postman_path) == {"kept": True}


def test_invalid_schema_stops_before_writing(settings_obj, monkeypatch):
    atomic_write(settings_obj.openapi_path, '{"kept": true}\n')

    def invalid(*args, **kwargs):
        return {"openapi": "3.0.3", "info": {}, "paths": {"bad": {}}}

    monkeypatch.setattr(service, "generate_schema", invalid)
    with pytest.raises(Exception):
        service.build_contract(settings_obj)
    assert load_json(settings_obj.openapi_path) == {"kept": True}


def test_corrupt_existing_collection_is_reported(settings_obj):
    atomic_write(settings_obj.postman_path, "{not json")
    with pytest.raises(json.JSONDecodeError):
        service.build_contract(settings_obj)


def test_empty_existing_file_is_treated_as_absent(settings_obj):
    atomic_write(settings_obj.postman_path, "")
    build = service.build_contract(settings_obj)
    assert build.sync.created


def test_generate_writes_both_files(settings_obj, capsys):
    call_command(
        "api_contract",
        "generate",
        "--openapi-output",
        settings_obj.openapi_path,
        "--postman-output",
        settings_obj.postman_path,
    )
    assert os.path.exists(settings_obj.openapi_path)
    assert os.path.exists(settings_obj.postman_path)


def test_check_fails_when_nothing_is_committed(settings_obj):
    with pytest.raises(CommandError):
        call_command(
            "api_contract",
            "check",
            "--openapi-output",
            settings_obj.openapi_path,
            "--postman-output",
            settings_obj.postman_path,
        )


def test_check_passes_after_generate(settings_obj):
    args = (
        "--openapi-output",
        settings_obj.openapi_path,
        "--postman-output",
        settings_obj.postman_path,
    )
    call_command("api_contract", "generate", *args)
    call_command("api_contract", "check", *args)


def test_dry_run_writes_nothing(settings_obj):
    call_command(
        "api_contract",
        "sync",
        "--dry-run",
        "--openapi-output",
        settings_obj.openapi_path,
        "--postman-output",
        settings_obj.postman_path,
    )
    assert not os.path.exists(settings_obj.openapi_path)
    assert not os.path.exists(settings_obj.postman_path)


def test_repeated_generate_produces_identical_bytes(settings_obj):
    args = (
        "--openapi-output",
        settings_obj.openapi_path,
        "--postman-output",
        settings_obj.postman_path,
    )
    call_command("api_contract", "generate", *args)
    first = open(settings_obj.postman_path).read()
    call_command("api_contract", "generate", *args)
    assert open(settings_obj.postman_path).read() == first


def test_generated_files_end_with_a_newline(settings_obj):
    call_command(
        "api_contract",
        "generate",
        "--openapi-output",
        settings_obj.openapi_path,
        "--postman-output",
        settings_obj.postman_path,
    )
    assert open(settings_obj.openapi_path).read().endswith("\n")


def test_unknown_setting_is_rejected():
    from django_api_contract.conf import ContractSettings

    with pytest.raises(AttributeError):
        ContractSettings().NOT_A_SETTING
