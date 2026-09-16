# django-api-contract

Keep your OpenAPI schema and your Postman collection in sync with your Django
REST Framework API, without maintaining either by hand.

The API code is the source of truth. The package reads your DRF routes and
serializers, generates an OpenAPI document from them, and folds that document
into the Postman collection you already have. Scripts, examples, custom headers
and manual requests you added in Postman survive the update.

```
Django / DRF  ->  OpenAPI schema  ->  Postman synchronizer  ->  your collection
```

## Install

```bash
pip install django-api-contract
```

Add it to `INSTALLED_APPS`, alongside `rest_framework` and `drf_spectacular`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "drf_spectacular",
    "django_api_contract",
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
```

Requires Python 3.9+, Django 4.2+, DRF 3.14+.

## Commands

```bash
python manage.py api_contract generate   # build both files from the current API
python manage.py api_contract sync       # same, merging into the existing collection
python manage.py api_contract check      # exit non-zero if the committed files are stale
python manage.py api_contract diff       # show what changed since the committed schema
```

`generate` and `sync` do the same work. They are separate names because `sync`
says out loud what both of them do: the existing Postman collection is merged
into, never replaced.

Useful flags, on any action:

```bash
--dry-run                 report what would change, write nothing
--allow-breaking-change   do not fail when a breaking change is detected
--openapi-output PATH     override the OpenAPI output path for this run
--postman-output PATH     override the Postman output path for this run
```

### Example output

```
$ python manage.py api_contract sync

✓ OpenAPI schema generated
✓ OpenAPI schema validated
✓ Postman collection synchronized

API Contract Synchronization

OpenAPI:
  Added:    1
  Changed:  2
  Removed:  0

Postman:
  Created:    1
  Updated:    2
  Unchanged:  12
  Preserved:  3
  Archived:   0
  Removed:    0

Renamed:
  GET /api/v1/customers/{id}/ -> GET /api/v1/customers/{public_id}/

Manual edits kept:
  POST /api/v1/customers/: body, scripts

Breaking changes:
  0
