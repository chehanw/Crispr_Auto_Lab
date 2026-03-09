"""
Feasibility Check (Stage 1.5)

Runs between hypothesis parsing and protocol generation.
Catches biological incompatibilities before wasting LLM calls on a flawed design.

Two-layer approach:
  Layer 1 — Instant Python lookup of known incompatibilities (zero latency)
  Layer 2 — Lightweight Haiku call for combinations not in the lookup

Flag severities:
  warning — proceed, but print the issue prominently
  blocker — halt the pipeline; the experiment is scientifically unsound as-stated
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import MODEL_FAST, MAX_TOKENS
from models.schemas import EditType, ParsedHypothesis


# ── DepMap common essential genes ──────────────────────────────────────────

def _load_common_essential_genes(path: str = "data/CRISPRInferredCommonEssentials.csv") -> frozenset[str]:
    """
    Load the DepMap common essential gene list at import time.
    Returns an empty frozenset if the file is missing — the check
    simply becomes a no-op until the file is present.
    """
    p = Path(__file__).parent.parent / path
    if not p.exists():
        return frozenset()
    with open(p) as f:
        return frozenset(line.strip().upper() for line in f if line.strip())


COMMON_ESSENTIAL_GENES: frozenset[str] = _load_common_essential_genes()


# ── Flag dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FeasibilityFlag:
    severity: str        # "warning" | "blocker"
    issue: str
    recommendation: str

    def is_blocker(self) -> bool:
        return self.severity == "blocker"


# ── Layer 1: Hardcoded incompatibility lookup ──────────────────────────────
#
# Keys: (gene_upper, cell_line_value)
# Add entries as new incompatibilities are discovered.

KNOWN_INCOMPATIBILITIES: dict[tuple[str, str], FeasibilityFlag] = {
    ("TP53", "HeLa"): FeasibilityFlag(
        severity="warning",
        issue="HeLa cells carry HPV-18 E6, which constitutively degrades p53. "
              "TP53 is already functionally inactivated — knockout may produce minimal additional phenotype.",
        recommendation="Use a p53-WT cell line (A549, MCF7, HCT116 p53+/+) to study TP53 loss-of-function. "
                       "If HeLa is required, include a p53-WT control line for comparison.",
    ),
    ("RB1", "HeLa"): FeasibilityFlag(
        severity="warning",
        issue="HeLa cells express HPV-18 E7, which inactivates Rb. "
              "RB1 knockout may have minimal additional effect on proliferation.",
        recommendation="Use Rb-proficient cells (e.g., MCF7, RPE-1) for RB1 loss-of-function studies.",
    ),
    ("CDKN2A", "HeLa"): FeasibilityFlag(
        severity="warning",
        issue="CDKN2A (p16/ARF) is commonly deleted or silenced in HeLa cells. "
              "Baseline expression may already be absent.",
        recommendation="Confirm CDKN2A expression in your HeLa stock by Western/qPCR before proceeding.",
    ),
    ("KRAS", "HEK293"): FeasibilityFlag(
        severity="warning",
        issue="HEK293 cells harbor adenovirus 5 sequences and show atypical RAS-MAPK signaling. "
              "KRAS knockout phenotypes may not recapitulate primary tissue biology.",
        recommendation="Use a cancer-relevant cell line (e.g., A549 for KRAS-driven lung adenocarcinoma) "
                       "to better model the oncogenic context.",
    ),
    ("BRCA1", "HEK293"): FeasibilityFlag(
        severity="warning",
        issue="HEK293 cells are not a standard model for BRCA1-related DNA repair phenotypes. "
              "HR deficiency readouts may be confounded by the transformed background.",
        recommendation="Use MCF10A, RPE-1, or patient-derived breast epithelial cells for BRCA1 functional studies.",
    ),
}


def _lookup_incompatibilities(hypothesis: ParsedHypothesis) -> list[FeasibilityFlag]:
    """Return any hardcoded flags for this gene × cell line combination."""
    key = (hypothesis.target_gene.upper(), hypothesis.cell_line.value)
    flag = KNOWN_INCOMPATIBILITIES.get(key)
    return [flag] if flag else []


def _check_essential_gene(hypothesis: ParsedHypothesis) -> list[FeasibilityFlag]:
    """
    Warn if the target gene is a DepMap common essential and the edit is a knockout.
    Returns an empty list if the essential gene dataset is not loaded.
    """
    if not COMMON_ESSENTIAL_GENES:
        return []
    if hypothesis.edit_type != EditType.KNOCKOUT:
        return []
    gene = hypothesis.target_gene.upper()
    if gene not in COMMON_ESSENTIAL_GENES:
        return []
    return [FeasibilityFlag(
        severity="warning",
        issue=(
            f"DepMap CRISPR screens identify {hypothesis.target_gene} as a commonly essential "
            f"gene across many cell lines. Complete knockout may cause severe loss of viability "
            f"or cell death rather than a measurable phenotype."
        ),
        recommendation=(
            f"Consider CRISPRi/dCas9 repression or inducible knockout (e.g. auxin-inducible "
            f"degron) to modulate {hypothesis.target_gene} without complete loss. "
            f"If full KO is required, verify cell viability 48-72 h post-transfection "
            f"before proceeding to phenotypic assays."
        ),
    )]


# ── Layer 2: LLM biological sanity check ──────────────────────────────────

SYSTEM_PROMPT = """\
You are a CRISPR experimental design consultant doing a rapid feasibility pre-check.
Given a parsed hypothesis, identify any biological or technical issues that would make
this experiment scientifically unsound, technically infeasible, or likely to produce
uninterpretable results.

