"""Unit tests for utils/llm_utils.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.llm_utils import extract_json


class TestExtractJson:
    def test_plain_json_object(self):
        assert extract_json('{"key": "value"}') == {"key": "value"}

    def test_strips_json_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert extract_json(text) == {"key": "value"}

    def test_strips_plain_fence(self):
        text = '```\n{"key": "value"}\n```'
        assert extract_json(text) == {"key": "value"}

    def test_nested_object(self):
        text = '{"a": {"b": 1}}'
        assert extract_json(text) == {"a": {"b": 1}}

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="JSON parse error"):
            extract_json("{not valid json}")

    def test_json_array_raises_value_error(self):
        with pytest.raises(ValueError, match="Expected a JSON object"):
            extract_json("[1, 2, 3]")

    def test_json_scalar_raises_value_error(self):
        with pytest.raises(ValueError, match="Expected a JSON object"):
            extract_json('"just a string"')

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            extract_json("")

    def test_raw_text_truncated_in_error(self):
        """Error message should not dump enormous payloads."""
        long_garbage = "x" * 2000
        with pytest.raises(ValueError) as exc_info:
            extract_json(long_garbage)
        assert len(str(exc_info.value)) < 1500
