"""
sgRNA Retriever (Stage 2) — Brunello Library

Looks up sgRNA candidates from the Brunello genome-wide CRISPR knockout library
(Doench et al., Nature Biotechnology 2016).

Library: broadgpp-brunello-library-corrected.txt
  Columns: sgRNAID | Seq | gene
  Guides:  ~77,441 SpCas9 guides targeting ~19,000 human genes

The dataset is loaded once at import time and cached in memory.
All subsequent queries are pure in-memory lookups — no file I/O per call.
"""

from __future__ import annotations

import csv
import sys
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
BRUNELLO_PATH = ROOT_DIR / "data" / "broadgpp-brunello-library-corrected.txt"

# SpCas9 PAM — all Brunello guides target NGG sites
PAM_SEQUENCE = "NGG"

# Column names in the raw file
_COL_ID   = "sgRNAID"
_COL_SEQ  = "Seq"
_COL_GENE = "gene"


# ── Dataset loading (cached) ───────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_library() -> dict[str, list[dict]]:
    """
    Load and normalize the Brunello library. Called once; result is cached.

    Returns:
        Dict mapping uppercase gene_symbol → list of guide dicts.

    Raises:
        RuntimeError: If the file is missing or malformed.
    """
    if not BRUNELLO_PATH.exists():
        raise RuntimeError(f"Brunello library not found: {BRUNELLO_PATH}")

    index: dict[str, list[dict]] = {}
    skipped = 0

    with BRUNELLO_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")

        required = {_COL_ID, _COL_SEQ, _COL_GENE}
        if not required.issubset(set(reader.fieldnames or [])):
            raise RuntimeError(
                f"Brunello file missing required columns. "
                f"Expected {required}, got {reader.fieldnames}"
            )

        for row in reader:
            gene   = row[_COL_GENE].strip().upper()
            seq    = row[_COL_SEQ].strip().upper()
            gid    = row[_COL_ID].strip()

            if not gene or not seq or len(seq) != 20:
                skipped += 1
                continue

            guide = {
                "guide_id":       gid,
                "sgrna_sequence": seq,
                "gene_symbol":    gene,
                "source_library": "Brunello",
                "gc_content":     _gc_content(seq),
                "pam_sequence":   PAM_SEQUENCE,
                "pam_valid":      True,  # All Brunello guides target NGG
            }

            index.setdefault(gene, []).append(guide)

    if not index:
        raise RuntimeError("Brunello library loaded but contains no valid guides.")

    return index


def _gc_content(seq: str) -> float:
    """Return GC content as a fraction (0.0–1.0)."""
    if not seq:
        return 0.0
    gc = sum(1 for nt in seq.upper() if nt in ("G", "C"))
    return round(gc / len(seq), 4)


def _rank_guides(guides: list[dict]) -> list[dict]:
    """
    Rank guides by GC content proximity to 0.50 (optimal for SpCas9 activity).
    Guides with GC between 40–70% are generally preferred.
    """
    return sorted(guides, key=lambda g: abs(g["gc_content"] - 0.50))


# ── Public API ─────────────────────────────────────────────────────────────

def get_guides(gene_symbol: str, max_guides: int = 5) -> list[dict]:
    """
    Return up to max_guides sgRNA candidates for a gene from the Brunello library.

    Args:
        gene_symbol: Gene name — normalized to uppercase internally.
        max_guides:  Maximum number of guides to return (default 5).

    Returns:
        List of guide dicts with keys:
            guide_id, sgrna_sequence, gene_symbol, source_library,
            gc_content, pam_sequence, pam_valid
        Empty list if gene not found in library.

    Raises:
        ValueError:  If gene_symbol is empty or max_guides < 1.
        RuntimeError: If the Brunello file is missing or malformed.
    """
    if not gene_symbol or not gene_symbol.strip():
        raise ValueError("gene_symbol must be a non-empty string.")
    if max_guides < 1:
        raise ValueError("max_guides must be at least 1.")

    library = _load_library()
    gene = gene_symbol.strip().upper()
    guides = library.get(gene, [])
    ranked = _rank_guides(guides)
    return ranked[:max_guides]


def gene_in_library(gene_symbol: str) -> bool:
    """Return True if the gene has any guides in the Brunello library."""
    library = _load_library()
    return gene_symbol.strip().upper() in library


# ── Test Harness ───────────────────────────────────────────────────────────

TEST_CASES = [
    {"gene": "TP53",  "max_guides": 4,  "expect_results": True},
    {"gene": "tp53",  "max_guides": 4,  "expect_results": True},   # lowercase
    {"gene": "BRCA1", "max_guides": 3,  "expect_results": True},
    {"gene": "KRAS",  "max_guides": 5,  "expect_results": True},
    {"gene": "EGFR",  "max_guides": 3,  "expect_results": True},
    {"gene": "FAKE1", "max_guides": 3,  "expect_results": False},  # not in library
]


def _run_tests() -> None:
    print("=" * 65)
    print("AutoLab-CRISPR  |  sgRNA Retriever (Brunello)  |  Test Harness")
    print("=" * 65)
    print("Loading Brunello library…", end=" ", flush=True)

    try:
        lib = _load_library()
        total_genes  = len(lib)
        total_guides = sum(len(v) for v in lib.values())
        print(f"OK  ({total_genes:,} genes, {total_guides:,} guides)")
    except RuntimeError as exc:
        print(f"FAIL — {exc}")
        sys.exit(1)

    passed = failed = 0

    for i, case in enumerate(TEST_CASES, 1):
        gene, max_g, expect = case["gene"], case["max_guides"], case["expect_results"]
        print(f"\n[{i}/{len(TEST_CASES)}] get_guides({gene!r}, max={max_g})")
        try:
            guides = get_guides(gene, max_guides=max_g)
            got_results = len(guides) > 0

            if got_results != expect:
                raise AssertionError(f"Expected results={expect}, got {len(guides)} guide(s)")

            if guides:
                for g in guides:
                    pam_ok = "✓" if g["pam_valid"] else "✗"
                    print(
                        f"  {g['guide_id'][:35]:<35}  "
                        f"seq={g['sgrna_sequence']}  "
                        f"gc={g['gc_content']:.2f}  "
                        f"pam={g['pam_sequence']} {pam_ok}"
                    )
                gcs = [g["gc_content"] for g in guides]
                assert all(0.0 <= gc <= 1.0 for gc in gcs), "GC content out of range"
            else:
                print("  (no guides found — expected)")

            print("  PASS")
            passed += 1
        except Exception as exc:
            print(f"  FAIL: {exc}")
            failed += 1

    print("\n" + "=" * 65)
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES)}")
    print("=" * 65)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        gene_arg = sys.argv[1]
        max_arg  = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        results  = get_guides(gene_arg, max_guides=max_arg)
        if results:
            for g in results:
                print(g)
        else:
            print(f"No sgRNA guides found in Brunello library for '{gene_arg}'")
    else:
        _run_tests()
