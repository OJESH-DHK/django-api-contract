# Architecture

## Pipeline

```
Django URLconf + DRF serializers
        |
        v  drf-spectacular
OpenAPI document
        |
        +--> normalize --> validate --> openapi.json
        |
        v
Postman synchronizer  <--  existing postman_collection.json
        |
        v
updated postman_collection.json
```

OpenAPI sits in the middle on purpose. Postman is an output, never an input to
the API description, so a change made in Postman can never silently redefine
what the API is.

## Modules

| Module | Responsibility |
|---|---|
| `conf.py` | Reads `settings.API_CONTRACT`, applies defaults, resolves output paths |
| `schema/generator.py` | Runs the schema generator, converts the result to plain JSON |
| `schema/normalizer.py` | Sorts and reorders the document so output is byte-stable |
| `schema/validator.py` | Structural checks: refs resolve, path params declared, ids unique |
| `postman/identity.py` | Endpoint identity and rename scoring |
| `postman/examples.py` | Deterministic example values for schemas |
| `postman/generator.py` | Renders a complete Postman v2.1 collection |
| `postman/merger.py` | Folds one generated request into an existing one |
| `postman/synchronizer.py` | Matches, merges and reassembles the whole collection |
| `diff/comparator.py` | Compares two OpenAPI documents field by field |
| `diff/models.py` | `Change`, `Severity`, `ContractDiff` |
| `diff/reporter.py` | Renders the diff, the sync summary and the check failure |
| `service.py` | Orchestration: build everything, then write everything |
| `management/commands/api_contract.py` | Argument parsing and terminal output only |

## Endpoint identity

Every operation gets an identity string of the form:

```
GET /api/v1/customers/{public_id}/
```

That is the HTTP method plus the normalized path. Normalization collapses
repeated slashes and enforces a leading slash. It deliberately keeps the
trailing slash, because DRF routes `/customers` and `/customers/` separately,
and it keeps the version prefix, so `/api/v1/customers/` and
`/api/v2/customers/` never collide.

Identity alone is not enough, because a path can change while the operation
stays the same. Each generated request therefore records three things in its
`x-api-contract` metadata: the identity, the `operationId`, and hashes of the
request and response contracts.

Matching an existing request to a current operation runs in this order:

1. **Identity.** Same method and path. This survives an `operationId` rename.
2. **`operationId`.** This survives a path change, which is the common case when
   a lookup field is renamed. Duplicate ids are skipped rather than guessed at,
   since an id shared by two operations identifies neither.
3. **Similarity scoring.** Whatever is left over is scored against the
   unclaimed operations.

## Rename detection

Scoring compares a previously generated request against a candidate operation.
Different HTTP methods score zero immediately. Otherwise:

| Signal | Weight |
|---|---|
| Path shape, that is the path with parameter names blanked out | 0.40 |
| Request contract hash, parameters plus request body | 0.25 |
| Response contract hash | 0.15 |
| Raw path string similarity | 0.20 |

The request contract hash ignores the *names* of path parameters and replaces
them with their position. Renaming `{id}` to `{public_id}` does not change what
the endpoint accepts, so it should not count against the match. Query and
header parameter names are part of the contract and are kept.

A score of 0.9 or above applies the rename and updates the existing request in
place. A score between `RENAME_SIMILARITY_THRESHOLD` and 0.9 is reported as a
possible rename and nothing is changed, because a wrong automatic match would
move someone's test scripts onto the wrong endpoint.

A renamed lookup field with an unchanged serializer scores about 0.99. Two
different resources that happen to share a path shape score around 0.5.

## Synchronization

`synchronize_collection` never rebuilds the file from nothing. It:

1. Generates the full collection from the current schema.
2. Flattens the existing collection into a list of requests, remembering which
   folder each one came from.
3. Splits those requests into managed (the package generated them) and manual
   (it did not).
4. Matches managed requests to generated ones using the order above.
5. Merges each pair, letting the schema own the structure and the existing file
   own the human edits.
6. Reassembles the collection: generated folders sorted by name, requests
   inside them sorted by path and method, then manual requests appended in the
   folder they were in, then manual folders.

Step 6 is what makes repeated runs stable. Ten consecutive syncs against an
unchanged API produce the same bytes and never duplicate a request, a folder, a
header or a parameter.

## Telling a manual edit from a stale value

When a request is generated, the metadata records a hash of each field the
package owns, and the list of header, query, path and form keys it created:

```json
"x-api-contract": {
    "managed": true,
    "identity": "POST /api/v1/customers/",
    "generated": { "name": "0f2a...", "description": "9c41...", "body": "77bd..." },
    "owned": { "header": ["Accept", "Content-Type"], "query": ["page"] }
}
```

On the next run the package hashes what is actually in the file. A match means
nobody touched it, so the fresh value is written. A mismatch means someone
edited it by hand, so their version is kept and reported under "Manual edits
kept". The recorded hash stays the hash of the *generated* value, so the edit
keeps being recognized on every later run.

The `owned` lists solve the other half of the problem. A query parameter in the
file that is not in the newly generated request is either something you added
or something the API dropped. If the key appears in `owned`, the package put it
there and the API no longer produces it, so it is removed. If it does not, you
added it, and it stays.

## Deleted endpoints

A managed request with no matching operation is not deleted by default. It is
renamed to `<identity> [removed from API]`, marked `archived` in its metadata,
left in its folder, and listed in the summary under "Removed from API".

Setting `REMOVE_DELETED_ENDPOINTS` to `True` deletes it instead. That only ever
applies to requests carrying `"managed": true`. A request the package did not
create is never deleted by either setting, because the package has no way to
know what it was for.

## Breaking changes

`compare_schemas` walks both documents endpoint by endpoint. For each endpoint
present in both, it flattens the request body and the first successful response
into `{dotted.field.name: descriptor}` maps, resolving `$ref` and `allOf` and
descending into arrays as `field[]`. Then it compares parameters, request
fields, response fields and the security requirement.

Breaking: an endpoint or method removed, a required request field added, an
optional field made required, any field type change, an enum value dropped, a
response field removed, a required parameter added, a path parameter removed,
a response field that is no longer nullable, and a change in authentication.

Not breaking: a new endpoint, a new optional request field, a new optional
query parameter, a new response field, a required field made optional, and a
new enum value accepted in a request.

Reported as potential rather than certain: a success status code change, a new
enum value appearing in a response, and a required request field being removed.

## How data loss is avoided

Four separate mechanisms, in order of how early they stop a problem:

1. **Nothing is written until everything succeeds.** `build_contract` generates,
   validates and merges entirely in memory. A failure anywhere in that chain
   raises before `write_contract` is reached, and the committed files are
   untouched.
2. **Writes are atomic.** Each file is written to a temporary file in the
   destination directory, flushed, fsynced, then moved into place with
   `os.replace`. A crash leaves either the old file or the new one, never half
   of either.
3. **Deletion is opt in.** Endpoints that disappear are archived, not removed,
   and manual requests are never removed at all.
4. **Human edits outrank generated ones.** Anything the package cannot prove it
   wrote is left alone, and anything it can prove was changed afterwards is
   kept and reported.
