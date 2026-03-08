"""
Module 2: sgRNA Lookup
Looks up candidate guide RNAs for a given gene symbol from a local CSV library.

Expected CSV columns:
    guide_id        - unique identifier (e.g. "TP53_g1")
    gene            - gene symbol (e.g. "TP53")
    sequence        - 20-nt sgRNA sequence
    efficiency_score  - on-target score 0.0–1.0
    off_target_score  - off-target risk score 0.0–1.0 (lower is better)
    pam             - PAM sequence (e.g. "NGG")
    chromosome      - genomic location chromosome
    position        - genomic coordinate

Example CSV rows:
    guide_id,gene,sequence,efficiency_score,off_target_score,pam,chromosome,position
    TP53_g1,TP53,GCACTTTGATGTCAACAGAT,0.87,0.12,NGG,chr17,7676520
    KRAS_g1,KRAS,GTAGTTGGAGCTGGTGGCGT,0.93,0.05,NGG,chr12,25245274
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GuideRNA:
    guide_id: str
    gene: str
    sequence: str
    efficiency_score: float
    off_target_score: float
    pam: str
    chromosome: str
    position: int

    def __str__(self) -> str:
        return (
            f"{self.guide_id}: {self.sequence} [{self.pam}] "
            f"eff={self.efficiency_score:.2f} off_target={self.off_target_score:.2f} "
            f"@ {self.chromosome}:{self.position}"
        )


# ---------------------------------------------------------------------------
# Required columns in the CSV
# ---------------------------------------------------------------------------

_REQUIRED_COLUMNS = {
    "guide_id", "gene", "sequence",
    "efficiency_score", "off_target_score", "pam",
    "chromosome", "position",
}


# ---------------------------------------------------------------------------
# Core lookup
# ---------------------------------------------------------------------------

def load_library(csv_path: str | Path) -> list[GuideRNA]:
    """Parse the CSV library and return all guide RNAs.

    Raises:
        FileNotFoundError: if the CSV path does not exist.
        ValueError: if required columns are missing or a row is malformed.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"sgRNA library not found: {path}")

    guides: list[GuideRNA] = []

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no header row.")

        missing = _REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

        for line_num, row in enumerate(reader, start=2):
            try:
                guide = GuideRNA(
                    guide_id=row["guide_id"].strip(),
                    gene=row["gene"].strip().upper(),
                    sequence=row["sequence"].strip().upper(),
                    efficiency_score=float(row["efficiency_score"]),
                    off_target_score=float(row["off_target_score"]),
                    pam=row["pam"].strip().upper(),
                    chromosome=row["chromosome"].strip(),
                    position=int(row["position"]),
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Malformed row at line {line_num}: {exc}") from exc

            guides.append(guide)

    return guides


def lookup_guides(
    gene_symbol: str,
    csv_path: str | Path,
    *,
    min_efficiency: float = 0.0,
    max_off_target: float = 1.0,
    sort_by: str = "efficiency_score",
) -> list[GuideRNA]:
    """Return candidate sgRNAs for *gene_symbol* from the library CSV.

    Args:
        gene_symbol:    Target gene (case-insensitive).
        csv_path:       Path to the sgRNA library CSV.
        min_efficiency: Discard guides below this on-target score (0–1).
        max_off_target: Discard guides above this off-target risk (0–1).
        sort_by:        Column to sort results by; prefix with "-" to reverse
                        (e.g. "-efficiency_score" = highest first).

    Returns:
        List of matching GuideRNA objects, sorted as requested.

    Raises:
        FileNotFoundError: if csv_path does not exist.
        ValueError: if csv_path is malformed or sort_by is invalid.
    """
    if not gene_symbol or not gene_symbol.strip():
        raise ValueError("gene_symbol must be a non-empty string.")

    target = gene_symbol.strip().upper()
    all_guides = load_library(csv_path)

    candidates = [
        g for g in all_guides
        if g.gene == target
        and g.efficiency_score >= min_efficiency
        and g.off_target_score <= max_off_target
    ]

    descending = sort_by.startswith("-")
    key_name = sort_by.lstrip("-")

    valid_keys = {"efficiency_score", "off_target_score", "position", "guide_id"}
    if key_name not in valid_keys:
        raise ValueError(f"sort_by must be one of {sorted(valid_keys)}, got '{key_name}'.")

    candidates.sort(key=lambda g: getattr(g, key_name), reverse=descending)
    return candidates
