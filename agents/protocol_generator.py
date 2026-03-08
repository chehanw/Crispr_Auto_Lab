"""
Protocol Generator Agent (Stage 3)

Input:
    - ParsedHypothesis  (Stage 1 output)
    - SgRNAResults      (Stage 2 output — ranked candidates)
    - literature        (optional free-text grounding from papers / databases)

Output:
    KnockoutProtocol — validated Pydantic model + raw dict

Retry policy: up to MAX_RETRIES attempts on JSON parse / schema errors.
Each retry appends the prior failure as context so the model can self-correct.
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

from config import MODEL_MAIN, MAX_TOKENS, TEMPERATURE
from models.schemas import (
    KnockoutProtocol,
    ParsedHypothesis,
    SgRNAResults,
)
from utils.llm_utils import extract_json

# ── Constants ──────────────────────────────────────────────────────────────

MAX_RETRIES = 3

# ── Prompts ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert CRISPR molecular biology protocol designer.
Given a parsed hypothesis, ranked sgRNA candidates, and optional literature context,
produce a complete, reproducible knockout protocol as valid JSON.

Return ONLY valid JSON — no markdown, no code fences, no explanation.

Schema (all fields required unless marked optional):
{
  "gene": "<HGNC gene symbol>",
  "cell_line": "<one of: HEK293, HeLa, Jurkat, primary, other>",
  "transfection_method": "<one of: lipofectamine, electroporation, lentiviral, rnp>",
  "selected_sgrna": {
    "guide_id": "<string>",
    "gene": "<string>",
    "sequence": "<exactly 20 nucleotides, e.g. ACGTACGTACGTACGTACGT>",
    "efficiency_score": <float 0.0–1.0>,
    "off_target_score": <float 0.0–1.0>,
    "pam": "<string, typically NGG>",
    "chromosome": "<string or null>",
    "position": <integer or null>
  },
  "steps": [
    {
      "step_number": <integer starting at 1>,
      "title": "<short action title>",
      "description": "<detailed instructions>",
      "duration_hours": <float or null>,
      "critical_notes": "<string or null>"
    }
  ],
  "total_duration_days": <float>,
  "expected_efficiency_pct": <float 0.0–100.0>,
  "validation_assay": "<e.g. T7E1 assay, Sanger sequencing, Western blot>",
  "safety_notes": ["<list of biosafety considerations>"]
}

Rules:
- Select the sgRNA with the best balance of efficiency_score (high) and off_target_score (low).
- Choose transfection_method based on cell_line: HEK293/HeLa → lipofectamine; Jurkat/primary → electroporation.
- Include at minimum 5 protocol steps covering: cell culture prep, guide delivery, incubation, selection, validation.
- total_duration_days must be consistent with step durations.
- safety_notes must include at least one BSL-2 handling note.
- Never return null for required fields.
- sequence must be exactly 20 characters (nucleotides only).\
"""

USER_TEMPLATE = """\
Parsed Hypothesis:
{hypothesis_json}

sgRNA Candidates (ranked by efficiency desc):
{sgrna_json}

Literature / Database Context:
{literature}

Generate the knockout protocol JSON now.\
"""

RETRY_SUFFIX = "\n\nPrevious attempt failed with error: {error}\nReturn corrected JSON only."


# ── Public API ─────────────────────────────────────────────────────────────

