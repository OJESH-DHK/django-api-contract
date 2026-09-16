import copy
import json

from django_api_contract.constants import METADATA_KEY
from django_api_contract.postman import build_collection, synchronize_collection

from .conftest import all_items, drop_operation, find_item, identities, rename_path

SCRIPT = {
    "listen": "test",
    "script": {"type": "text/javascript", "exec": ["pm.test('status', () => {});"]},
}
MANUAL_REQUEST = {
    "name": "Manual smoke check",
    "request": {"method": "GET", "url": {"raw": "{{base_url}}/health/"}},
}


def sync(schema, existing, settings_obj):
    return synchronize_collection(schema, copy.deepcopy(existing), settings_obj)


def test_first_run_creates_everything(schema, settings_obj):
    result = synchronize_collection(schema, None, settings_obj)
    assert len(result.created) == len(all_items(result.collection))
    assert result.updated == []


def test_second_run_changes_nothing(schema, collection, settings_obj):
    result = sync(schema, collection, settings_obj)
    assert result.created == []
    assert result.updated == []
    assert json.dumps(result.collection, sort_keys=True) == json.dumps(
        collection, sort_keys=True
    )


def test_ten_runs_stay_identical(schema, collection, settings_obj):
    current = copy.deepcopy(collection)
    for _ in range(10):
        current = sync(schema, current, settings_obj).collection
    assert json.dumps(current, sort_keys=True) == json.dumps(collection, sort_keys=True)


def test_repeated_sync_never_duplicates_requests(schema, collection, settings_obj):
    current = copy.deepcopy(collection)
    for _ in range(5):
        current = sync(schema, current, settings_obj).collection
    listing = identities(current)
    assert len(listing) == len(set(listing))


def test_repeated_sync_never_duplicates_folders(schema, collection, settings_obj):
    current = copy.deepcopy(collection)
    for _ in range(5):
        current = sync(schema, current, settings_obj).collection
    names = [folder["name"] for folder in current["item"]]
    assert len(names) == len(set(names))


def test_new_endpoint_is_created(schema, collection, settings_obj):
    reduced = drop_operation(schema, "/api/v1/customers/{public_id}/", "delete")
    trimmed = build_collection(reduced, settings_obj)
    result = sync(schema, trimmed, settings_obj)
    assert result.created == ["DELETE /api/v1/customers/{public_id}/"]


def test_existing_request_is_updated_not_duplicated(schema, collection, settings_obj):
    changed = copy.deepcopy(schema)
    changed["paths"]["/api/v1/customers/"]["get"]["parameters"].append(
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}}
    )
    result = sync(changed, collection, settings_obj)
    listing = identities(result.collection)
    assert listing.count("GET /api/v1/customers/") == 1
    assert "GET /api/v1/customers/" in result.updated


def test_query_parameter_is_added_without_duplication(schema, collection, settings_obj):
    changed = copy.deepcopy(schema)
    changed["paths"]["/api/v1/customers/"]["get"]["parameters"].append(
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}}
    )
    result = sync(changed, collection, settings_obj)
    item = find_item(result.collection, "GET /api/v1/customers/")
    keys = [entry["key"] for entry in item["request"]["url"]["query"]]
    assert keys.count("limit") == 1
    assert len(keys) == len(set(keys))


def test_removed_query_parameter_disappears(schema, collection, settings_obj):
    changed = copy.deepcopy(schema)
    operation = changed["paths"]["/api/v1/customers/"]["get"]
    operation["parameters"] = [p for p in operation["parameters"] if p["name"] != "page"]
    result = sync(changed, collection, settings_obj)
    item = find_item(result.collection, "GET /api/v1/customers/")
    keys = [entry["key"] for entry in item["request"]["url"].get("query", [])]
    assert "page" not in keys


def test_headers_are_not_duplicated(schema, collection, settings_obj):
    result = sync(schema, collection, settings_obj)
    for item in all_items(result.collection):
        keys = [entry["key"] for entry in item["request"].get("header", [])]
        assert len(keys) == len(set(keys))


