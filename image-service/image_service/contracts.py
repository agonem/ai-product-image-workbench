"""Offline Draft 2020-12 protocol validation. No business database access."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2] / "contracts"
SCHEMAS = {
    path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8"))
    for path in ROOT.glob("*.schema.json")
}
SCHEMAS["task-request"] = SCHEMAS.pop("task")
REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values()
)
VALIDATORS = {
    name: Draft202012Validator(
        schema, registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    for name, schema in SCHEMAS.items()
}


def validate_contract(name: str, value: object) -> list[str]:
    """Return schema paths and keywords, not potentially sensitive input values."""
    if name not in VALIDATORS or name == "common":
        raise ValueError("Unknown contract")
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        return ["$: JSON"]
    return [
        f"/{'/'.join(map(str, error.absolute_schema_path))}: {error.validator}"
        for error in VALIDATORS[name].iter_errors(value)
    ]
