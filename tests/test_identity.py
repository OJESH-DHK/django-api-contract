import copy

from django_api_contract.postman.identity import (
    OperationIdentity,
    PreviousOperation,
    build_identities,
    identity_string,
    index_by_operation_id,
)
from django_api_contract.utils import content_hash


def test_identity_string_is_method_and_path():
    assert identity_string("get", "/api/v1/customers/") == "GET /api/v1/customers/"


def test_identity_normalizes_duplicate_slashes():
    assert identity_string("get", "api//v1//customers/") == "GET /api/v1/customers/"


def test_identity_keeps_trailing_slash_distinct():
    assert identity_string("get", "/customers") != identity_string("get", "/customers/")


def test_versioned_paths_stay_distinct():
    assert identity_string("get", "/api/v1/customers/") != identity_string(
        "get", "/api/v2/customers/"
    )


def test_shape_removes_parameter_names():
    identity = OperationIdentity(method="get", path="/api/v1/customers/{public_id}/")
    assert identity.shape == "GET /api/v1/customers/{}/"


def test_identity_falls_back_to_default_folder():
    assert OperationIdentity(method="get", path="/x/").tag == "Default"


def test_tag_comes_from_the_first_openapi_tag():
    identity = OperationIdentity(method="get", path="/x/", operation={"tags": ["customers"]})
    assert identity.tag == "customers"


def test_duplicate_operation_ids_are_not_indexed():
    identities = [
        OperationIdentity("get", "/a/", {"operationId": "same"}),
        OperationIdentity("get", "/b/", {"operationId": "same"}),
        OperationIdentity("get", "/c/", {"operationId": "unique"}),
    ]
    index = index_by_operation_id(identities)
    assert set(index) == {"unique"}


def test_request_fingerprint_ignores_path_parameter_names():
    base = {
        "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}]
    }
    renamed = copy.deepcopy(base)
    renamed["parameters"][0]["name"] = "public_id"
    left = OperationIdentity("get", "/customers/{id}/", base)
    right = OperationIdentity("get", "/customers/{public_id}/", renamed)
    assert left.request_fingerprint == right.request_fingerprint


def test_request_fingerprint_keeps_query_parameter_names():
    left = OperationIdentity("get", "/x/", {"parameters": [{"name": "page", "in": "query"}]})
    right = OperationIdentity("get", "/x/", {"parameters": [{"name": "offset", "in": "query"}]})
    assert left.request_fingerprint != right.request_fingerprint


def test_previous_operation_scores_a_parameter_rename_highly():
    operation = {
        "parameters": [{"name": "public_id", "in": "path", "required": True}],
        "responses": {"200": {"description": "ok"}},
    }
    candidate = OperationIdentity("get", "/customers/{public_id}/", operation)
    previous = PreviousOperation(
        method="get",
        path="/customers/{id}/",
        request_fingerprint=content_hash(candidate.request_fingerprint),
        response_fingerprint=content_hash(candidate.response_fingerprint),
    )
    assert previous.score_against(candidate) >= 0.9


def test_previous_operation_does_not_match_a_different_resource():
    candidate = OperationIdentity(
        "get", "/orders/{id}/", {"responses": {"200": {"description": "ok"}}}
    )
    previous = PreviousOperation(
        method="get",
        path="/customers/{id}/",
        request_fingerprint="other",
        response_fingerprint="other",
    )
    assert previous.score_against(candidate) < 0.7


def test_previous_operation_never_matches_another_method():
    candidate = OperationIdentity("post", "/customers/{id}/", {})
    previous = PreviousOperation(method="get", path="/customers/{id}/")
    assert previous.score_against(candidate) == 0.0


def test_previous_operation_requires_method_and_path():
    assert PreviousOperation.from_metadata({"method": "GET"}) is None
    assert PreviousOperation.from_metadata({"path": "/x/"}) is None


def test_build_identities_covers_every_operation(schema):
    identities = build_identities(schema)
    assert identity_string("get", "/api/v1/customers/{public_id}/") in {
        item.identity for item in identities
    }
    assert len(identities) == sum(
        len([m for m in item if m in {"get", "post", "put", "patch", "delete"}])
        for item in schema["paths"].values()
    )
