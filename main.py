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
import re
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
from agents.literature_analyst import analyze_literature, print_literature_insights
from agents.protocol_patcher import apply_patches, print_patches
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

    # ── Stage 3: Generate protocol ─────────────────────────────────────────
    print("[3/5] Generating protocol…")
    try:
        protocol, _ = generate_protocol(
            hypothesis, sgrna_results, literature=literature_text,
        )
    except EnvironmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: Protocol generation failed — {exc}", file=sys.stderr)
        return 1

    # ── Stages 4 + 5: Review + execution packet in parallel ───────────────
    # review_protocol and generate_execution_packet run simultaneously.
    #
    # Three outcomes after review:
    #   accepted       → speculative exec_packet is used directly  (~15s saved)
    #   patchable      → local patches applied (ms), exec_packet rerun on patched JSON
    #   non-patchable  → regenerate + re-review (sequential), exec_packet rerun on result
    #
    # In all failure paths the speculative exec_packet thread finishes naturally
    # when the ThreadPoolExecutor context manager exits; its result is discarded.
    protocol_json = json.loads(protocol.model_dump_json())
    patches_applied: list[str] = []
    execution_packet: dict = {}
    got_speculative_packet = False

    print("[4+5/5] Reviewing protocol and building execution packet in parallel…")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_review = pool.submit(review_protocol, hypothesis, protocol)
        f_packet = pool.submit(generate_execution_packet, protocol_json)

        # Wait for review; f_packet runs concurrently in background.
        try:
            review = f_review.result()
        except (EnvironmentError, ValueError) as exc:
            print(f"ERROR: Protocol review failed — {exc}", file=sys.stderr)
            return 1

        criticals    = [f for f in review["validation_flags"] if f["severity"] == "critical"]
        non_patchable = [f for f in criticals if not f.get("patchable", True)]

        if non_patchable:
            # Structural flaw: regenerate then re-review (sequential inside the with block).
            # Speculative f_packet runs to completion on __exit__ but is discarded.
            print(f"  ↻ {len(non_patchable)} non-patchable critical(s) — regenerating protocol…")
            try:
                protocol, _ = generate_protocol(
                    hypothesis, sgrna_results,
                    literature=literature_text,
                    prior_review=review,
                )
                protocol_json = json.loads(protocol.model_dump_json())
                review = review_protocol(hypothesis, protocol)
                criticals = [f for f in review["validation_flags"] if f["severity"] == "critical"]
                print(f"  ✓ Regenerated (verdict: {review['overall_verdict']}, {len(criticals)} critical(s))")
            except (EnvironmentError, ValueError) as exc:
                print(f"  ! Regeneration failed ({exc}) — proceeding with original.", file=sys.stderr)

        elif criticals:
            # All patchable: fix locally (ms), then rerun exec_packet on the patched JSON.
            # Speculative f_packet is discarded since the protocol changed.
            print(f"  [patch] {len(criticals)} patchable critical(s) — applying local patches…")
            protocol_json, patches_applied = apply_patches(protocol_json, review, raw_guides)
            print_patches(patches_applied)

        else:
            # Clean pass: collect the speculatively computed execution packet directly.
            print(f"  ✓ Protocol accepted (verdict: {review['overall_verdict']}, 0 critical(s))")
            try:
                execution_packet = f_packet.result()
                got_speculative_packet = True
            except (EnvironmentError, ValueError) as exc:
                print(f"ERROR: Execution planning failed — {exc}", file=sys.stderr)
                return 1
        # ThreadPoolExecutor.__exit__ waits for f_packet before continuing.

    # ── Stage 5: Execution packet (only if speculative result was not usable) ──
    if not got_speculative_packet:
        print("[5/5] Building execution packet for revised protocol…")
        try:
            execution_packet = generate_execution_packet(protocol_json)
        except (EnvironmentError, ValueError) as exc:
            print(f"ERROR: Execution planning failed — {exc}", file=sys.stderr)
            return 1

    # ── Output ─────────────────────────────────────────────────────────────
    _print_hypothesis(hypothesis)
    _print_guides(sgrna_results)
    _print_literature_section(lit_result)
    _print_protocol(protocol)
    _print_review_section(review)
    if patches_applied:
        _print_section("4.5. Local Patches Applied")
        print_patches(patches_applied)
    _print_execution_section(execution_packet)

    output_path = _save_output(hypothesis, sgrna_results, lit_result, protocol, review, patches_applied, execution_packet)
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
    patches_applied: list[str],
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
        "patches_applied": patches_applied,
        "execution_packet": execution_packet.get("execution_packet", {}),
    }

    output_path.write_text(json.dumps(payload, indent=2))
    return output_path


