"""
AutoLab-CRISPR — CLI entry point

Usage:
    python main.py --hypothesis "Knocking out TP53 will cause uncontrolled proliferation."

Pipeline (stages run in order):
    1.   parse_hypothesis       → ParsedHypothesis
    1.5. check_feasibility      → FeasibilityFlags  (blocks on critical flags)
    2.   get_guides             → list[dict]  → SgRNAResults
    3.   generate_protocol      → KnockoutProtocol
    4+5. review_protocol + generate_execution_packet → parallel
"""

from __future__ import annotations

import argparse
import json
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ── Project imports ────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent))

from agents.parser import parse_hypothesis
from agents.sgrna_retriever import get_guides
from agents.protocol_generator import generate_protocol
from agents.feasibility_check import check_feasibility, print_feasibility_flags
from agents.reviewer import review_protocol, print_review
from agents.execution_planner import generate_execution_packet, print_execution_packet
from config import TOP_K_GUIDES, OUTPUT_DIR
from models.schemas import KnockoutProtocol, ParsedHypothesis, SgRNACandidate, SgRNAResults


# ── Helpers ────────────────────────────────────────────────────────────────

def _build_sgrna_results(gene: str, raw_guides: list[dict]) -> SgRNAResults:
    """Convert raw dicts from sgrna_retriever into a validated SgRNAResults model."""
    candidates = [
        SgRNACandidate(
            guide_id=g["guide_id"],
            gene=g["gene"],
            sequence=g["sequence"],
            efficiency_score=g["efficiency_score"],
            off_target_score=g["off_target_score"],
            pam=g.get("pam", "NGG"),
            chromosome=g.get("chromosome"),
            position=g.get("position"),
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

    # ── Stage 3: Generate protocol ─────────────────────────────────────────
    print("[3/5] Generating knockout protocol…")
    try:
        protocol, _ = generate_protocol(hypothesis, sgrna_results)
    except EnvironmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: Protocol generation failed — {exc}", file=sys.stderr)
        return 1

    # ── Stages 4 + 5: Review and execution plan (parallel) ────────────────
    print("[4+5/5] Reviewing protocol and building execution packet (parallel)…")
    protocol_json = json.loads(protocol.model_dump_json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_review = pool.submit(review_protocol, hypothesis, protocol)
        f_packet = pool.submit(generate_execution_packet, protocol_json)

        try:
            review = f_review.result()
        except EnvironmentError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"ERROR: Protocol review failed — {exc}", file=sys.stderr)
            return 1

        try:
            execution_packet = f_packet.result()
        except EnvironmentError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"ERROR: Execution planning failed — {exc}", file=sys.stderr)
            return 1

    # ── Output ─────────────────────────────────────────────────────────────
    _print_hypothesis(hypothesis)
    _print_guides(sgrna_results)
    _print_protocol(protocol)
    _print_review_section(review)
    _print_execution_section(execution_packet)

    output_path = _save_output(hypothesis, sgrna_results, protocol, review, execution_packet)
    print(f"\n  Output saved → {output_path}")
    print()
    return 0


# ── Output serialization ───────────────────────────────────────────────────

def _save_output(
    hypothesis: ParsedHypothesis,
    sgrna_results: SgRNAResults,
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