Return ONLY valid JSON — no markdown, no code fences.

Schema:
{
  "flags": [
    {
      "severity": "<warning | blocker>",
      "issue": "<specific biological or technical problem — one sentence, precise>",
      "recommendation": "<concrete fix — one sentence>"
    }
  ]
}

Rules:
- Only flag REAL problems. Do not flag minor style preferences.
- blocker: experiment cannot answer the hypothesis as stated (wrong model, gene already KO, etc.)
- warning: experiment can proceed but has a known caveat that must be acknowledged.
- Return an empty flags list if the design is sound: {"flags": []}
- Maximum 3 flags. Prioritize the most critical.
- Do NOT repeat issues already obvious from the hypothesis text itself."""

USER_TEMPLATE = """\
Parsed hypothesis:
{hypothesis_json}

Flag any biological feasibility issues. Be concise."""


def _llm_feasibility_check(hypothesis: ParsedHypothesis) -> list[FeasibilityFlag]:
    """Quick Haiku call for feasibility issues not covered by the lookup."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return []  # Silently skip if no key — don't block the pipeline

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=MODEL_FAST,
            max_tokens=512,        # Short — we want a quick check, not an essay
            temperature=0.1,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": USER_TEMPLATE.format(
                hypothesis_json=hypothesis.model_dump_json(indent=2)
            )}],
        )
        raw = message.content[0].text.strip()
        return _parse_llm_flags(raw)
    except Exception:
        return []  # Never block the pipeline on a feasibility check failure


def _parse_llm_flags(text: str) -> list[FeasibilityFlag]:
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    flags = []
    for item in data.get("flags", []):
        # LLM-generated flags are capped at "warning" — only the curated
        # hardcoded lookup should ever halt the pipeline with a blocker.
        flags.append(FeasibilityFlag(
            severity="warning",
            issue=item.get("issue", ""),
            recommendation=item.get("recommendation", ""),
        ))
    return flags


# ── Public API ─────────────────────────────────────────────────────────────