# ── Cache mode ─────────────────────────────────────────────────────────────

def _find_cache_file(gene: str | None, explicit_path: str | None) -> Path | None:
    """
    Resolve a cache file path.
    - explicit_path set → use that file directly.
    - gene set → find most recent output file for that gene.
    - neither → find most recent output file overall.
    """
    if explicit_path:
        p = Path(explicit_path)
        return p if p.exists() else None

    candidates = sorted(OUTPUT_DIR.glob("*.json"), reverse=True)  # newest first
    if gene:
        gene_upper = gene.upper()
        candidates = [p for p in candidates if gene_upper in p.name.upper()]
    return candidates[0] if candidates else None


def run_from_cache(cache_path: Path) -> int:
    """Display a previously saved pipeline result. No API calls."""
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Could not read cache file — {exc}", file=sys.stderr)
        return 1

    print(f"\n  [cache] Loading from {cache_path.name}\n")

    # Reconstruct display objects from raw dicts
    try:
        hypothesis  = ParsedHypothesis(**payload["hypothesis"])
        sgrna_data  = payload["sgrna_results"]
        candidates  = [SgRNACandidate(**c) for c in sgrna_data["candidates"]]
        sgrna_results = SgRNAResults(gene=sgrna_data["gene"], candidates=candidates)
        lit_result    = payload.get("literature")
        protocol      = KnockoutProtocol(**payload["protocol"])
        review        = payload["review"]
        patches       = payload.get("patches_applied", [])
        exec_packet   = {"execution_packet": payload["execution_packet"]}
    except Exception as exc:
        print(f"ERROR: Cache file is malformed — {exc}", file=sys.stderr)
        return 1

    _print_hypothesis(hypothesis)
    _print_guides(sgrna_results)
    _print_literature_section(lit_result)
    _print_protocol(protocol)
    _print_review_section(review)
    if patches:
        _print_section("4.5. Local Patches Applied")
        print_patches(patches)
    _print_execution_section(exec_packet)
    print(f"\n  [cache] Source: {cache_path}\n")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="autolab-crispr",
        description="AutoLab-CRISPR: AI-assisted CRISPR experimental design pipeline.",
    )
    parser.add_argument(
        "--hypothesis",
        required=False,
        metavar="TEXT",
        help='Free-text biological hypothesis, e.g. "Knocking out TP53 will …"',
    )
    parser.add_argument(
        "--from-cache",
        nargs="?",
        const="",          # flag present with no value → auto-find
        metavar="FILE",
        dest="from_cache",
        help="Skip pipeline and display a cached result. "
             "Optionally provide a path to a specific output JSON; "
             "omit to auto-load the most recent file for the gene in --hypothesis.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.from_cache is not None:
        # Cache mode — resolve gene from hypothesis if provided
        gene = None
        if args.hypothesis:
            # Quick extraction without an LLM call: look for uppercase gene token
            tokens = re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", args.hypothesis)
            gene = tokens[0] if tokens else None

        explicit = args.from_cache if args.from_cache else None
        cache_path = _find_cache_file(gene, explicit)

        if cache_path is None:
            print("ERROR: No cache file found. Run without --from-cache first.", file=sys.stderr)
            sys.exit(1)

        sys.exit(run_from_cache(cache_path))

    if not args.hypothesis:
        print("ERROR: --hypothesis is required when not using --from-cache.", file=sys.stderr)
        sys.exit(1)

    sys.exit(run(args.hypothesis))
