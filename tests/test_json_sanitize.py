from __future__ import annotations

import json

import pytest

from app.json_sanitize import escape_control_chars_inside_json_strings


@pytest.mark.parametrize(
    "raw,expected_inner",
    [
        ('{"a":"x\ny"}', {"a": "x\ny"}),
        ('{"a":"x\ty"}', {"a": "x\ty"}),
    ],
)
def test_sanitize_makes_invalid_json_parseable(raw: str, expected_inner: dict) -> None:
    fixed = escape_control_chars_inside_json_strings(raw)
    assert json.loads(fixed) == expected_inner


def test_sanitize_idempotent_on_valid_json() -> None:
    valid = '{"a": "hello\\nworld", "b": 1}'
    assert escape_control_chars_inside_json_strings(valid) == valid


def test_sanitize_preserves_whitespace_outside_strings() -> None:
    raw = '{\n "a": "b\nc"\n}'
    fixed = escape_control_chars_inside_json_strings(raw)
    assert json.loads(fixed) == {"a": "b\nc"}
    assert "\n" in fixed  # newlines between keys remain
