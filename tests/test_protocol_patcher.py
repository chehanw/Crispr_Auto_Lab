"""
Unit tests for agents/protocol_patcher.py.

Coverage:
- apply_patches: each patch category (controls, guide_selection, validation, safety, statistics)
- Idempotency: applying same patch twice does not duplicate
- Unknown category is silently skipped
- Non-patchable flags are excluded
- Original dict is never mutated (immutability)
- print_patches: empty and non-empty
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.protocol_patcher import apply_patches, print_patches


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _base_protocol() -> dict:
    return {
        "gene": "TP53",
        "cell_line": "HEK293",
        "transfection_method": "lipofectamine",
        "selected_sgrna": {"guide_id": "TP53_g1", "sequence": "GCACTTTGATGTCAACAGAT", "gc_content": 0.45},
        "steps": [],
        "total_duration_days": 7.0,
        "expected_efficiency_pct": 75.0,
        "validation_assay": "T7E1 assay",
        "safety_notes": ["Handle under BSL-2 conditions."],
    }


def _flag(category: str, issue: str, severity: str = "critical", patchable: bool = True) -> dict:
    return {
        "severity": severity,
        "category": category,
        "issue": issue,
        "recommendation": "Fix it.",
        "patchable": patchable,
    }


def _review(flags: list[dict]) -> dict:
    return {"validation_flags": flags, "overall_verdict": "revise", "review_summary": "Issues found."}


# ── Immutability ──────────────────────────────────────────────────────────────

class TestImmutability:
    def test_original_protocol_not_mutated(self):
        proto = _base_protocol()
        original_notes = list(proto["safety_notes"])
        review = _review([_flag("controls", "no negative control")])
        apply_patches(proto, review)
        assert proto["safety_notes"] == original_notes

    def test_returns_new_dict(self):
        proto = _base_protocol()
        review = _review([_flag("controls", "no negative control")])
        patched, _ = apply_patches(proto, review)
        assert patched is not proto


# ── Controls patch ────────────────────────────────────────────────────────────

class TestControlsPatch:
    def test_adds_non_targeting_flag_on_negative_control_issue(self):
        proto = _base_protocol()
        review = _review([_flag("controls", "missing negative control")])
        patched, patches = apply_patches(proto, review)
        assert patched["non_targeting_sgRNA_control_recommended"] is True
        assert any("controls" in p for p in patches)

    def test_adds_flag_for_mock_keyword(self):
        proto = _base_protocol()
        review = _review([_flag("controls", "no mock transfection control")])
        patched, patches = apply_patches(proto, review)
        assert patched.get("non_targeting_sgRNA_control_recommended") is True

    def test_idempotent_if_already_set(self):
        proto = {**_base_protocol(), "non_targeting_sgRNA_control_recommended": True}
        review = _review([_flag("controls", "missing negative control")])
        _, patches = apply_patches(proto, review)
        assert patches == []

    def test_unrelated_controls_issue_not_patched(self):
        proto = _base_protocol()
        review = _review([_flag("controls", "no positive control for western")])
        patched, patches = apply_patches(proto, review)
        assert "non_targeting_sgRNA_control_recommended" not in patched
        assert patches == []


# ── Guide selection patch ─────────────────────────────────────────────────────

class TestGuideSelectionPatch:
    def _candidates(self) -> list[dict]:
        return [
            {"guide_id": "TP53_g1", "sgrna_sequence": "GCACTTTGATGTCAACAGAT", "gc_content": 0.45},
            {"guide_id": "TP53_g2", "sgrna_sequence": "ACTTCCTGAAAACAACGTTC", "gc_content": 0.40},
            {"guide_id": "TP53_g3", "sgrna_sequence": "TGTTCCGAGAGCTGAATGAG", "gc_content": 0.50},
        ]

    def test_adds_backup_guides_from_candidates(self):
        proto = _base_protocol()
        review = _review([_flag("guide_selection", "only one sgrna tested")])
        patched, patches = apply_patches(proto, review, self._candidates())
        assert "backup_guides" in patched
        assert len(patched["backup_guides"]) <= 2
        # Selected guide excluded from backups
        ids = [g["guide_id"] for g in patched["backup_guides"]]
        assert "TP53_g1" not in ids
        assert any("guide_selection" in p for p in patches)

    def test_adds_note_when_no_candidates(self):
        proto = _base_protocol()
        review = _review([_flag("guide_selection", "single guide only")])
        patched, patches = apply_patches(proto, review, sgrna_candidates=[])
        assert "backup_guides_note" in patched
        assert patches

    def test_idempotent_if_backup_guides_exist(self):
        proto = {**_base_protocol(), "backup_guides": [{"guide_id": "TP53_g2"}]}
        review = _review([_flag("guide_selection", "only one sgrna")])
        patched, patches = apply_patches(proto, review, self._candidates())
        assert patches == []

    def test_unrelated_guide_issue_not_patched(self):
        proto = _base_protocol()
        review = _review([_flag("guide_selection", "low efficiency score")])
        patched, patches = apply_patches(proto, review, self._candidates())
        assert "backup_guides" not in patched
        assert patches == []


# ── Validation patch ──────────────────────────────────────────────────────────

class TestValidationPatch:
    def test_appends_western_blot_when_missing(self):
        proto = _base_protocol()
        review = _review([_flag("validation", "no western blot confirmation")])
        patched, patches = apply_patches(proto, review)
        assert "Western blot" in patched["validation_assay"]
        assert any("Western blot" in p for p in patches)

    def test_does_not_duplicate_western_blot(self):
        proto = {**_base_protocol(), "validation_assay": "T7E1 assay, Western blot"}
        review = _review([_flag("validation", "need protein confirmation by western blot")])
        patched, patches = apply_patches(proto, review)
        assert patched["validation_assay"].lower().count("western blot") == 1
        assert not any("Western blot" in p for p in patches)

    def test_adds_rescue_recommended(self):
        proto = _base_protocol()
        review = _review([_flag("validation", "no rescue experiment proposed")])
        patched, patches = apply_patches(proto, review)
        assert patched.get("rescue_experiment_recommended") is True
        assert any("rescue" in p for p in patches)

    def test_adds_off_target_recommended(self):
        proto = _base_protocol()
        review = _review([_flag("validation", "off-target sites not assessed")])
        patched, patches = apply_patches(proto, review)
        assert patched.get("off_target_validation_recommended") is True
        assert any("off_target" in p for p in patches)


# ── Safety patch ──────────────────────────────────────────────────────────────

class TestSafetyPatch:
    def test_appends_standard_note_when_weak(self):
        proto = {**_base_protocol(), "safety_notes": ["Use gloves."]}
        review = _review([_flag("safety", "safety notes insufficient")])
        patched, patches = apply_patches(proto, review)
        assert len(patched["safety_notes"]) == 2
        assert any("safety" in p for p in patches)

    def test_idempotent_if_standard_note_present(self):
        standard = (
            "All work must comply with institutional biosafety protocols. "
            "Use appropriate PPE (lab coat, gloves, eye protection) at all times. "
            "Decontaminate all biological waste before disposal."
        )
        proto = {**_base_protocol(), "safety_notes": [standard]}
        review = _review([_flag("safety", "incomplete safety notes")])
        patched, patches = apply_patches(proto, review)
        assert len(patched["safety_notes"]) == 1
        assert patches == []


# ── Statistics patch ──────────────────────────────────────────────────────────

class TestStatisticsPatch:
    def test_adds_statistical_plan_note(self):
        proto = _base_protocol()
        review = _review([_flag("statistics", "no statistical plan")])
        patched, patches = apply_patches(proto, review)
        assert "statistical_plan_note" in patched
        assert any("statistics" in p for p in patches)

    def test_idempotent_if_note_exists(self):
        proto = {**_base_protocol(), "statistical_plan_note": "Already has stats."}
        review = _review([_flag("statistics", "no statistical plan")])
        patched, patches = apply_patches(proto, review)
        assert patched["statistical_plan_note"] == "Already has stats."
        assert patches == []


# ── Non-patchable flags excluded ──────────────────────────────────────────────

class TestNonPatchableExclusion:
    def test_non_patchable_flag_not_applied(self):
        proto = _base_protocol()
        review = _review([_flag("controls", "missing negative control", patchable=False)])
        patched, patches = apply_patches(proto, review)
        assert "non_targeting_sgRNA_control_recommended" not in patched
        assert patches == []


# ── Unknown category silently skipped ────────────────────────────────────────

class TestUnknownCategory:
    def test_unknown_category_no_crash(self):
        proto = _base_protocol()
        review = _review([_flag("feasibility", "some feasibility concern")])
        patched, patches = apply_patches(proto, review)
        # No exception; no unexpected keys added
        assert patches == []


# ── Empty review ─────────────────────────────────────────────────────────────

class TestEmptyReview:
    def test_no_flags_returns_unchanged_copy(self):
        proto = _base_protocol()
        review = _review([])
        patched, patches = apply_patches(proto, review)
        assert patched == proto
        assert patches == []


# ── print_patches ─────────────────────────────────────────────────────────────

class TestPrintPatches:
    def test_empty_prints_no_patches(self, capsys):
        print_patches([])
        out = capsys.readouterr().out
        assert "no patches" in out

    def test_non_empty_prints_each_patch(self, capsys):
        print_patches(["controls: added flag", "safety: appended note"])
        out = capsys.readouterr().out
        assert "controls: added flag" in out
        assert "safety: appended note" in out
