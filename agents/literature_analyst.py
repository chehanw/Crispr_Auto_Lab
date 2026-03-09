"""
Literature Analyst Agent (Stage 2.5 — optional enrichment)

Extracts experimentally useful knowledge from PubMed abstracts.
Does NOT summarize papers. Extracts practical guidance for CRISPR protocol design.

Input:
    - target_gene: str
    - experimental_context: str
    - papers: list of dicts with title, journal, year, abstract

Output:
    dict matching LITERATURE_SCHEMA — structured insights + source papers

Runs between sgRNA retrieval and protocol generation to enrich the protocol
with literature-grounded guidance.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# TODO: remove sys.path hack after proper packaging (pyproject.toml)
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import MODEL_FAST, MAX_TOKENS
from utils.llm_utils import extract_json

MAX_RETRIES = 3

REQUIRED_INSIGHT_KEYS = {
    "recommended_methods",
    "validation_strategies",
    "control_recommendations",
    "assay_examples",
    "common_pitfalls",
}

# ── Prompts ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a scientific literature analyst for CRISPR experimental design.

Your task is to extract experimentally useful knowledge from PubMed abstracts.
You are NOT summarizing papers. You are extracting practical guidance.

Focus on:
- sgRNA design considerations
- delivery methods
- validation strategies
- experimental controls
- phenotype assays
- common pitfalls or failure modes

Return ONLY valid JSON — no markdown, no code fences, no explanation.

Schema:
{
  "literature_insights": {
    "recommended_methods": ["<practical method recommendation — one sentence>"],
    "validation_strategies": ["<specific validation approach — one sentence>"],
    "control_recommendations": ["<specific control to include — one sentence>"],
    "assay_examples": ["<assay used in these papers — one sentence>"],
    "common_pitfalls": ["<failure mode or caution — one sentence>"]
  },
  "source_papers": [
    {
      "title": "<paper title>",
      "journal": "<journal name>",
      "year": "<year>",
      "key_finding": "<one sentence: the most relevant finding from this paper for the experiment>"
    }
  ]
}

Rules:
- Only use information supported by the provided abstracts.
- Do NOT invent citations or experimental details not in the abstracts.
- Each list: 3–5 items maximum.
- One sentence per item. Be concise and practical.
- source_papers must match the input papers exactly — do not alter titles or years.
- key_finding: one sentence capturing the single most relevant finding for THIS experiment (gene + context). Be specific, not generic.
- If an abstract contains no relevant guidance for a category, leave that list shorter."""

USER_TEMPLATE = """\
Target gene: {target_gene}
Experimental context: {experimental_context}

Papers:
{papers_text}

Extract experimental guidance now."""


# ── Public API ─────────────────────────────────────────────────────────────