def test_manual_request_is_preserved(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    existing["item"][0]["item"].append(copy.deepcopy(MANUAL_REQUEST))
    result = sync(schema, existing, settings_obj)
    names = [item["name"] for item in all_items(result.collection)]
    assert "Manual smoke check" in names
    assert result.preserved_manual == ["Manual smoke check"]


def test_manual_folder_is_preserved(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    existing["item"].append(
        {"name": "Scratch", "item": [copy.deepcopy(MANUAL_REQUEST)]}
    )
    result = sync(schema, existing, settings_obj)
    assert "Scratch" in [folder["name"] for folder in result.collection["item"]]


def test_test_scripts_survive(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    target = find_item(existing, "GET /api/v1/customers/")
    target["event"] = [copy.deepcopy(SCRIPT)]
    result = sync(schema, existing, settings_obj)
    assert find_item(result.collection, "GET /api/v1/customers/")["event"] == [SCRIPT]


def test_renamed_request_name_survives(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    find_item(existing, "GET /api/v1/customers/")["name"] = "List all customers"
    result = sync(schema, existing, settings_obj)
    assert find_item(result.collection, "GET /api/v1/customers/")["name"] == (
        "List all customers"
    )


def test_custom_header_survives(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    target = find_item(existing, "GET /api/v1/customers/")
    target["request"]["header"].append({"key": "X-Tenant", "value": "acme"})
    result = sync(schema, existing, settings_obj)
    headers = find_item(result.collection, "GET /api/v1/customers/")["request"]["header"]
    assert {"key": "X-Tenant", "value": "acme"} in headers


def test_custom_query_value_survives(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    target = find_item(existing, "GET /api/v1/customers/")
    page = next(e for e in target["request"]["url"]["query"] if e["key"] == "page")
    page["value"] = "7"
    page["disabled"] = False
    result = sync(schema, existing, settings_obj)
    merged = find_item(result.collection, "GET /api/v1/customers/")["request"]["url"]["query"]
    page = next(entry for entry in merged if entry["key"] == "page")
    assert page["value"] == "7"
    assert page["disabled"] is False


def test_custom_auth_survives(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    target = find_item(existing, "GET /api/v1/customers/")
    target["request"]["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{t}}"}]}
    result = sync(schema, existing, settings_obj)
    assert find_item(result.collection, "GET /api/v1/customers/")["request"]["auth"]["bearer"]


def test_edited_request_body_survives(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    target = find_item(existing, "POST /api/v1/customers/")
    target["request"]["body"]["raw"] = '{"name": "my fixture"}'
    result = sync(schema, existing, settings_obj)
    merged = find_item(result.collection, "POST /api/v1/customers/")
    assert merged["request"]["body"]["raw"] == '{"name": "my fixture"}'
    assert "body" in result.preserved_edits["POST /api/v1/customers/"]


def test_untouched_request_body_is_refreshed(schema, collection, settings_obj):
    changed = copy.deepcopy(schema)
    changed["components"]["schemas"]["Customer"]["properties"]["nickname"] = {"type": "string"}
    result = sync(changed, collection, settings_obj)
    body = json.loads(find_item(result.collection, "POST /api/v1/customers/")["request"]["body"]["raw"])
    assert "nickname" in body


def test_manual_response_example_is_preserved(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    target = find_item(existing, "GET /api/v1/customers/{public_id}/")
    target["response"].append({"name": "Not found", "code": 404, "body": "{}"})
    result = sync(schema, existing, settings_obj)
    merged = find_item(result.collection, "GET /api/v1/customers/{public_id}/")
    assert any(response["name"] == "Not found" for response in merged["response"])


def test_edited_response_example_is_preserved(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    target = find_item(existing, "GET /api/v1/customers/{public_id}/")
    target["response"][0]["body"] = '{"hand": "written"}'
    result = sync(schema, existing, settings_obj)
    merged = find_item(result.collection, "GET /api/v1/customers/{public_id}/")
    assert merged["response"][0]["body"] == '{"hand": "written"}'


def test_collection_variable_value_is_not_overwritten(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    existing["variable"][0]["value"] = "https://staging.example.com"
    result = sync(schema, existing, settings_obj)
    assert result.collection["variable"][0]["value"] == "https://staging.example.com"


def test_extra_collection_variables_are_kept(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    existing["variable"].append({"key": "tenant", "value": "acme"})
    result = sync(schema, existing, settings_obj)
    keys = [entry["key"] for entry in result.collection["variable"]]
    assert "tenant" in keys


def test_folder_id_is_preserved(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    existing["item"][0]["id"] = "folder-id-kept"
    result = sync(schema, existing, settings_obj)
    assert result.collection["item"][0]["id"] == "folder-id-kept"


def test_request_id_is_preserved(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    find_item(existing, "GET /api/v1/customers/")["id"] = "request-id-kept"
    result = sync(schema, existing, settings_obj)
    assert find_item(result.collection, "GET /api/v1/customers/")["id"] == "request-id-kept"


def test_collection_id_is_preserved(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    existing["info"]["_postman_id"] = "kept-collection-id"
    result = sync(schema, existing, settings_obj)
    assert result.collection["info"]["_postman_id"] == "kept-collection-id"


def test_deleted_endpoint_is_archived_by_default(schema, collection, settings_obj):
    reduced = drop_operation(schema, "/api/v1/subscriptions/{id}/")
    result = sync(reduced, collection, settings_obj)
    assert result.archived == ["GET /api/v1/subscriptions/{id}/"]
    assert result.removed == []
    names = [item["name"] for item in all_items(result.collection)]
    assert any("[removed from API]" in name for name in names)


def test_deleted_endpoint_is_removed_when_configured(schema, collection, settings_obj):
    strict = settings_obj.with_overrides(REMOVE_DELETED_ENDPOINTS=True)
    reduced = drop_operation(schema, "/api/v1/subscriptions/{id}/")
    result = synchronize_collection(reduced, copy.deepcopy(collection), strict)
    assert result.removed == ["GET /api/v1/subscriptions/{id}/"]
    assert find_item(result.collection, "GET /api/v1/subscriptions/{id}/") is None


def test_strict_cleanup_never_touches_manual_requests(schema, collection, settings_obj):
    strict = settings_obj.with_overrides(REMOVE_DELETED_ENDPOINTS=True)
    existing = copy.deepcopy(collection)
    existing["item"][0]["item"].append(copy.deepcopy(MANUAL_REQUEST))
    reduced = drop_operation(schema, "/api/v1/subscriptions/{id}/")
    result = synchronize_collection(reduced, existing, strict)
    names = [item["name"] for item in all_items(result.collection)]
    assert "Manual smoke check" in names


def test_archiving_can_be_disabled(schema, collection, settings_obj):
    plain = settings_obj.with_overrides(ARCHIVE_DELETED_ENDPOINTS=False)
    reduced = drop_operation(schema, "/api/v1/subscriptions/{id}/")
    result = synchronize_collection(reduced, copy.deepcopy(collection), plain)
    names = [item["name"] for item in all_items(result.collection)]
    assert not any("[removed from API]" in name for name in names)


def test_path_parameter_rename_updates_in_place(schema, collection, settings_obj):
    renamed = rename_path(
        schema,
        "/api/v1/addresses/{id}/",
        "/api/v1/addresses/{public_id}/",
        "id",
        "public_id",
    )
    result = sync(renamed, collection, settings_obj)
    assert result.created == []
    assert result.archived == []
    assert ("GET /api/v1/addresses/{id}/", "GET /api/v1/addresses/{public_id}/") in result.renamed


def test_rename_keeps_custom_scripts(schema, collection, settings_obj):
    existing = copy.deepcopy(collection)
    find_item(existing, "GET /api/v1/addresses/{id}/")["event"] = [copy.deepcopy(SCRIPT)]
    renamed = rename_path(
        schema, "/api/v1/addresses/{id}/", "/api/v1/addresses/{public_id}/", "id", "public_id"
    )
    result = sync(renamed, existing, settings_obj)
    moved = find_item(result.collection, "GET /api/v1/addresses/{public_id}/")
    assert moved["event"] == [SCRIPT]


def test_rename_detection_can_be_disabled(schema, collection, settings_obj):
    disabled = settings_obj.with_overrides(DETECT_RENAMES=False)
    renamed = rename_path(
        schema, "/api/v1/addresses/{id}/", "/api/v1/addresses/{public_id}/", "id", "public_id"
    )
    stripped = copy.deepcopy(collection)
    for item in all_items(stripped):
        item[METADATA_KEY].pop("operation_id", None)
    result = synchronize_collection(renamed, stripped, disabled)
    assert result.created
    assert result.archived


def test_method_change_is_reported_as_add_and_archive(schema, collection, settings_obj):
    changed = copy.deepcopy(schema)
    operation = changed["paths"]["/api/v1/customers/import/"].pop("post")
    operation["operationId"] = "customers-import-put"
    changed["paths"]["/api/v1/customers/import/"]["put"] = operation
    result = sync(changed, collection, settings_obj)
    assert "PUT /api/v1/customers/import/" in result.created
    assert "POST /api/v1/customers/import/" in result.archived


def test_versioned_endpoints_are_not_merged(schema, collection, settings_obj):
    versioned = copy.deepcopy(schema)
    v2 = copy.deepcopy(versioned["paths"]["/api/v1/customers/"])
    for operation in v2.values():
        operation["operationId"] = operation["operationId"].replace("v1", "v2") + "-v2"
    versioned["paths"]["/api/v2/customers/"] = v2
    result = sync(versioned, collection, settings_obj)
    listing = identities(result.collection)
    assert "GET /api/v1/customers/" in listing
    assert "GET /api/v2/customers/" in listing
    assert len(listing) == len(set(listing))
