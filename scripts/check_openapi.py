#!/usr/bin/env python3
"""Validate the public OpenAPI source, bundle, route inventory and boundary models."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, ClassVar

from build_openapi import DIST_PATH, SOURCE_ROOT, OpenAPIReferenceError, build_bundle

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PATHS = {
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("POST", "/v2/projects/{project_id}/runs"),
    ("GET", "/v2/runs/{run_id}"),
    ("GET", "/v2/runs/{run_id}/events"),
    ("POST", "/v2/runs/{run_id}/clarifications"),
    ("POST", "/v2/runs/{run_id}/requirements/confirm"),
    ("POST", "/v2/runs/{run_id}/reviews"),
    ("POST", "/v2/runs/{run_id}/feedback"),
    ("POST", "/v2/chat/completions"),
}
EXPECTED_RUN_STATUSES = {
    "running",
    "needs_clarification",
    "ready_for_confirmation",
    "rejected",
    "needs_review",
    "model_unavailable",
    "failed",
    "queued",
    "waiting_for_review",
    "complete",
    None,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_refs(value: Any):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for item in value.values():
            yield from _iter_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_refs(item)


def _check_source_references() -> list[str]:
    errors: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.json")):
        document = _load(path)
        for reference in _iter_refs(document):
            if not isinstance(reference, str):
                errors.append(f"{path}: $ref must be a string")
                continue
            target_name, _, fragment = reference.partition("#")
            if not target_name:
                continue
            target = (path.parent / target_name).resolve()
            if not target.exists():
                errors.append(f"{path}: missing $ref target {reference}")
                continue
            try:
                target_document = _load(target)
                _select_pointer(target_document, fragment, target)
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f"{path}: invalid $ref {reference}: {exc}")
    return errors


def _select_pointer(document: Any, fragment: str, source: Path) -> Any:
    if not fragment:
        return document
    if not fragment.startswith("/"):
        raise ValueError(f"unsupported fragment in {source}: #{fragment}")
    current = document
    for raw_token in fragment[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def _operation_inventory(bundle: dict[str, Any]) -> tuple[set[tuple[str, str]], list[str]]:
    inventory: set[tuple[str, str]] = set()
    operation_ids: set[str] = set()
    errors: list[str] = []
    paths = bundle.get("paths")
    if not isinstance(paths, dict):
        return set(), ["OpenAPI paths must be an object"]
    for path, item in paths.items():
        if path.startswith("/v1"):
            errors.append(f"project-owned OpenAPI path must not use /v1: {path}")
        if not isinstance(item, dict):
            errors.append(f"path item is not an object: {path}")
            continue
        path_parameters = item.get("parameters", [])
        path_parameter_names = {
            parameter.get("name")
            for parameter in path_parameters
            if isinstance(parameter, dict) and parameter.get("in") == "path"
        }
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                continue
            if not isinstance(operation, dict):
                errors.append(f"operation is not an object: {method.upper()} {path}")
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                errors.append(f"missing operationId: {method.upper()} {path}")
            elif operation_id in operation_ids:
                errors.append(f"duplicate operationId: {operation_id}")
            else:
                operation_ids.add(operation_id)
            for variable in _path_variables(path):
                if variable not in path_parameter_names and not any(
                    parameter.get("name") == variable
                    for parameter in operation.get("parameters", [])
                    if isinstance(parameter, dict) and parameter.get("in") == "path"
                ):
                    errors.append(f"missing path parameter {variable!r}: {method.upper()} {path}")
            inventory.add((method.upper(), path))
    return inventory, errors


def _path_variables(path: str) -> list[str]:
    variables: list[str] = []
    remainder = path
    while "{" in remainder and "}" in remainder:
        start = remainder.index("{")
        end = remainder.index("}", start)
        variables.append(remainder[start + 1 : end])
        remainder = remainder[end + 1 :]
    return variables


def _fastapi_inventory() -> set[tuple[str, str]]:
    from ai_presales_copilot.api_v2 import LocalTokenAuth, create_fastapi_app

    class _Model:
        model = "contract-check"

        def health(self) -> dict[str, int]:
            return {"status": 200}

    class _Workflow:
        model = _Model()

    class _Store:
        def load_by_run_id(self, run_id: str):
            return None

    class _Knowledge:
        documents: ClassVar[list[dict[str, Any]]] = []

    app = create_fastapi_app(
        _Workflow(),
        _Store(),
        _Knowledge(),
        auth=LocalTokenAuth(allow_dev=True),
    )
    inventory: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}:
            continue
        inventory.update((method.upper(), path) for method in methods if method.upper() in {"GET", "POST"})
    return inventory


def _check_pydantic_fields(bundle: dict[str, Any]) -> list[str]:
    from ai_presales_copilot.api_v2 import V2FeedbackRequest, V2ReviewRequest
    from ai_presales_copilot.schemas import (
        ClarificationRequestV2,
        CustomerInputV2,
        RequirementConfirmRequestV2,
        RunInputRequestV2,
    )

    model_map = {
        "CustomerInput": CustomerInputV2,
        "RunInputRequest": RunInputRequestV2,
        "ClarificationRequest": ClarificationRequestV2,
        "RequirementConfirmRequest": RequirementConfirmRequestV2,
        "ReviewRequest": V2ReviewRequest,
        "FeedbackRequest": V2FeedbackRequest,
    }
    errors: list[str] = []
    schemas = bundle["components"]["schemas"]
    for schema_name, model in model_map.items():
        runtime_schema = model.model_json_schema()
        contract = schemas[schema_name]
        runtime_properties = set(runtime_schema.get("properties", {}))
        contract_properties = set(contract.get("properties", {}))
        if runtime_properties != contract_properties:
            errors.append(
                f"Pydantic/OpenAPI fields differ for {schema_name}: "
                f"runtime={sorted(runtime_properties)}, contract={sorted(contract_properties)}"
            )
        if set(runtime_schema.get("required", [])) != set(contract.get("required", [])):
            errors.append(
                f"Pydantic/OpenAPI required fields differ for {schema_name}: "
                f"runtime={sorted(runtime_schema.get('required', []))}, "
                f"contract={sorted(contract.get('required', []))}"
            )
        runtime_enums = _enum_values(runtime_schema)
        contract_enums = _enum_values(contract)
        if runtime_enums != contract_enums:
            errors.append(
                f"Pydantic/OpenAPI enum values differ for {schema_name}: "
                f"runtime={sorted(runtime_enums)}, contract={sorted(contract_enums)}"
            )
    return errors


def _check_run_statuses(bundle: dict[str, Any]) -> list[str]:
    statuses = bundle["components"]["schemas"]["RunState"]["properties"]["status"].get("enum", [])
    if set(statuses) != EXPECTED_RUN_STATUSES:
        return [
            (
                "RunState status values differ from the current runtime state machine: "
                f"contract={sorted(status for status in statuses if status is not None)}, "
                f"expected={sorted(status for status in EXPECTED_RUN_STATUSES if status is not None)}"
            )
        ]
    return []


def _enum_values(value: Any) -> set[str]:
    """Collect non-null enum/const values while ignoring Pydantic metadata."""

    values: set[str] = set()
    if isinstance(value, dict):
        enum = value.get("enum")
        if isinstance(enum, list):
            values.update(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in enum if item is not None)
        if "const" in value and value["const"] is not None:
            values.add(json.dumps(value["const"], ensure_ascii=False, sort_keys=True))
        for item in value.values():
            values.update(_enum_values(item))
    elif isinstance(value, list):
        for item in value:
            values.update(_enum_values(item))
    return values


def main() -> int:
    errors: list[str] = []
    errors.extend(_check_source_references())
    try:
        bundle = build_bundle()
    except OpenAPIReferenceError as exc:
        print(f"openapi bundle build failed: {exc}", file=sys.stderr)
        return 1
    if not DIST_PATH.exists():
        errors.append(f"generated bundle is missing: {DIST_PATH}")
    else:
        dist = _load(DIST_PATH)
        if dist != bundle:
            errors.append("generated bundle differs from the resolved source fragments")
    if bundle.get("openapi") != "3.1.0":
        errors.append("OpenAPI version must be 3.1.0")
    if not isinstance(bundle.get("info"), dict) or not bundle["info"].get("version"):
        errors.append("OpenAPI info.version is required")
    contract_inventory, inventory_errors = _operation_inventory(bundle)
    errors.extend(inventory_errors)
    if contract_inventory != EXPECTED_PATHS:
        errors.append(
            "OpenAPI operation inventory differs from the expected v2 route set: "
            f"missing={sorted(EXPECTED_PATHS - contract_inventory)}, "
            f"extra={sorted(contract_inventory - EXPECTED_PATHS)}"
        )
    try:
        actual_inventory = _fastapi_inventory()
    except Exception as exc:  # pragma: no cover - environment dependency failure  # noqa: BLE001
        errors.append(f"could not inspect FastAPI routes: {type(exc).__name__}: {exc}")
    else:
        if actual_inventory != EXPECTED_PATHS:
            errors.append(
                "FastAPI route inventory differs from the expected v2 route set: "
                f"missing={sorted(EXPECTED_PATHS - actual_inventory)}, "
                f"extra={sorted(actual_inventory - EXPECTED_PATHS)}"
            )
    try:
        errors.extend(_check_pydantic_fields(bundle))
        errors.extend(_check_run_statuses(bundle))
    except Exception as exc:  # pragma: no cover - environment dependency failure  # noqa: BLE001
        errors.append(f"could not compare Pydantic fields: {type(exc).__name__}: {exc}")

    try:
        from openapi_spec_validator import validate_spec
    except ImportError:  # pragma: no cover - enforced by dev dependency
        errors.append("openapi-spec-validator is required for OpenAPI checks")
    else:
        try:
            validate_spec(bundle)
        except Exception as exc:  # pragma: no cover - validator implementation detail  # noqa: BLE001
            errors.append(f"OpenAPI structural validation failed: {exc}")

    if errors:
        print("OpenAPI check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"OpenAPI check passed: {len(contract_inventory)} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
