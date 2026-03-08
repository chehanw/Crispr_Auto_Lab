"""
AutoLab-CRISPR — CLI entry point

Usage:
    python main.py --hypothesis "Knocking out TP53 will cause uncontrolled proliferation."

Pipeline (stages run in order):
    1.   parse_hypothesis       → ParsedHypothesis
    1.5. check_feasibility      → FeasibilityFlags  (blocks on critical flags)
    2.   get_guides             → list[dict]  → SgRNAResults
    3→4. revision loop      → generate_protocol → review_protocol
                              repeats up to 3x if criticals remain
    5.   execution packet   → generate_execution_packet
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import datetime
from pathlib import Path

# ── Project imports ────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent))

from agents.parser import parse_hypothesis
from agents.sgrna_retriever import get_guides
from agents.protocol_generator import generate_protocol
from agents.feasibility_check import check_feasibility, print_feasibility_flags
from agents.reviewer import review_protocol, print_review
from agents.execution_planner import generate_execution_packet, print_execution_packet
from agents.literature_analyst import analyze_literature, print_literature_insights
from utils.pubmed_fetcher import fetch_papers
from config import TOP_K_GUIDES, OUTPUT_DIR
from models.schemas import KnockoutProtocol, ParsedHypothesis, SgRNACandidate, SgRNAResults


# ── Helpers ────────────────────────────────────────────────────────────────

def _fetch_literature(gene: str, context: str) -> tuple[dict | None, str]:
    """
    Fetch PubMed papers and extract protocol-relevant insights.

    Returns:
        (lit_result, literature_text) — lit_result is None on failure,
        literature_text is a formatted string for the protocol generator
        (or a fallback message if the fetch fails).
    """
    try:
        papers = fetch_papers(gene, context, max_papers=4)
        if not papers:
            return None, "No additional context provided."
        lit_result = analyze_literature(gene, context, papers)
        literature_text = _format_literature_for_protocol(lit_result)
        return lit_result, literature_text
    except EnvironmentError as exc:
        print(f"  WARNING: Literature grounding skipped — {exc}", file=sys.stderr)
        return None, "No additional context provided."
    except Exception:
        return None, "No additional context provided."


def _format_literature_for_protocol(lit_result: dict) -> str:
    """Flatten literature insights into a readable string for the protocol generator."""
    insights = lit_result.get("literature_insights", {})
    sources = lit_result.get("source_papers", [])
    lines = []
    for key, label in [
        ("recommended_methods",     "Recommended methods"),
        ("validation_strategies",   "Validation strategies"),
        ("control_recommendations", "Controls"),
        ("assay_examples",          "Assays"),
        ("common_pitfalls",         "Pitfalls to avoid"),
    ]:
        items = insights.get(key, [])
        if items:
            lines.append(f"{label}: " + "; ".join(items))
    if sources:
        citations = ", ".join(f"{s['title'][:60]} ({s['year']})" for s in sources[:3])
        lines.append(f"Sources: {citations}")
    return "\n".join(lines)


def _build_sgrna_results(gene: str, raw_guides: list[dict]) -> SgRNAResults:
    """Convert raw dicts from sgrna_retriever into a validated SgRNAResults model."""
    candidates = [
        SgRNACandidate(
            guide_id=g["guide_id"],
            gene=g["gene_symbol"],
            sequence=g["sgrna_sequence"],
            efficiency_score=g["gc_content"],   # GC content used as efficiency proxy
            off_target_score=0.0,               # Not available in Brunello library
            pam=g.get("pam_sequence", "NGG"),
            chromosome=None,
            position=None,
        )
        for g in raw_guides
    ]
    return SgRNAResults(gene=gene, candidates=candidates)


def _print_section(title: str) -> None:
    width = 60
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")


def _print_hypothesis(hypothesis) -> None:
    _print_section("1. Parsed Hypothesis")
    print(f"  gene          : {hypothesis.target_gene}")
    print(f"  edit_type     : {hypothesis.edit_type.value}")
    print(f"  cell_line     : {hypothesis.cell_line.value}")
    print(f"  phenotype     : {hypothesis.phenotype}")
    print(f"  system_context: {hypothesis.system_context}")
    if hypothesis.assumptions_made:
        print("  assumptions:")
        for a in hypothesis.assumptions_made:
            print(f"    • {a}")


def _print_guides(sgrna_results: SgRNAResults) -> None:
    _print_section("2. Candidate sgRNAs")
    for g in sgrna_results.candidates:
        print(
            f"  {g.guide_id:<12} seq={g.sequence}  "
            f"eff={g.efficiency_score:.2f}  off={g.off_target_score:.2f}  "
            f"pam={g.pam}"
        )


def _print_literature_section(lit_result: dict | None) -> None:
    _print_section("2.5. Literature Grounding")
    if lit_result is None:
        print("  (skipped — no papers retrieved)")
        return
    print_literature_insights(lit_result)


def _print_protocol(protocol) -> None:
    _print_section("3. Protocol JSON")
    print(protocol.model_dump_json(indent=2))


def _print_review_section(review: dict) -> None:
    _print_section("4. Protocol Review")
    print_review(review)


def _print_execution_section(packet: dict) -> None:
    _print_section("5. Execution Packet")
    print_execution_packet(packet)


# ── Main pipeline ──────────────────────────────────────────────────────────

def run(hypothesis_text: str) -> int:
    """Execute the pipeline. Returns 0 on success, 1 on handled error."""

    # ── Stage 1: Parse hypothesis ──────────────────────────────────────────
    print("\n[1/5] Parsing hypothesis…")
    try:
        hypothesis = parse_hypothesis(hypothesis_text)
    except EnvironmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: Could not parse hypothesis — {exc}", file=sys.stderr)
        return 1

    target_gene = hypothesis.target_gene

    # ── Stage 1.5: Feasibility check ──────────────────────────────────────
    print(f"[1.5/5] Checking biological feasibility…")
    flags = check_feasibility(hypothesis)
    print_feasibility_flags(flags)
    blockers = [f for f in flags if f.is_blocker()]
    if blockers:
        print(
            f"\nERROR: {len(blockers)} blocker(s) found. Fix the hypothesis before proceeding.\n",
            file=sys.stderr,
        )
        return 1

    # ── Stage 2: Retrieve sgRNAs ───────────────────────────────────────────
    print(f"[2/5] Looking up sgRNAs for '{target_gene}'…")
    try:
        raw_guides = get_guides(target_gene, max_guides=TOP_K_GUIDES)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: sgRNA retrieval failed — {exc}", file=sys.stderr)
        return 1

    if not raw_guides:
        print(
            f"ERROR: No sgRNA guides found for gene '{target_gene}'. "
            "Check that the gene symbol is in the library (data/sgrna_library.csv).",
            file=sys.stderr,
        )
        return 1

    sgrna_results = _build_sgrna_results(target_gene, raw_guides)

    # ── Stage 2.5: Literature grounding ───────────────────────────────────
    print(f"[2.5/5] Fetching literature for '{target_gene}'…")
    lit_result, literature_text = _fetch_literature(
        target_gene,
        f"{hypothesis.phenotype} {hypothesis.system_context}",
    )

    # ── Stages 3→4: Protocol revision loop ────────────────────────────────
    # Generate a protocol, review it, and if criticals remain feed the review
    # back into the generator so the model can self-correct. Repeat up to
    # MAX_REVISIONS times, then proceed with the best result regardless.
    MAX_REVISIONS = 3
    protocol = None
    review: dict = {}
    prior_review: dict | None = None

    for revision in range(1, MAX_REVISIONS + 1):
        print(f"[3/5] Generating protocol (attempt {revision}/{MAX_REVISIONS})…")
        try:
            protocol, _ = generate_protocol(
                hypothesis,
                sgrna_results,
                literature=literature_text,
                prior_review=prior_review,
            )
        except EnvironmentError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"ERROR: Protocol generation failed — {exc}", file=sys.stderr)
            return 1

        print(f"[4/5] Reviewing protocol (attempt {revision}/{MAX_REVISIONS})…")
        try:
            review = review_protocol(hypothesis, protocol)
        except EnvironmentError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"ERROR: Protocol review failed — {exc}", file=sys.stderr)
            return 1

        criticals = [f for f in review["validation_flags"] if f["severity"] == "critical"]
        verdict = review["overall_verdict"]

        if not criticals or verdict == "approve":
            print(f"  ✓ Protocol accepted (verdict: {verdict}, {len(criticals)} critical(s))")
            break

        if revision < MAX_REVISIONS:
            print(f"  ↻ {len(criticals)} critical(s) found — feeding back to generator…")
            prior_review = review
        else:
            print(f"  ! Max revisions reached — {len(criticals)} critical(s) remain. Proceeding with best attempt.")

    # ── Stage 5: Execution packet ──────────────────────────────────────────
    print("[5/5] Building execution packet…")
    protocol_json = json.loads(protocol.model_dump_json())
    try:
        execution_packet = generate_execution_packet(protocol_json)
    except EnvironmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: Execution planning failed — {exc}", file=sys.stderr)
        return 1

    # ── Output ─────────────────────────────────────────────────────────────
    _print_hypothesis(hypothesis)
    _print_guides(sgrna_results)
    _print_literature_section(lit_result)
    _print_protocol(protocol)
    _print_review_section(review)
    _print_execution_section(execution_packet)

    output_path = _save_output(hypothesis, sgrna_results, lit_result, protocol, review, execution_packet)
    print(f"\n  Output saved → {output_path}")
    print()
    return 0


# ── Output serialization ───────────────────────────────────────────────────

def _save_output(
    hypothesis: ParsedHypothesis,
    sgrna_results: SgRNAResults,
    lit_result: dict | None,
    protocol: KnockoutProtocol,
    review: dict,
    execution_packet: dict,
) -> Path:
    """Serialize full pipeline result to /output/<timestamp>_<gene>.json."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{hypothesis.target_gene}.json"
    output_path = OUTPUT_DIR / filename

    payload = {
        "hypothesis": json.loads(hypothesis.model_dump_json()),
        "sgrna_results": json.loads(sgrna_results.model_dump_json()),
        "literature": lit_result,
        "protocol": json.loads(protocol.model_dump_json()),
        "review": review,
        "execution_packet": execution_packet.get("execution_packet", {}),
    }

    output_path.write_text(json.dumps(payload, indent=2))
    return output_path


# ── CLI ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="autolab-crispr",
        description="AutoLab-CRISPR: AI-assisted CRISPR experimental design pipeline.",
    )
    parser.add_argument(
        "--hypothesis",
        required=True,
        metavar="TEXT",
        help='Free-text biological hypothesis, e.g. "Knocking out TP53 will …"',
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run(args.hypothesis))