```

## Configuration

Every setting has a default. Add only what you want to change:

```python
API_CONTRACT = {
    "OPENAPI_OUTPUT": "api-contract/openapi.json",
    "POSTMAN_OUTPUT": "api-contract/postman_collection.json",
    "PRESERVE_MANUAL_REQUESTS": True,
    "REMOVE_DELETED_ENDPOINTS": False,
    "FAIL_ON_BREAKING_CHANGE": True,
}
```

| Setting | Default | What it does |
|---|---|---|
| `OPENAPI_OUTPUT` | `api-contract/openapi.json` | Where the schema is written, relative to `BASE_DIR` |
| `POSTMAN_OUTPUT` | `api-contract/postman_collection.json` | Where the collection is written |
| `POSTMAN_COLLECTION_ID` | derived from the name | Fixed `_postman_id` for the collection |
| `POSTMAN_COLLECTION_NAME` | the OpenAPI title | Collection name |
| `POSTMAN_COLLECTION_DESCRIPTION` | the OpenAPI description | Collection description |
| `PRESERVE_MANUAL_REQUESTS` | `True` | Keep requests that do not map to any endpoint |
| `REMOVE_DELETED_ENDPOINTS` | `False` | Delete generated requests whose endpoint is gone |
| `ARCHIVE_DELETED_ENDPOINTS` | `True` | Rename those requests instead of deleting them |
| `PRESERVE_RESPONSE_EXAMPLES` | `True` | Keep response examples you edited by hand |
| `DETECT_RENAMES` | `True` | Match a renamed endpoint to its existing request |
| `RENAME_SIMILARITY_THRESHOLD` | `0.7` | Below this score, a rename is not even reported |
| `FAIL_ON_BREAKING_CHANGE` | `True` | Fail `generate`, `sync` and `diff` on a breaking change |
| `URLCONF` | project default | Generate from a different URLconf |
| `SERVERS` | from drf-spectacular | `servers` block, and the default `base_url` value |
| `SCHEMA_GENERATOR_CLASS` | `drf_spectacular.generators.SchemaGenerator` | Swap the generator |
| `BASE_URL_VARIABLE` | `base_url` | Name of the Postman variable holding the host |
| `INDENT` | `2` | JSON indentation in both output files |

## What is generated and what is preserved

The package marks everything it creates with an `x-api-contract` block:

```json
"x-api-contract": {
    "managed": true,
    "operation_id": "customers-retrieve",
    "identity": "GET /api/v1/customers/{public_id}"
}
```

That marker is how the synchronizer tells its own output from your edits.

| Generated on every run | Preserved from your collection |
|---|---|
| HTTP method and URL | Request name, once you rename it |
| Path, query and header parameter names | Parameter values and enabled/disabled toggles |
| Request body structure and examples | A request body you edited by hand |
| Response examples per status code | Response examples you edited, and ones you added |
| Folder grouping from OpenAPI tags | Folder and request ids, descriptions, variables |
| Collection auth from the security schemes | Per-request auth you set yourself |
| | Pre-request and test scripts |
| | Requests that match no endpoint |

Generated examples use placeholder values (`user@example.com`, `2024-01-01`).
Credentials are always Postman variables such as `{{access_token}}` and
`{{api_key}}`, so no secret is written into a generated file.

## Deleted and renamed endpoints

When an endpoint disappears from your API, the package does not delete the
request. It renames it to `GET /old/path/ [removed from API]` and reports it,
so you notice before you lose the request. Set `REMOVE_DELETED_ENDPOINTS` to
`True` if you want the cleanup done for you. Even then, only requests the
package generated are removed. Requests you wrote yourself are never touched.

When a path parameter is renamed, for example `{id}` to `{public_id}`, the
package matches the new endpoint to the existing request and updates it in
place, keeping your scripts. If the match is not confident enough, it reports a
possible rename and leaves both requests alone for you to review.

See [docs/architecture.md](docs/architecture.md) for how identity and rename
detection actually work.

## Breaking change detection

`diff` classifies each change. Removing an endpoint, adding a required field,
making an optional field required, changing a field type, dropping an enum
value, removing a response field and changing the authentication requirement
are all reported as breaking. Adding an endpoint, an optional field or an
optional query parameter is not.

Some changes cannot be classified with confidence, and those are reported
separately as potential breaking changes rather than guessed at.

## Deterministic output

Running `generate` twice against an unchanged API produces identical files,
byte for byte. Ids come from a hash of the endpoint rather than a fresh UUID,
and structural lists are sorted. That keeps the artifacts reviewable in a pull
request and keeps merge conflicts to the lines that actually changed.

The package does not resolve git conflicts for you. If two developers change
the API on separate branches, resolve the conflict in the source code, then run
`sync` again to regenerate the artifacts.

## Continuous integration

`check` regenerates the contract in memory and compares it with the committed
files. It exits `0` when they match and non-zero when they do not.

```yaml
- name: Check API contract
  run: python manage.py api_contract check
```

A developer who changes the API and forgets to run `sync` gets a failing build
with the list of endpoints that moved.

## Safety

Nothing is written until the schema has been generated, validated and merged
successfully. Both files are written through a temporary file in the same
directory and then moved into place, so a crash mid-write cannot leave a
half-written contract. If generation fails, the files on disk are exactly as
they were.

## Example project

[`example/`](example/) is a small Django project with a catalog API, the
`API_CONTRACT` settings block, and both generated files committed so you can
see the output without running anything.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check django_api_contract tests
mypy django_api_contract
```

Releases are published from GitHub Actions through PyPI trusted publishing.
See [docs/releasing.md](docs/releasing.md).

## License

MIT. See [LICENSE](LICENSE).
