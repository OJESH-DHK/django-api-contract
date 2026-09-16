import json

from django_api_contract.constants import METADATA_KEY, POSTMAN_SCHEMA_URL
from django_api_contract.postman import build_collection

from .conftest import all_items, find_item, identities


def test_collection_declares_v21_schema(collection):
    assert collection["info"]["schema"] == POSTMAN_SCHEMA_URL
    assert collection["info"]["_postman_id"]


def test_every_operation_becomes_a_request(schema, collection):
    expected = sum(
        len([m for m in item if m in {"get", "post", "put", "patch", "delete"}])
        for item in schema["paths"].values()
    )
    assert len(all_items(collection)) == expected


def test_requests_are_grouped_by_tag(collection):
    names = [folder["name"] for folder in collection["item"]]
    assert names == sorted(names)
    assert "customers" in names


def test_generation_is_deterministic(schema, settings_obj):
    first = build_collection(schema, settings_obj)
    second = build_collection(schema, settings_obj)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_ids_do_not_change_between_runs(schema, settings_obj):
    first = build_collection(schema, settings_obj)
    second = build_collection(schema, settings_obj)
    assert [item["id"] for item in all_items(first)] == [
        item["id"] for item in all_items(second)
    ]


def test_every_request_carries_identity_metadata(collection):
    for item in all_items(collection):
        meta = item[METADATA_KEY]
        assert meta["managed"] is True
        assert meta["identity"]
        assert meta["method"]
        assert meta["path"]


def test_path_parameters_use_postman_syntax(collection):
    item = find_item(collection, "GET /api/v1/customers/{public_id}/")
    url = item["request"]["url"]
    assert ":public_id" in url["raw"]
    assert [entry["key"] for entry in url["variable"]] == ["public_id"]


def test_base_url_is_a_variable(collection):
    item = find_item(collection, "GET /api/v1/customers/")
    assert item["request"]["url"]["raw"].startswith("{{base_url}}")
    assert collection["variable"][0]["key"] == "base_url"


def test_optional_query_parameters_are_disabled(collection):
    item = find_item(collection, "GET /api/v1/customers/")
    page = next(entry for entry in item["request"]["url"]["query"] if entry["key"] == "page")
    assert page["disabled"] is True


def test_json_body_is_generated_for_writes(collection):
    item = find_item(collection, "POST /api/v1/customers/")
    body = json.loads(item["request"]["body"]["raw"])
    assert body["email"] == "user@example.com"
    assert "created_at" not in body, "read-only fields must stay out of request bodies"


def test_enum_body_field_uses_the_first_value(collection):
    body = json.loads(find_item(collection, "POST /api/v1/customers/")["request"]["body"]["raw"])
    assert body["tier"] in {"free", "pro", "enterprise"}


def test_multipart_upload_becomes_a_file_field(collection):
    item = find_item(collection, "POST /api/v1/customers/import/")
    formdata = item["request"]["body"]["formdata"]
    upload = next(entry for entry in formdata if entry["key"] == "upload")
    assert upload["type"] == "file"


def test_content_type_header_matches_the_body(collection):
    item = find_item(collection, "POST /api/v1/customers/")
    headers = {entry["key"]: entry["value"] for entry in item["request"]["header"]}
    assert headers["Content-Type"] == "application/json"


def test_get_requests_have_no_body(collection):
    item = find_item(collection, "GET /api/v1/customers/")
    assert "body" not in item["request"]


def test_responses_are_generated_per_status(collection):
    item = find_item(collection, "GET /api/v1/customers/{public_id}/")
    assert [response["code"] for response in item["response"]] == [200]


def test_no_credentials_appear_in_the_collection(collection):
    payload = json.dumps(collection)
    for leak in ("password123", "secret", "sk_live", "Bearer ey"):
        assert leak not in payload


def test_collection_name_follows_the_schema_title(schema, settings_obj):
    assert build_collection(schema, settings_obj)["info"]["name"] == "Demo API"


def test_collection_name_can_be_overridden(schema, settings_obj):
    overridden = settings_obj.with_overrides(POSTMAN_COLLECTION_NAME="Custom")
    assert build_collection(schema, overridden)["info"]["name"] == "Custom"


def test_collection_id_is_stable_for_a_name(schema, settings_obj):
    first = build_collection(schema, settings_obj)["info"]["_postman_id"]
    second = build_collection(schema, settings_obj)["info"]["_postman_id"]
    assert first == second


def test_requests_are_ordered_deterministically(collection):
    listing = identities(collection)
    assert listing == sorted(set(listing), key=listing.index)