def generate_protocol(
    hypothesis: ParsedHypothesis,
    sgrna_results: SgRNAResults,
    literature: str | None = None,
) -> tuple[KnockoutProtocol, dict]:
    """
    Call Claude to produce a structured knockout protocol.

    Args:
        hypothesis:    Validated ParsedHypothesis from Stage 1.
        sgrna_results: Ranked SgRNAResults from Stage 2.
        literature:    Optional grounding text (paper abstracts, DB entries).

    Returns:
        Tuple of (KnockoutProtocol, raw_dict) — Pydantic model + underlying dict.

    Raises:
        ValueError:            If all retries exhaust without valid JSON/schema.
        EnvironmentError:      If ANTHROPIC_API_KEY is missing.
        anthropic.APIError:    On unrecoverable API failures.
    """
    _validate_inputs(hypothesis)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)

    base_user_msg = USER_TEMPLATE.format(
        hypothesis_json=hypothesis.model_dump_json(indent=2),
        sgrna_json=sgrna_results.model_dump_json(indent=2),
        literature=literature.strip() if literature else "No additional context provided.",
    )

    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        user_content = base_user_msg
        if last_error:
            user_content += RETRY_SUFFIX.format(error=last_error)

        try:
            message = client.messages.create(
                model=MODEL_MAIN,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw_text = message.content[0].text.strip()
            raw_dict = extract_json(raw_text)
            protocol = _validate_schema(raw_dict)
            return protocol, raw_dict

        except (ValueError, ValidationError) as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise ValueError(
                    f"Protocol generation failed after {MAX_RETRIES} attempts. "
                    f"Last error: {last_error}"
                ) from exc

    raise RuntimeError("Unexpected exit from retry loop.")  # pragma: no cover


# ── Helpers ────────────────────────────────────────────────────────────────

def _validate_inputs(hypothesis: ParsedHypothesis) -> None:
    """Fast pre-flight check for conditions Pydantic does not enforce."""
    if not hypothesis.target_gene:
        raise ValueError("hypothesis.target_gene must be non-empty.")


def _validate_schema(data: dict) -> KnockoutProtocol:
    """Validate dict against KnockoutProtocol Pydantic schema."""
    try:
        return KnockoutProtocol(**data)
    except ValidationError as exc:
        raise ValueError(f"Schema validation failed: {exc}") from exc


# ── CLI / Test Harness ─────────────────────────────────────────────────────

def _make_fixture() -> tuple[ParsedHypothesis, SgRNAResults]:
    """Minimal in-memory fixtures — no files required."""
    from models.schemas import CellLine, EditType, SgRNACandidate

    hypothesis = ParsedHypothesis(
        target_gene="TP53",
        phenotype="Loss of apoptosis checkpoint leading to uncontrolled proliferation",
        system_context="Cancer biology / p53 tumour suppressor pathway",
        assumptions_made=["Cell line defaulted to HEK293", "Edit type defaulted to knockout"],
        edit_type=EditType.KNOCKOUT,
        cell_line=CellLine.HEK293,
        raw_hypothesis="Knocking out TP53 in cancer cells will lead to uncontrolled proliferation.",
    )

    candidates = [
        SgRNACandidate(
            guide_id="TP53_g1",
            gene="TP53",
            sequence="GCACTTTGATGTCAACAGAT",
            efficiency_score=0.87,
            off_target_score=0.12,
            pam="NGG",
            chromosome="chr17",
            position=7676520,
        ),
        SgRNACandidate(
            guide_id="TP53_g2",
            gene="TP53",
            sequence="ACTTCCTGAAAACAACGTTC",
            efficiency_score=0.81,
            off_target_score=0.18,
            pam="NGG",
            chromosome="chr17",
            position=7676154,
        ),
    ]

    sgrna_results = SgRNAResults(gene="TP53", candidates=candidates)
    return hypothesis, sgrna_results


TEST_CASES = [
    {
        "label": "TP53 knockout — no literature",
        "literature": None,
    },
    {
        "label": "TP53 knockout — with literature grounding",
        "literature": (
            "Joung et al. (2017) Nat Methods: SpCas9 with NGG PAM achieves "
            ">80% indel efficiency in HEK293 cells when delivered via lipofection. "
            "T7E1 mismatch cleavage assay recommended for rapid validation."
        ),
    },
]


def _run_one(
    idx: int,
    case: dict,
    hypothesis: ParsedHypothesis,
    sgrna_results: SgRNAResults,
) -> dict:
    t0 = time.perf_counter()
    try:
        protocol, _ = generate_protocol(hypothesis, sgrna_results, case["literature"])
        return {
            "idx": idx,
            "label": case["label"],
            "elapsed": time.perf_counter() - t0,
            "ok": True,
            "protocol": protocol,
        }
    except Exception as exc:
        return {
            "idx": idx,
            "label": case["label"],
            "elapsed": time.perf_counter() - t0,
            "ok": False,
            "error": str(exc),
        }


def _run_tests() -> None:
    print("=" * 60)
    print("AutoLab-CRISPR  |  Protocol Generator  |  Test Harness (parallel)")
    print(f"Running {len(TEST_CASES)} cases in parallel — est. ~10–15s total")
    print("=" * 60)

    hypothesis, sgrna_results = _make_fixture()
    suite_start = time.perf_counter()
    results: list[dict | None] = [None] * len(TEST_CASES)

    with ThreadPoolExecutor(max_workers=len(TEST_CASES)) as pool:
        # Pass immutable snapshots so threads never share mutable state.
        futures = {
            pool.submit(_run_one, i, case, hypothesis.model_copy(), sgrna_results.model_copy()): i
            for i, case in enumerate(TEST_CASES)
        }
        for future in as_completed(futures):
            res = future.result()
            results[res["idx"]] = res

    passed = failed = 0
    for i, res in enumerate(results, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {res['label']}")
        if res["ok"]:
            p = res["protocol"]
            print(f"  gene               : {p.gene}")
            print(f"  cell_line          : {p.cell_line.value}")
            print(f"  transfection       : {p.transfection_method.value}")
            print(f"  selected_guide     : {p.selected_sgrna.guide_id}")
            print(f"  steps              : {len(p.steps)}")
            print(f"  duration_days      : {p.total_duration_days}")
            print(f"  expected_efficiency: {p.expected_efficiency_pct}%")
            print(f"  validation_assay   : {p.validation_assay}")
            print(f"  safety_notes       : {len(p.safety_notes)} note(s)")
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
    if len(sys.argv) > 1:
        # Quick smoke test with a custom hypothesis string (reuses fixture sgRNAs)
        from models.schemas import CellLine, EditType
        hyp = ParsedHypothesis(
            target_gene="TP53",
            phenotype="user-specified",
            system_context="user-specified",
            assumptions_made=[],
            edit_type=EditType.KNOCKOUT,
            cell_line=CellLine.HEK293,
            raw_hypothesis=" ".join(sys.argv[1:]),
        )
        _, sgr = _make_fixture()
        proto, _ = generate_protocol(hyp, sgr)
        print(proto.model_dump_json(indent=2))
    else:
        _run_tests()