def analyze_literature(
    target_gene: str,
    experimental_context: str,
    papers: list[dict],
) -> dict:
    """
    Extract experimental guidance from PubMed abstracts.

    Args:
        target_gene:            Gene being targeted (e.g. "TP53").
        experimental_context:   Free-text context (e.g. "apoptosis in HeLa cells").
        papers:                 List of dicts, each with keys:
                                title, journal, year, abstract.

    Returns:
        Dict with keys: literature_insights, source_papers.

    Raises:
        ValueError:         If inputs are invalid or all retries fail.
        EnvironmentError:   If ANTHROPIC_API_KEY is not set.
        anthropic.APIError: On unrecoverable API failures.
    """
    _validate_inputs(target_gene, experimental_context, papers)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    papers_text = _format_papers(papers)
    base_msg = USER_TEMPLATE.format(
        target_gene=target_gene.strip().upper(),
        experimental_context=experimental_context.strip(),
        papers_text=papers_text,
    )

    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        user_content = base_msg
        if last_error:
            user_content += f"\n\nPrevious attempt failed: {last_error}\nReturn corrected JSON only."

        try:
            message = client.messages.create(
                model=MODEL_FAST,
                max_tokens=MAX_TOKENS,
                temperature=0.1,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = message.content[0].text.strip()
            return _parse_and_validate(raw)

        except ValueError as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise ValueError(
                    f"Literature analysis failed after {MAX_RETRIES} attempts. "
                    f"Last error: {last_error}"
                ) from exc

    raise RuntimeError("Unexpected exit from retry loop.")  # pragma: no cover


# ── Helpers ────────────────────────────────────────────────────────────────

def _validate_inputs(target_gene: str, experimental_context: str, papers: list[dict]) -> None:
    if not target_gene or not target_gene.strip():
        raise ValueError("target_gene must be a non-empty string.")
    if not experimental_context or not experimental_context.strip():
        raise ValueError("experimental_context must be a non-empty string.")
    if not papers:
        raise ValueError("papers list must not be empty.")
    for i, p in enumerate(papers):
        for key in ("title", "journal", "year", "abstract"):
            if key not in p or not str(p[key]).strip():
                raise ValueError(f"Paper {i} missing or empty field: '{key}'")


def _format_papers(papers: list[dict]) -> str:
    parts = []
    for i, p in enumerate(papers, 1):
        parts.append(
            f"[{i}] {p['title']}\n"
            f"    Journal: {p['journal']} ({p['year']})\n"
            f"    Abstract: {p['abstract'].strip()}"
        )
    return "\n\n".join(parts)


def _parse_and_validate(text: str) -> dict:
    data = extract_json(text)

    if "literature_insights" not in data:
        raise ValueError("Missing key: 'literature_insights'")
    if "source_papers" not in data:
        raise ValueError("Missing key: 'source_papers'")

    insights = data["literature_insights"]
    missing = REQUIRED_INSIGHT_KEYS - insights.keys()
    if missing:
        raise ValueError(f"literature_insights missing keys: {missing}")

    for key in REQUIRED_INSIGHT_KEYS:
        if not isinstance(insights[key], list):
            raise ValueError(f"literature_insights.{key} must be a list.")

    if not isinstance(data["source_papers"], list) or not data["source_papers"]:
        raise ValueError("source_papers must be a non-empty list.")

    return data


# ── Display ────────────────────────────────────────────────────────────────

def print_literature_insights(result: dict) -> None:
    insights = result["literature_insights"]
    sources = result["source_papers"]

    labels = {
        "recommended_methods":    "Recommended Methods",
        "validation_strategies":  "Validation Strategies",
        "control_recommendations": "Control Recommendations",
        "assay_examples":         "Assay Examples",
        "common_pitfalls":        "Common Pitfalls",
    }

    for key, label in labels.items():
        items = insights.get(key, [])
        if items:
            print(f"\n  — {label} —")
            for item in items:
                print(f"    • {item}")

    print(f"\n  — Sources ({len(sources)} paper(s)) —")
    for s in sources:
        print(f"    [{s['year']}] {s['title']} — {s['journal']}")


# ── Test Harness ───────────────────────────────────────────────────────────

FIXTURE_PAPERS = [
    {
        "title": "High-fidelity CRISPR-Cas9 variants with undetectable genome-wide off-targets",
        "journal": "Nature",
        "year": "2016",
        "abstract": (
            "We describe SpCas9-HF1 (high-fidelity variant 1), which harbors alterations "
            "designed to reduce non-specific DNA contacts. SpCas9-HF1 retains on-target "
            "activities comparable to wild-type SpCas9 with >85% of sgRNAs while nearly "
            "eliminating detectable off-target mutations. We identified off-target mutations "
            "using GUIDE-seq and found none detectable with SpCas9-HF1. These results suggest "
            "SpCas9-HF1 can be used in place of wild-type SpCas9 for most applications where "
            "on-target activity and minimal off-target mutations are desired."
        ),
    },
    {
        "title": "Optimized sgRNA design to maximize activity and minimize off-target effects of CRISPR-Cas9",
        "journal": "Nature Biotechnology",
        "year": "2016",
        "abstract": (
            "Genome-wide CRISPR-Cas9 knockout screens have identified essential genes and drug "
            "targets. We show that sgRNA activity is strongly influenced by the nucleotide "
            "composition and position of mismatches. sgRNAs with G at position 20 (the PAM-distal "
            "position) showed consistently higher activity. We recommend designing sgRNAs to "
            "target early exons and avoid repetitive regions. T7E1 assay was used to evaluate "
            "editing efficiency, and Sanger sequencing with TIDE analysis was used to confirm "
            "indels. Including two independent sgRNAs targeting different exons significantly "
            "reduces false-positive phenotypes in screens."
        ),
    },
    {
        "title": "TP53 mutation and loss in human cancers: implications for therapy",
        "journal": "Nature Reviews Cancer",
        "year": "2021",
        "abstract": (
            "TP53 is mutated in >50% of human cancers. Loss-of-function TP53 mutations confer "
            "resistance to DNA-damaging agents including cisplatin through abrogation of the "
            "G1/S checkpoint and impaired apoptotic signaling. CRISPR-based TP53 knockout in "
            "cancer cell lines must account for HeLa-specific caveats: HPV-18 E6 protein "
            "constitutively degrades p53 via MDM2-independent proteasomal degradation, making "
            "HeLa cells a poor model for p53 loss-of-function. MCF7 and A549 cells retain "
            "functional wild-type p53 and are preferred models. Functional validation of TP53 "
            "knockout should include p21 induction, BAX upregulation, and Annexin V apoptosis "
            "assays following DNA damage (e.g., doxorubicin or ionizing radiation) rather than "
            "cisplatin alone, which activates multiple pathways."
        ),
    },
]

TEST_CASES = [
    {
        "label": "TP53 — 3 real abstracts",
        "target_gene": "TP53",
        "experimental_context": "apoptosis and cisplatin resistance in HeLa cells",
        "papers": FIXTURE_PAPERS,
    },
    {
        "label": "KRAS — single abstract",
        "target_gene": "KRAS",
        "experimental_context": "ERK signaling in HEK293 cells",
        "papers": [FIXTURE_PAPERS[1]],  # reuse sgRNA design paper — still relevant
    },
]


def _run_tests() -> None:
    print("=" * 60)
    print("AutoLab-CRISPR  |  Literature Analyst  |  Test Harness")
    print("=" * 60)

    passed = failed = 0

    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {case['label']}")
        t0 = time.perf_counter()
        try:
            result = analyze_literature(
                case["target_gene"],
                case["experimental_context"],
                case["papers"],
            )
            elapsed = time.perf_counter() - t0
            print_literature_insights(result)
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
