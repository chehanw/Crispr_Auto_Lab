"""
Reviewer Agent (Stage 4)

Critiques a generated CRISPR protocol like a scientific peer reviewer.
Does not rubber-stamp — flags real weaknesses with concrete fixes.

Input:  ParsedHypothesis + KnockoutProtocol
Output: dict matching the review schema (see REVIEW_SCHEMA below)

Retry policy: up to MAX_RETRIES on JSON/schema failures.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import MODEL_FAST, MAX_TOKENS
from models.schemas import KnockoutProtocol, ParsedHypothesis

MAX_RETRIES = 3

VALID_VERDICTS = {"approve", "approve_with_warnings", "revise", "major_revision"}
VALID_SEVERITIES = {"info", "warning", "critical"}
VALID_CATEGORIES = {
    "controls", "guide_selection", "validation", "assay_design",
    "statistics", "timeline", "safety", "feasibility",
}

# ── Prompts ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a rigorous scientific peer reviewer specializing in CRISPR functional genomics.
You review CRISPR knockout protocols with the same critical eye as a Nature Methods reviewer.

You are NOT a rubber stamp. Your job is to find real problems.

Return ONLY valid JSON — no markdown, no code fences, no explanation.

Schema:
{
  "overall_verdict": "<one of: approve | approve_with_warnings | revise | major_revision>",
  "validation_flags": [
    {
      "severity": "<one of: info | warning | critical>",
      "category": "<one of: controls | guide_selection | validation | assay_design | statistics | timeline | safety | feasibility>",
      "issue": "<specific scientific problem — be precise, not vague>",
      "recommendation": "<concrete fix, not a platitude>"
    }
  ],
  "review_summary": "<2–4 sentence verdict. Be direct. State the biggest risk first.>"
}

Scoring guide for overall_verdict:
- approve:               No significant issues. Protocol is solid.
- approve_with_warnings: Minor gaps that should be addressed but won't invalidate results.
- revise:                One or more moderate issues that could compromise conclusions.
- major_revision:        Critical flaw that would invalidate the experiment or make it unpublishable.

What to look for (non-exhaustive):
- Missing negative controls (non-targeting sgRNA, mock transfection)
- Missing positive controls
- Off-target risk not addressed (no off-target validation assay)
- Only one sgRNA tested (should validate with ≥2 independent guides)
- No rescue experiment proposed
- Validation at DNA level only (no protein confirmation or vice versa)
- Unrealistic efficiency expectations given cell line / method
- Insufficient clones analyzed for homozygous knockout
- No isogenic control proposed
- Functional assay not matched to stated phenotype
- Timeline inconsistencies
- Safety gaps for hazardous reagents
- Cell-line-specific caveats not addressed (e.g. HeLa / HPV, p53 status)

Be concise. One flag per distinct issue. Do not pad with obvious boilerplate."""

USER_TEMPLATE = """\
Hypothesis:
{hypothesis_json}

Generated Protocol:
{protocol_json}

Review this protocol now. Be critical."""

RETRY_SUFFIX = "\n\nYour previous response failed validation with error: {error}\nReturn corrected JSON only."


# ── Public API ─────────────────────────────────────────────────────────────

