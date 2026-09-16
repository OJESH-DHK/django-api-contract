# Example project

A small Django + DRF project that shows `django-api-contract` in use.

## Run it

```bash
pip install -e ..
pip install django djangorestframework drf-spectacular

python manage.py migrate
python manage.py runserver
```

## Generate the contract

```bash
python manage.py api_contract generate
```

This writes `api-contract/openapi.json` and `api-contract/postman_collection.json`.
Both files are committed so you can see what the output looks like.

## Try a change

Add a field to `catalog/serializers.py`, then:

```bash
python manage.py api_contract diff
python manage.py api_contract sync
```

The diff reports the change at endpoint level, and the sync folds it into the
existing Postman collection instead of replacing it. Import
`api-contract/postman_collection.json` into Postman, add a test script to a
request, re-export it over the same file and run `sync` again: the script is
still there.

## Configuration

See `config/settings.py` for the `API_CONTRACT` block.
