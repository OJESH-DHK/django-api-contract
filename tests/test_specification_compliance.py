"""Validate the generated artifacts against the published specifications."""

import json
import urllib.error
import urllib.request

import pytest

POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def test_generated_schema_is_valid_openapi(schema):
    openapi_spec_validator = pytest.importorskip("openapi_spec_validator")
    openapi_spec_validator.validate(schema)


def test_empty_api_still_produces_valid_openapi(settings_obj):
    openapi_spec_validator = pytest.importorskip("openapi_spec_validator")
    openapi_spec_validator.validate(
        {
            "openapi": "3.0.3",
            "info": {"title": "Empty", "version": "1.0.0"},
            "paths": {},
        }
    )


@pytest.fixture(scope="module")
def postman_schema():
    jsonschema = pytest.importorskip("jsonschema")
    try:
        with urllib.request.urlopen(POSTMAN_SCHEMA_URL, timeout=20) as response:
            return jsonschema, json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"Postman schema unavailable: {exc}")


def test_generated_collection_is_valid_postman_v21(collection, postman_schema):
    jsonschema, schema = postman_schema
    jsonschema.validate(collection, schema)


def test_synchronized_collection_is_still_valid_postman_v21(
    schema, collection, settings_obj, postman_schema
):
    import copy

    from django_api_contract.postman import synchronize_collection

    jsonschema, postman = postman_schema
    existing = copy.deepcopy(collection)
    existing["item"][0]["item"].append(
        {"name": "Manual check", "request": {"method": "GET", "url": {"raw": "{{base_url}}/x/"}}}
    )
    result = synchronize_collection(schema, existing, settings_obj)
    jsonschema.validate(result.collection, postman)
