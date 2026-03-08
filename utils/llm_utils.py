"""
Shared LLM output utilities.

Used by every agent that calls a language model, so JSON parsing
and fence-stripping logic live in one place.
"""

from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict:
    """
    Extract a JSON object from raw LLM output.

    Strips markdown fences (```json ... ``` or ``` ... ```) if present,
    then parses and validates the result is a JSON object (not an array
    or scalar).

    Args:
        text: Raw string returned by the language model.

    Returns:
        Parsed dict.

    Raises:
        ValueError: On JSON parse failure or non-object result.
    """
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error: {exc}\nRaw text: {text[:500]}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}.")

    return data
