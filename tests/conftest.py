import copy

import pytest

from django_api_contract.conf import ContractSettings
from django_api_contract.postman import build_collection
from django_api_contract.schema import generate_schema, normalize_schema


@pytest.fixture
def settings_obj(tmp_path):
    return ContractSettings(
        {
            "OPENAPI_OUTPUT": str(tmp_path / "openapi.json"),
            "POSTMAN_OUTPUT": str(tmp_path / "postman_collection.json"),
        }
    )


@pytest.fixture(scope="session")
def raw_schema():
    return normalize_schema(generate_schema())


@pytest.fixture
def schema(raw_schema):
    return copy.deepcopy(raw_schema)


@pytest.fixture
def collection(schema, settings_obj):
    return build_collection(schema, settings_obj)


def find_item(collection, identity):
    for folder in collection["item"]:
        for item in folder.get("item", []):
            if item.get("x-api-contract", {}).get("identity") == identity:
                return item
    return None


def all_items(collection):
    items = []
    for entry in collection["item"]:
        if isinstance(entry.get("item"), list):
            items.extend(entry["item"])
        else:
            items.append(entry)
    return items


def identities(collection):
    return [
        item.get("x-api-contract", {}).get("identity")
        for item in all_items(collection)
        if item.get("x-api-contract", {}).get("identity")
    ]


def rename_path(schema, old_path, new_path, old_param=None, new_param=None):
    """Move a path, optionally renaming one of its path parameters."""
    result = copy.deepcopy(schema)
    item = result["paths"].pop(old_path)
    if old_param and new_param:
        for operation in item.values():
            for parameter in operation.get("parameters", []):
                if parameter.get("name") == old_param:
                    parameter["name"] = new_param
    result["paths"][new_path] = item
    return normalize_schema(result)


def drop_operation(schema, path, method=None):
    result = copy.deepcopy(schema)
    if method is None:
        result["paths"].pop(path)
    else:
        result["paths"][path].pop(method)
    return normalize_schema(result)
