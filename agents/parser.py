"""
Hypothesis Parser Agent (Stage 1)

Input:  free-text biological hypothesis
Output: ParsedHypothesis — structured JSON with target_gene, phenotype,
        system_context, assumptions_made, edit_type, cell_line
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

# TODO: remove sys.path hack after proper packaging (pyproject.toml)
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import MODEL_FAST, MAX_TOKENS, TEMPERATURE
from models.schemas import ParsedHypothesis
from utils.llm_utils import extract_json

# ── Constants ──────────────────────────────────────────────────────────────

MAX_RETRIES = 3

# ── Prompts ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a CRISPR experimental design assistant.
Your job is to parse a free-text biological hypothesis into structured JSON.

Return ONLY valid JSON — no markdown, no explanation, no code fences.

Schema:
{
  "target_gene":      "<HGNC gene symbol, uppercase, e.g. TP53>",
  "phenotype":        "<expected biological outcome after the edit>",
  "system_context":   "<disease, pathway, or biological system mentioned>",
  "assumptions_made": ["<list of assumptions you inferred from ambiguous input>"],
  "edit_type":        "<one of: knockout, knockin, activation, repression>",
  "cell_line":        "<one of: HEK293, HeLa, Jurkat, primary, other>"
}

Rules:
- target_gene must be a valid HGNC symbol. If ambiguous, pick the most likely one and add an assumption.
- If cell_line is not mentioned, default to HEK293 and note it in assumptions_made.
- If edit_type is not mentioned, default to knockout and note it in assumptions_made.
- assumptions_made must be a list (can be empty if nothing was assumed).
- Never return null for required fields — infer reasonable defaults."""

USER_TEMPLATE = "Hypothesis: {hypothesis}"
RETRY_SUFFIX = "\n\nPrevious attempt failed with error: {error}\nReturn corrected JSON only."


# ── Parser ─────────────────────────────────────────────────────────────────

def parse_hypothesis(hypothesis: str) -> ParsedHypothesis:
    """
    Call Claude to extract structured fields from a free-text hypothesis.

    Retries up to MAX_RETRIES times on JSON parse or schema validation
    failures, forwarding the prior error to the model for self-correction.

    Args:
        hypothesis: Raw user hypothesis string.

    Returns:
        ParsedHypothesis — validated Pydantic model.

    Raises:
        ValueError:         If all retries exhaust without valid output.
        EnvironmentError:   If ANTHROPIC_API_KEY is not set.
        anthropic.APIError: On unrecoverable API failures.
    """
    if not hypothesis or not hypothesis.strip():
        raise ValueError("Hypothesis must be a non-empty string.")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        user_content = USER_TEMPLATE.format(hypothesis=hypothesis)
        if last_error:
            user_content += RETRY_SUFFIX.format(error=last_error)

        try:
            message = client.messages.create(
                model=MODEL_FAST,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw_text = message.content[0].text.strip()
            parsed_data = extract_json(raw_text)
            parsed_data["raw_hypothesis"] = hypothesis
            return ParsedHypothesis(**parsed_data)

        except (ValueError, ValidationError) as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise ValueError(
                    f"Hypothesis parsing failed after {MAX_RETRIES} attempts. "
                    f"Last error: {last_error}"
                ) from exc

    raise RuntimeError("Unexpected exit from retry loop.")  # pragma: no cover


# ── CLI / Test Harness ─────────────────────────────────────────────────────

TEST_CASES = [
    {
        "label": "Standard knockout",
        "hypothesis": "Knocking out TP53 in cancer cells will lead to uncontrolled proliferation.",
    },
    {
        "label": "Gene symbol inferred from description",
        "hypothesis": "I want to study what happens when I disable the BRCA1 tumor suppressor in breast cancer cells.",
    },
    {
        "label": "Activation, non-default cell line",
        "hypothesis": "Activating KRAS signaling in Jurkat T-cells should mimic oncogenic transformation.",
    },
    {
        "label": "Ambiguous / minimal input",
        "hypothesis": "What if we knocked out MYC?",
    },
]


def _run_one(idx: int, case: dict) -> dict:
    """Run a single test case. Returns a result dict (thread-safe)."""
    t0 = time.perf_counter()
    try:
        result = parse_hypothesis(case["hypothesis"])
        return {
            "idx": idx,
            "label": case["label"],
            "hypothesis": case["hypothesis"],
            "elapsed": time.perf_counter() - t0,
            "ok": True,
            "result": result,
        }
    except Exception as exc:
        return {
            "idx": idx,
            "label": case["label"],
            "hypothesis": case["hypothesis"],
            "elapsed": time.perf_counter() - t0,
            "ok": False,
            "error": str(exc),
        }


def _run_tests() -> None:
    print("=" * 60)
    print("AutoLab-CRISPR  |  Parser Agent  |  Test Harness (parallel)")
    print(f"Running {len(TEST_CASES)} cases in parallel — est. ~2–4s total")
    print("=" * 60)

    suite_start = time.perf_counter()
    results: list[dict | None] = [None] * len(TEST_CASES)

    with ThreadPoolExecutor(max_workers=len(TEST_CASES)) as pool:
        futures = {pool.submit(_run_one, i, case): i for i, case in enumerate(TEST_CASES)}
        for future in as_completed(futures):
            res = future.result()
            results[res["idx"]] = res

    passed = failed = 0
    for i, res in enumerate(results, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {res['label']}")
        print(f"  Input: {res['hypothesis']}")
        if res["ok"]:
            r = res["result"]
            print(f"  target_gene    : {r.target_gene}")
            print(f"  phenotype      : {r.phenotype}")
            print(f"  system_context : {r.system_context}")
            print(f"  edit_type      : {r.edit_type.value}")
            print(f"  cell_line      : {r.cell_line.value}")
            print(f"  assumptions    : {r.assumptions_made}")
            print(f"  PASS  ({res['elapsed']:.2f}s)")
            passed += 1
        else:
            print(f"  FAIL  ({res['elapsed']:.2f}s): {res['error']}")
            failed += 1

    total = time.perf_counter() - suite_start
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES)}")
    print(f"Total time: {total:.2f}s  (parallel)")
    print("=" * 60)


if __name__ == "__main__":
    # Run with:  python agents/parser.py
    # Or with a custom hypothesis:  python agents/parser.py "Your hypothesis here"
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
        result = parse_hypothesis(user_input)
        print(result.model_dump_json(indent=2))
    else:
        _run_tests()
