"""
Protocol Patcher (Stage 3.5 — local patch pass)

Applies deterministic, local fixes to a protocol JSON based on reviewer flags
that are marked patchable=true. No LLM calls — all logic is rule-based.

Input:
    protocol_json  — dict from KnockoutProtocol.model_dump()
    review         — dict from reviewer (validation_flags with patchable field)
    sgrna_candidates — optional list of raw Brunello guide dicts for backup guides

Output:
    (patched_protocol_json, patches_applied)
    patches_applied is a list of human-readable strings describing what changed.

Rules (one per patch type):
    controls      → add non_targeting_sgRNA_control_recommended flag
    guide_selection (single guide) → add backup_guides list from candidates
    validation (western blot)  → append "Western blot" to validation_assay
    validation (rescue)        → add rescue_experiment_recommended flag
    validation (off-target)    → add off_target_validation_recommended flag
    safety (weak notes)        → append standard BSL-2 note if absent
    statistics                 → add statistical_plan_note
"""

from __future__ import annotations

import copy

# ── Standard safety note appended when reviewer flags weak safety coverage ─

_STANDARD_SAFETY_NOTE = (
    "All work must comply with institutional biosafety protocols. "
    "Use appropriate PPE (lab coat, gloves, eye protection) at all times. "
    "Decontaminate all biological waste before disposal."
)


# ── Public API ─────────────────────────────────────────────────────────────

def apply_patches(
    protocol_json: dict,
    review: dict,
    sgrna_candidates: list[dict] | None = None,
) -> tuple[dict, list[str]]:
    """
    Apply all patchable reviewer flags to the protocol dict.

    Args:
        protocol_json:    Raw dict (from KnockoutProtocol.model_dump_json()).
        review:           Reviewer output dict with validation_flags.
        sgrna_candidates: Optional Brunello guide dicts for backup guide patch.

    Returns:
        (patched_json, patches_applied)
        patched_json     — new dict (original is never mutated)
        patches_applied  — list of description strings, one per patch applied
    """
    protocol = copy.deepcopy(protocol_json)
    patches: list[str] = []

    patchable_flags = [
        f for f in review.get("validation_flags", [])
        if f.get("patchable", True)
    ]

    for flag in patchable_flags:
        category = flag.get("category", "")
        issue    = flag.get("issue", "").lower()

        if category == "controls":
            _patch_controls(protocol, issue, patches)

        elif category == "guide_selection":
            _patch_guide_selection(protocol, issue, sgrna_candidates, patches)

        elif category == "validation":
            _patch_validation(protocol, issue, patches)

        elif category == "safety":
            _patch_safety(protocol, patches)

        elif category == "statistics":
            _patch_statistics(protocol, issue, patches)

    return protocol, patches


# ── Patch rules ────────────────────────────────────────────────────────────

def _patch_controls(protocol: dict, issue: str, patches: list[str]) -> None:
    """Add non-targeting sgRNA control recommendation if flagged missing."""
    if protocol.get("non_targeting_sgRNA_control_recommended"):
        return  # Already patched
    if any(kw in issue for kw in ("non-targeting", "negative control", "mock", "scramble")):
        protocol["non_targeting_sgRNA_control_recommended"] = True
        patches.append(
            "controls: added non_targeting_sgRNA_control_recommended=true "
            "(non-targeting sgRNA control flagged as missing)"
        )


def _patch_guide_selection(
    protocol: dict,
    issue: str,
    candidates: list[dict] | None,
    patches: list[str],
) -> None:
    """Add backup guides if reviewer flags single-guide risk."""
    if not any(kw in issue for kw in ("one sgrna", "single guide", "single sgrna", "only one")):
        return
    if protocol.get("backup_guides"):
        return  # Already patched

    # Use extra candidates (excluding the one already selected)
    selected_id = protocol.get("selected_sgrna", {}).get("guide_id", "")
    backups = [
        {"guide_id": g["guide_id"], "sequence": g["sgrna_sequence"], "gc_content": g["gc_content"]}
        for g in (candidates or [])
        if g["guide_id"] != selected_id
    ][:2]  # Max 2 backups

    if backups:
        protocol["backup_guides"] = backups
        ids = ", ".join(g["guide_id"] for g in backups)
        patches.append(f"guide_selection: added backup_guides [{ids}] for independent validation")
    else:
        protocol["backup_guides_note"] = (
            "Reviewer recommends ≥2 independent sgRNAs. "
            "Select additional guides from the Brunello library targeting a different exon."
        )
        patches.append("guide_selection: added backup_guides_note (no additional candidates available)")


def _patch_validation(protocol: dict, issue: str, patches: list[str]) -> None:
    """Append missing validation methods to validation_assay string."""
    current = protocol.get("validation_assay", "")

    if any(kw in issue for kw in ("western blot", "western", "protein")):
        if "western blot" not in current.lower():
            protocol["validation_assay"] = current + ", Western blot"
            patches.append("validation: appended 'Western blot' to validation_assay")

    if any(kw in issue for kw in ("rescue", "reintroduc", "re-express")):
        if not protocol.get("rescue_experiment_recommended"):
            protocol["rescue_experiment_recommended"] = True
            patches.append(
                "validation: added rescue_experiment_recommended=true "
                "(re-expression of WT gene to confirm phenotype specificity)"
            )

    if any(kw in issue for kw in ("off-target", "off target", "specificity")):
        if not protocol.get("off_target_validation_recommended"):
            protocol["off_target_validation_recommended"] = True
            patches.append(
                "validation: added off_target_validation_recommended=true "
                "(GUIDE-seq or targeted deep-seq at predicted off-target sites)"
            )


def _patch_safety(protocol: dict, patches: list[str]) -> None:
    """Append standard safety note if existing notes are weak."""
    notes = protocol.get("safety_notes", [])
    if not any(_STANDARD_SAFETY_NOTE[:30].lower() in n.lower() for n in notes):
        protocol["safety_notes"] = notes + [_STANDARD_SAFETY_NOTE]
        patches.append("safety: appended standard biosafety compliance note")


def _patch_statistics(protocol: dict, issue: str, patches: list[str]) -> None:
    """Add a statistical plan note if flagged missing."""
    if protocol.get("statistical_plan_note"):
        return
    protocol["statistical_plan_note"] = (
        "Use minimum n=3 independent biological replicates per condition. "
        "Apply unpaired t-test or one-way ANOVA with post-hoc correction (α=0.05). "
        "Report mean ± SEM. Pre-register analysis plan before unblinding."
    )
    patches.append("statistics: added statistical_plan_note (n=3, α=0.05, t-test/ANOVA)")


# ── Display ────────────────────────────────────────────────────────────────

def print_patches(patches: list[str]) -> None:
    if not patches:
        print("  (no patches applied)")
        return
    for p in patches:
        print(f"    [patch] {p}")