def review_protocol(
    hypothesis: ParsedHypothesis,
    protocol: KnockoutProtocol,
) -> dict:
    """
    Critique a CRISPR protocol like a peer reviewer.

    Args:
        hypothesis: ParsedHypothesis from Stage 1.
        protocol:   KnockoutProtocol from Stage 3.

    Returns:
        Validated review dict with keys:
        overall_verdict, validation_flags, review_summary.

    Raises:
        ValueError:         If all retries fail validation.
        EnvironmentError:   If ANTHROPIC_API_KEY is missing.
        anthropic.APIError: On unrecoverable API failures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)

    base_msg = USER_TEMPLATE.format(
        hypothesis_json=hypothesis.model_dump_json(indent=2),
        protocol_json=protocol.model_dump_json(indent=2),
    )

    last_error: Optional[str] = None

    for attempt in range(1, MAX_RETRIES + 1):
        user_content = base_msg
        if last_error:
            user_content += RETRY_SUFFIX.format(error=last_error)

        try:
            message = client.messages.create(
                model=MODEL_FAST,
                max_tokens=MAX_TOKENS,
                temperature=0.3,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = message.content[0].text.strip()
            review = _parse_and_validate(raw)
            return review

        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise ValueError(
                    f"Review failed after {MAX_RETRIES} attempts. Last error: {last_error}"
                ) from exc

    raise RuntimeError("Unexpected exit from retry loop.")  # pragma: no cover


# ── Validation ─────────────────────────────────────────────────────────────

def _parse_and_validate(text: str) -> dict:
    """Extract JSON and validate review schema fields."""
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error: {exc}\nRaw: {text[:400]}") from exc

    # Validate top-level keys
    required = {"overall_verdict", "validation_flags", "review_summary"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Missing required keys: {missing}")

    if data["overall_verdict"] not in VALID_VERDICTS:
        raise ValueError(f"Invalid verdict: {data['overall_verdict']!r}. Must be one of {VALID_VERDICTS}")

    if not isinstance(data["validation_flags"], list):
        raise ValueError("validation_flags must be a list.")

    for i, flag in enumerate(data["validation_flags"]):
        for key in ("severity", "category", "issue", "recommendation"):
            if key not in flag:
                raise ValueError(f"Flag {i} missing key: {key!r}")
        if flag["severity"] not in VALID_SEVERITIES:
            raise ValueError(f"Flag {i} invalid severity: {flag['severity']!r}")
        if flag["category"] not in VALID_CATEGORIES:
            raise ValueError(f"Flag {i} invalid category: {flag['category']!r}")

    if not isinstance(data["review_summary"], str) or not data["review_summary"].strip():
        raise ValueError("review_summary must be a non-empty string.")

    return data


# ── Display ────────────────────────────────────────────────────────────────

def print_review(review: dict) -> None:
    verdict = review["overall_verdict"].upper().replace("_", " ")
    flags = review["validation_flags"]
    criticals = [f for f in flags if f["severity"] == "critical"]
    warnings  = [f for f in flags if f["severity"] == "warning"]
    infos     = [f for f in flags if f["severity"] == "info"]

    print(f"\n  Verdict        : {verdict}")
    print(f"  Flags          : {len(criticals)} critical  {len(warnings)} warning  {len(infos)} info")
    print(f"  Summary        : {review['review_summary']}")

    if flags:
        print()
        for f in flags:
            icon = {"critical": "✗", "warning": "!", "info": "i"}.get(f["severity"], "?")
            print(f"  [{icon}] [{f['severity'].upper()}] [{f['category']}]")
            print(f"      Issue : {f['issue']}")
            print(f"      Fix   : {f['recommendation']}")


# ── Test Harness ───────────────────────────────────────────────────────────

def _make_fixtures():
    from models.schemas import (
        CellLine, EditType, SgRNACandidate, SgRNAResults,
        TransfectionMethod, ProtocolStep,
    )

    hypothesis = ParsedHypothesis(
        target_gene="TP53",
        phenotype="impaired apoptosis and cisplatin resistance",
        system_context="cancer cell survival and chemotherapy response",
        assumptions_made=[],
        edit_type=EditType.KNOCKOUT,
        cell_line=CellLine.HELA,
        raw_hypothesis="Knocking out TP53 in HeLa cells will impair apoptosis and drive resistance to cisplatin.",
    )

    guide = SgRNACandidate(
        guide_id="TP53_g1", gene="TP53", sequence="GCACTTTGATGTCAACAGAT",
        efficiency_score=0.87, off_target_score=0.12, pam="NGG",
        chromosome="chr17", position=7676520,
    )

    protocol = KnockoutProtocol(
        gene="TP53",
        cell_line=CellLine.HELA,
        transfection_method=TransfectionMethod.LIPOFECTAMINE,
        selected_sgrna=guide,
        steps=[
            ProtocolStep(step_number=1, title="Cell seeding", description="Seed HeLa cells at 70% confluency.", duration_hours=24.0),
            ProtocolStep(step_number=2, title="Transfection", description="Lipofectamine 3000 with pX459 vector.", duration_hours=0.5),
            ProtocolStep(step_number=3, title="Selection", description="Puromycin 1 µg/mL for 5 days.", duration_hours=120.0),
            ProtocolStep(step_number=4, title="Sanger sequencing", description="PCR + Sanger to confirm indels.", duration_hours=8.0),
            ProtocolStep(step_number=5, title="Western blot", description="Anti-p53 Western blot.", duration_hours=8.0),
        ],
        total_duration_days=14.0,
        expected_efficiency_pct=72.0,
        validation_assay="Sanger sequencing, Western blot",
        safety_notes=["BSL-2 containment required.", "Handle cisplatin as hazardous waste."],
    )

    return hypothesis, protocol


TEST_CASES = [
    {"label": "Minimal protocol — should surface missing controls and off-target gaps"},
]


def _run_tests() -> None:
    print("=" * 60)
    print("AutoLab-CRISPR  |  Reviewer Agent  |  Test Harness")
    print("=" * 60)

    hypothesis, protocol = _make_fixtures()
    passed = failed = 0

    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {case['label']}")
        t0 = time.perf_counter()
        try:
            review = review_protocol(hypothesis, protocol)
            elapsed = time.perf_counter() - t0
            print_review(review)
            print(f"\n  PASS  ({elapsed:.2f}s)")
            passed += 1
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"  FAIL  ({elapsed:.2f}s): {exc}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES)}")
    print("=" * 60)


if __name__ == "__main__":
    _run_tests()
