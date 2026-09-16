from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from django_api_contract.conf import contract_settings
from django_api_contract.diff import render_check_failure, render_diff, render_sync_summary
from django_api_contract.exceptions import ApiContractError, BreakingChangeError
from django_api_contract.schema.validator import describe_problems
from django_api_contract.service import (
    build_contract,
    check_contract,
    enforce_compatibility,
    write_contract,
)

ACTIONS = ("generate", "sync", "check", "diff")


class Command(BaseCommand):
    help = (
        "Keep the OpenAPI schema and Postman collection in sync with the API.\n\n"
        "  generate  build both artifacts from the current API\n"
        "  sync      same as generate, merging into the existing collection\n"
        "  check     exit non-zero when the committed artifacts are outdated\n"
        "  diff      show what changed since the committed schema"
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("action", choices=ACTIONS, help="operation to run")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="report what would change without writing files",
        )
        parser.add_argument(
            "--allow-breaking-change",
            action="store_true",
            help="do not fail when a breaking change is detected",
        )
        parser.add_argument(
            "--openapi-output", help="override the OpenAPI output path for this run"
        )
        parser.add_argument(
            "--postman-output", help="override the Postman output path for this run"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        settings = contract_settings.with_overrides(
            OPENAPI_OUTPUT=options.get("openapi_output"),
            POSTMAN_OUTPUT=options.get("postman_output"),
            FAIL_ON_BREAKING_CHANGE=False if options["allow_breaking_change"] else None,
        )
        action = options["action"]

        try:
            handler = getattr(self, f"_handle_{action}")
            handler(settings, options)
        except BreakingChangeError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            for change in exc.changes:
                self.stderr.write(f"  {change.endpoint}: {change.describe() or 'removed'}")
            raise CommandError(
                "Breaking changes detected. Re-run with --allow-breaking-change to continue."
            ) from exc
        except ApiContractError as exc:
            problems = getattr(exc, "problems", None)
            message = str(exc)
            if problems:
                message = f"{message}\n{describe_problems(problems)}"
            raise CommandError(message) from exc

    def _handle_generate(self, settings: Any, options: dict) -> None:
        self._run_write(settings, options, header="Generating API contract...")

    def _handle_sync(self, settings: Any, options: dict) -> None:
        self._run_write(settings, options, header="Synchronizing API contract...")

    def _run_write(self, settings: Any, options: dict, header: str) -> None:
        dry_run = options["dry_run"]
        self.stdout.write(header)
        self.stdout.write("")

        build = build_contract(settings)
        self.stdout.write(self.style.SUCCESS("✓ OpenAPI schema generated"))
        self.stdout.write(self.style.SUCCESS("✓ OpenAPI schema validated"))

        enforce_compatibility(build, settings)

        if dry_run:
            self.stdout.write(self.style.WARNING("✓ Postman collection synchronized (dry run)"))
        else:
            write_contract(build, settings)
            self.stdout.write(self.style.SUCCESS("✓ Postman collection synchronized"))

        self.stdout.write("")
        self.stdout.write(
            render_sync_summary(
                build.diff,
                build.sync,
                dry_run=dry_run,
                openapi_path=None if dry_run else settings.openapi_path,
                postman_path=None if dry_run else settings.postman_path,
            )
        )

    def _handle_check(self, settings: Any, options: dict) -> None:
        result = check_contract(settings)
        if result.up_to_date:
            self.stdout.write(self.style.SUCCESS("✓ OpenAPI is up to date"))
            self.stdout.write(self.style.SUCCESS("✓ Postman collection is up to date"))
            self.stdout.write("")
            self.stdout.write("API contract is synchronized.")
            return

        self.stderr.write(self.style.ERROR("✗ API contract is out of date."))
        self.stderr.write("")
        self.stderr.write(render_check_failure(result.build.diff, result.stale))
        raise CommandError("API contract is out of date.")

    def _handle_diff(self, settings: Any, options: dict) -> None:
        build = build_contract(settings)
        if build.previous_schema is None:
            self.stdout.write(
                f"No committed schema at {settings.openapi_path}; nothing to compare."
            )
            return
        self.stdout.write(render_diff(build.diff))
        if not options["allow_breaking_change"]:
            enforce_compatibility(build, settings)