def check_feasibility(hypothesis: ParsedHypothesis) -> list[FeasibilityFlag]:
    """
    Run both feasibility layers and return deduplicated flags.

    Layer 1 (instant lookup) always runs.
    Layer 2 (LLM) runs only if no blocker was found in Layer 1,
    and only for combinations not already covered by the lookup.

    Args:
        hypothesis: ParsedHypothesis from Stage 1.

    Returns:
        List of FeasibilityFlag. Empty = no issues found.
        Blockers should halt the pipeline; warnings should be printed.
    """
    lookup_flags   = _lookup_incompatibilities(hypothesis)
    essential_flags = _check_essential_gene(hypothesis)

    # Skip LLM check if lookup already returned a blocker
    has_blocker = any(f.is_blocker() for f in lookup_flags)
    lookup_key = (hypothesis.target_gene.upper(), hypothesis.cell_line.value)
    already_covered = lookup_key in KNOWN_INCOMPATIBILITIES

    llm_flags: list[FeasibilityFlag] = []
    if not has_blocker and not already_covered:
        llm_flags = _llm_feasibility_check(hypothesis)

    # Deduplicate: drop LLM flags whose issue text overlaps with lookup or essential flags
    static_issues = {f.issue[:40].lower() for f in lookup_flags + essential_flags}
    deduped_llm = [
        f for f in llm_flags
        if not any(f.issue[:40].lower() in si or si in f.issue[:40].lower()
                   for si in static_issues)
    ]

    return lookup_flags + essential_flags + deduped_llm


def print_feasibility_flags(flags: list[FeasibilityFlag]) -> None:
    if not flags:
        print("  [✓] No feasibility issues detected.")
        return
    for f in flags:
        icon = "✗" if f.is_blocker() else "!"
        print(f"  [{icon}] [{f.severity.upper()}] {f.issue}")
        print(f"        → {f.recommendation}")


# ── Test Harness ───────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "label": "HeLa + TP53 — known incompatibility (lookup hit)",
        "gene": "TP53", "cell_line": "HeLa",
        "expect_flags": True,
    },
    {
        "label": "HeLa + RB1 — known incompatibility (lookup hit)",
        "gene": "RB1", "cell_line": "HeLa",
        "expect_flags": True,
    },
    {
        "label": "HEK293 + KRAS — known warning (lookup hit)",
        "gene": "KRAS", "cell_line": "HEK293",
        "expect_flags": True,
    },
    {
        "label": "HEK293 + EGFR — unknown combo, LLM check",
        "gene": "EGFR", "cell_line": "HEK293",
        "expect_flags": None,  # Unknown — LLM decides
    },
    {
        "label": "Jurkat + MYC — clean combo, expect no blockers",
        "gene": "MYC", "cell_line": "Jurkat",
        "expect_flags": None,
    },
]


def _run_tests() -> None:
    from models.schemas import CellLine, EditType

    cell_line_map = {
        "HeLa": CellLine.HELA,
        "HEK293": CellLine.HEK293,
        "Jurkat": CellLine.JURKAT,
    }

    print("=" * 60)
    print("AutoLab-CRISPR  |  Feasibility Check  |  Test Harness")
    print("=" * 60)

    passed = failed = 0

    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {case['label']}")
        cell_line = cell_line_map.get(case["cell_line"], CellLine.OTHER)

        hypothesis = ParsedHypothesis(
            target_gene=case["gene"],
            phenotype="test phenotype",
            system_context="test context",
            assumptions_made=[],
            edit_type=EditType.KNOCKOUT,
            cell_line=cell_line,
            raw_hypothesis=f"Knock out {case['gene']} in {case['cell_line']} cells.",
        )

        try:
            flags = check_feasibility(hypothesis)
            print_feasibility_flags(flags)

            if case["expect_flags"] is True and not flags:
                raise AssertionError("Expected flags but got none.")
            if case["expect_flags"] is False and flags:
                raise AssertionError(f"Expected no flags but got {len(flags)}.")

            blockers = [f for f in flags if f.is_blocker()]
            print(f"  → {len(flags)} flag(s), {len(blockers)} blocker(s)  PASS")
            passed += 1
        except Exception as exc:
            print(f"  FAIL: {exc}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES)}")
    print("=" * 60)


if __name__ == "__main__":
    _run_tests()
