"""
Experiment Confidence Evaluation (Stage 4.5)

Computes a 0–100 score summarising how likely the proposed experiment
is to yield interpretable results.

Scoring model — base = 100, subtract penalties:
  -30  Gene is DepMap common essential (lethality / viability confound)
  -15  Primary / hard-to-transfect cell line
  -10  Best sgRNA efficiency < 0.6 (GC-content proxy)
  -10  Weak literature support (< 2 source papers found)
  -10  Any feasibility flag present (biological caveat known)

Score is clamped to [0, 100].
Label thresholds:
  > 75 → High confidence
  50–75 → Moderate confidence
  < 50  → Low confidence
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Constants ──────────────────────────────────────────────────────────────

_PRIMARY_KEYWORDS = frozenset(["primary", "pbmc", "neuron", "ipsc", "hsc"])

_PENALTY_ESSENTIAL_GENE    = 30
_PENALTY_PRIMARY_CELL      = 15
_PENALTY_LOW_SGRNA_EFF     = 10
_PENALTY_WEAK_LITERATURE   = 10
_PENALTY_FEASIBILITY_FLAGS = 10


# ── Result types ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConfidenceFactor:
    label: str
    penalty: int      # absolute penalty value (always positive)
    triggered: bool   # True  → penalty was applied


@dataclass(frozen=True)
class ConfidenceResult:
    score: int                              # 0–100
    label: str                              # "High" | "Moderate" | "Low"
    factors: list[ConfidenceFactor] = field(default_factory=list)


# ── Private helpers ────────────────────────────────────────────────────────

def _is_primary_cell_line(cell_line_value: str) -> bool:
    return cell_line_value.lower() in _PRIMARY_KEYWORDS


def _label_for_score(score: int) -> str:
    if score > 75:
        return "High"
    if score >= 50:
        return "Moderate"
    return "Low"


# ── Public API ─────────────────────────────────────────────────────────────

def compute_confidence(
    *,
    is_essential_gene: bool,
    cell_line_value: str,
    best_sgrna_efficiency: float,
    literature_source_count: int,
    feasibility_flag_count: int,
) -> ConfidenceResult:
    """
    Compute experiment confidence from pipeline outputs.

    All inputs are derived from existing pipeline stages — no extra LLM calls.

    Args:
        is_essential_gene:       True if gene appears in DepMap common essential set.
        cell_line_value:         CellLine enum value string (e.g. "primary", "HEK293").
        best_sgrna_efficiency:   Highest efficiency_score across retrieved sgRNA candidates.
        literature_source_count: Number of source papers returned by the literature stage.
        feasibility_flag_count:  Total feasibility flags raised (warnings + blockers).

    Returns:
        ConfidenceResult with numeric score, categorical label, and per-factor breakdown.
    """
    factors = [
        ConfidenceFactor(
            label="Gene essentiality in the selected cell line",
            penalty=_PENALTY_ESSENTIAL_GENE,
            triggered=is_essential_gene,
        ),
        ConfidenceFactor(
            label="Cell line editability",
            penalty=_PENALTY_PRIMARY_CELL,
            triggered=_is_primary_cell_line(cell_line_value),
        ),
        ConfidenceFactor(
            label="sgRNA efficiency",
            penalty=_PENALTY_LOW_SGRNA_EFF,
            triggered=best_sgrna_efficiency < 0.6,
        ),
        ConfidenceFactor(
            label="Known pathway support in literature",
            penalty=_PENALTY_WEAK_LITERATURE,
            triggered=literature_source_count < 2,
        ),
        ConfidenceFactor(
            label="Assay clarity for phenotype measurement",
            penalty=_PENALTY_FEASIBILITY_FLAGS,
            triggered=feasibility_flag_count > 0,
        ),
    ]

    total_penalty = sum(f.penalty for f in factors if f.triggered)
    score = max(0, min(100, 100 - total_penalty))

    return ConfidenceResult(
        score=score,
        label=_label_for_score(score),
        factors=factors,
    )
