"""Tests for utils/sgrna_lookup.py (Module 2)."""

import csv
import tempfile
from pathlib import Path

import pytest

from utils.sgrna_lookup import GuideRNA, load_library, lookup_guides

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HEADER = [
    "guide_id", "gene", "sequence",
    "efficiency_score", "off_target_score", "pam",
    "chromosome", "position",
]

_ROWS = [
    ["TP53_g1", "TP53", "GCACTTTGATGTCAACAGAT", "0.87", "0.12", "NGG", "chr17", "7676520"],
    ["TP53_g2", "TP53", "ACTTCCTGAAAACAACGTTC", "0.81", "0.18", "NGG", "chr17", "7676154"],
    ["TP53_g3", "TP53", "GTGTTTGTGCCTGTCCTGGG", "0.60", "0.35", "NGG", "chr17", "7669609"],
    ["KRAS_g1", "KRAS", "GTAGTTGGAGCTGGTGGCGT", "0.93", "0.05", "NGG", "chr12", "25245274"],
    ["KRAS_g2", "KRAS", "TTGGAGCTGGTGGCGTAGGC", "0.88", "0.11", "NGG", "chr12", "25245271"],
]


def _make_csv(rows: list[list[str]], header: list[str] = _HEADER) -> Path:
    """Write a temp CSV and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    )
    writer = csv.writer(tmp)
    writer.writerow(header)
    writer.writerows(rows)
    tmp.flush()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# load_library
# ---------------------------------------------------------------------------

class TestLoadLibrary:
    def test_loads_all_rows(self):
        path = _make_csv(_ROWS)
        guides = load_library(path)
        assert len(guides) == len(_ROWS)

    def test_types_are_correct(self):
        path = _make_csv(_ROWS[:1])
        guide = load_library(path)[0]
        assert isinstance(guide, GuideRNA)
        assert isinstance(guide.efficiency_score, float)
        assert isinstance(guide.off_target_score, float)
        assert isinstance(guide.position, int)

    def test_gene_normalized_to_uppercase(self):
        row = ["tp53_g1", "tp53", "GCACTTTGATGTCAACAGAT", "0.87", "0.12", "NGG", "chr17", "7676520"]
        path = _make_csv([row])
        guide = load_library(path)[0]
        assert guide.gene == "TP53"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_library("/nonexistent/path/library.csv")

    def test_missing_column_raises(self):
        bad_header = [c for c in _HEADER if c != "sequence"]
        path = _make_csv(_ROWS[:1], header=bad_header)
        with pytest.raises(ValueError, match="missing required columns"):
            load_library(path)

    def test_malformed_numeric_raises(self):
        bad_row = ["TP53_g1", "TP53", "GCACTTTGATGTCAACAGAT", "NOT_A_FLOAT", "0.12", "NGG", "chr17", "7676520"]
        path = _make_csv([bad_row])
        with pytest.raises(ValueError, match="Malformed row"):
            load_library(path)


# ---------------------------------------------------------------------------
# lookup_guides
# ---------------------------------------------------------------------------

class TestLookupGuides:
    def setup_method(self):
        self.csv_path = _make_csv(_ROWS)

    def test_returns_only_matching_gene(self):
        results = lookup_guides("TP53", self.csv_path)
        assert all(g.gene == "TP53" for g in results)
        assert len(results) == 3

    def test_case_insensitive_gene_symbol(self):
        lower = lookup_guides("tp53", self.csv_path)
        upper = lookup_guides("TP53", self.csv_path)
        assert len(lower) == len(upper)

    def test_unknown_gene_returns_empty(self):
        results = lookup_guides("BRCA2", self.csv_path)
        assert results == []

    def test_min_efficiency_filter(self):
        results = lookup_guides("TP53", self.csv_path, min_efficiency=0.80)
        assert all(g.efficiency_score >= 0.80 for g in results)
        assert len(results) == 2  # g1=0.87, g2=0.81 pass; g3=0.60 excluded

    def test_max_off_target_filter(self):
        results = lookup_guides("TP53", self.csv_path, max_off_target=0.20)
        assert all(g.off_target_score <= 0.20 for g in results)

    def test_default_sort_ascending_efficiency(self):
        results = lookup_guides("TP53", self.csv_path, sort_by="efficiency_score")
        scores = [g.efficiency_score for g in results]
        assert scores == sorted(scores)

    def test_descending_sort(self):
        results = lookup_guides("TP53", self.csv_path, sort_by="-efficiency_score")
        scores = [g.efficiency_score for g in results]
        assert scores == sorted(scores, reverse=True)

    def test_invalid_sort_key_raises(self):
        with pytest.raises(ValueError, match="sort_by"):
            lookup_guides("TP53", self.csv_path, sort_by="nonexistent_col")

    def test_empty_gene_symbol_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            lookup_guides("", self.csv_path)

    def test_real_library_csv(self):
        """Smoke test against the actual data/sgrna_library.csv."""
        real_csv = Path(__file__).parent.parent / "data" / "sgrna_library.csv"
        if not real_csv.exists():
            pytest.skip("data/sgrna_library.csv not present")
        results = lookup_guides("KRAS", real_csv, sort_by="-efficiency_score")
        assert len(results) > 0
        assert results[0].efficiency_score >= results[-1].efficiency_score
