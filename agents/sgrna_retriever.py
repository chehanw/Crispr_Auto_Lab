"""
sgRNA Retriever (Stage 2)

Input:  gene symbol (str)
Output: list of guide dicts ranked by efficiency DESC, off_target ASC

Pure Python — no LLM calls.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
LIBRARY_PATH = ROOT_DIR / "data" / "sgrna_library.csv"

REQUIRED_COLUMNS = {"guide_id", "gene", "sequence", "efficiency_score", "off_target_score"}


def get_guides(gene_symbol: str, max_guides: int = 5) -> list[dict]:
    """
    Return up to max_guides sgRNA candidates for the given gene.

    Args:
        gene_symbol: Gene name — normalized to uppercase internally.
        max_guides:  Maximum number of guides to return.

    Returns:
        List of guide dicts sorted by efficiency DESC, off_target ASC.
        Empty list if gene not found or library missing.

    Raises:
        ValueError: If gene_symbol is empty or max_guides < 1.
        RuntimeError: If the CSV is missing required columns.
    """
    if not gene_symbol or not gene_symbol.strip():
        raise ValueError("gene_symbol must be a non-empty string.")
    if max_guides < 1:
        raise ValueError("max_guides must be at least 1.")

    gene = gene_symbol.strip().upper()
    rows = _load_library()

    candidates = [r for r in rows if r["gene"].upper() == gene]
    ranked = sorted(candidates, key=lambda r: (-r["efficiency_score"], r["off_target_score"]))
    return ranked[:max_guides]


# ── Internal ───────────────────────────────────────────────────────────────

def _load_library(path: Path = LIBRARY_PATH) -> list[dict]:
    """Read CSV and return typed rows. Raises RuntimeError on schema mismatch."""
    if not path.exists():
        raise RuntimeError(f"sgRNA library not found: {path}")

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise RuntimeError(f"CSV missing required columns: {missing}")

        rows = []
        for i, row in enumerate(reader, start=2):  # line 1 = header
            try:
                rows.append({
                    **row,
                    "efficiency_score": float(row["efficiency_score"]),
                    "off_target_score": float(row["off_target_score"]),
                    "position": int(row["position"]) if row.get("position") else None,
                })
            except (ValueError, KeyError) as exc:
                raise RuntimeError(f"Bad data on CSV line {i}: {exc}") from exc

    return rows


# ── Test Harness ───────────────────────────────────────────────────────────

TEST_CASES = [
    {"gene": "TP53",  "max_guides": 3,  "expect_results": True},
    {"gene": "tp53",  "max_guides": 3,  "expect_results": True},   # lowercase
    {"gene": "KRAS",  "max_guides": 2,  "expect_results": True},
    {"gene": "BRCA1", "max_guides": 5,  "expect_results": True},
    {"gene": "FAKE1", "max_guides": 3,  "expect_results": False},  # unknown gene
]


def _run_tests() -> None:
    print("=" * 55)
    print("AutoLab-CRISPR  |  sgRNA Retriever  |  Test Harness")
    print("=" * 55)

    passed = failed = 0

    for i, case in enumerate(TEST_CASES, 1):
        gene, max_g, expect = case["gene"], case["max_guides"], case["expect_results"]
        print(f"\n[{i}/{len(TEST_CASES)}] get_guides({gene!r}, max={max_g})")
        try:
            guides = get_guides(gene, max_guides=max_g)
            got_results = len(guides) > 0

            if got_results != expect:
                raise AssertionError(f"Expected results={expect}, got {len(guides)} guides")

            if guides:
                for g in guides:
                    print(f"  {g['guide_id']:<12} eff={g['efficiency_score']:.2f}  off={g['off_target_score']:.2f}  seq={g['sequence']}")
                # Verify sort order
                effs = [g["efficiency_score"] for g in guides]
                assert effs == sorted(effs, reverse=True), "Guides not sorted by efficiency DESC"
            else:
                print("  (no guides found — expected)")

            print(f"  PASS")
            passed += 1
        except Exception as exc:
            print(f"  FAIL: {exc}")
            failed += 1

    print("\n" + "=" * 55)
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES)}")
    print("=" * 55)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        gene_arg = sys.argv[1]
        max_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        results = get_guides(gene_arg, max_guides=max_arg)
        if results:
            for g in results:
                print(g)
        else:
            print(f"No guides found for '{gene_arg}'")
    else:
        _run_tests()
