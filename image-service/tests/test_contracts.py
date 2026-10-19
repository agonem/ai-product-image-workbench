import json
from pathlib import Path

import pytest

from image_service.contracts import validate_contract

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_contract(case):
    assert (not validate_contract(case["contract"], case["payload"])) == case["valid"]


def test_schemas_and_fixture_names():
    from jsonschema import Draft202012Validator

    from image_service.contracts import SCHEMAS

    for schema in SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
    assert len({case["name"] for case in CASES}) == len(CASES)


def test_unknown_contract_and_safe_errors():
    with pytest.raises(ValueError, match="Unknown contract"):
        validate_contract("https://example.invalid/unregistered", {})
    errors = validate_contract("generation-v4-create", {"api_key": "dummy-sensitive-value"})
    assert errors
    assert "dummy-sensitive-value" not in str(errors)
    assert validate_contract("generation-v4-create", {"x": float("inf")})
