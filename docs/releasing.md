# Releasing

Publishing runs on GitHub Actions through PyPI trusted publishing, so no API
token is stored anywhere. PyPI verifies a short-lived OIDC identity from the
workflow run instead.

## One-time setup

Do this once, before the first release.

### 1. Create the pending publisher on PyPI

Go to <https://pypi.org/manage/account/publishing/> and add a pending publisher:

| Field | Value |
|---|---|
| PyPI project name | `django-api-contract` |
| Owner | `OJESH-DHK` |
| Repository name | `django-api-contract` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Repeat the same at <https://test.pypi.org/manage/account/publishing/> with the
environment name `testpypi` if you want to rehearse a release first.

### 2. Create the GitHub environments

In the repository settings, under Environments, create `pypi` and `testpypi`.
Adding yourself as a required reviewer on `pypi` means a release waits for your
approval before it uploads, which is worth doing.

## Cutting a release

1. Update `version` in `pyproject.toml`.
2. Move the entries under `## [Unreleased]` in `CHANGELOG.md` into a new
   version heading, and add the link at the bottom of the file.
3. Commit and push both.
4. Tag and push the tag:

   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

5. Publish a GitHub release for that tag. The workflow builds the sdist and
   wheel, checks that the tag matches the version in `pyproject.toml`, runs
   `twine check`, and uploads to PyPI.

A mismatch between the tag and `pyproject.toml` fails the build before anything
is uploaded, so a wrong tag costs you a re-tag rather than a yanked release.

## Rehearsing on TestPyPI

Run the Release workflow manually from the Actions tab and pick `testpypi`.
Then check the result installs:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            django-api-contract
```

## Versioning

The project follows semantic versioning. Anything that changes the generated
OpenAPI or Postman output in a way that produces a different file for an
unchanged API is a breaking change for users, because it shows up as a diff in
their committed artifacts. Call that out in the changelog.
