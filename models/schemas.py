"""
Shared Pydantic schemas for all pipeline stages.
Every agent input/output is typed here — no raw dicts in business logic.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class EditType(str, Enum):
    KNOCKOUT = "knockout"
    KNOCKIN = "knockin"
    ACTIVATION = "activation"
    REPRESSION = "repression"


class CellLine(str, Enum):
    HEK293 = "HEK293"
    HELA = "HeLa"
    HCT116 = "HCT116"
    JURKAT = "Jurkat"
    PRIMARY = "primary"
    OTHER = "other"


# ── Stage 1: Parser Output ─────────────────────────────────────────────────

class ParsedHypothesis(BaseModel):
    target_gene: str = Field(..., description="HGNC gene symbol, e.g. TP53")
    phenotype: str = Field(..., description="Expected biological phenotype after edit")
    system_context: str = Field(..., description="Disease / pathway / biological context")
    assumptions_made: list[str] = Field(..., description="Assumptions inferred from ambiguous input")
    edit_type: EditType = Field(default=EditType.KNOCKOUT)
    cell_line: CellLine = Field(default=CellLine.HEK293)
    raw_hypothesis: str = Field(..., description="Original user input, preserved verbatim")


# ── Stage 2: sgRNA Candidates ──────────────────────────────────────────────

class SgRNACandidate(BaseModel):
    guide_id: str
    gene: str
    sequence: str = Field(..., min_length=20, max_length=20, description="20-nt guide sequence")
    efficiency_score: float = Field(..., ge=0.0, le=1.0)
    off_target_score: float = Field(..., ge=0.0, le=1.0, description="Lower = fewer off-targets")
    pam: str = Field(default="NGG")
    chromosome: Optional[str] = None
    position: Optional[int] = None


class SgRNAResults(BaseModel):
    gene: str
    candidates: list[SgRNACandidate] = Field(..., min_length=1)


# ── Stage 3: Knockout Protocol ─────────────────────────────────────────────

class TransfectionMethod(str, Enum):
    LIPOFECTAMINE = "lipofectamine"
    ELECTROPORATION = "electroporation"
    LENTIVIRAL = "lentiviral"
    RNP = "rnp"  # ribonucleoprotein complex


class ProtocolStep(BaseModel):
    step_number: int
    title: str
    description: str
    duration_hours: Optional[float] = None
    critical_notes: Optional[str] = None


class KnockoutProtocol(BaseModel):
    gene: str
    cell_line: CellLine
    transfection_method: TransfectionMethod
    selected_sgrna: SgRNACandidate
    steps: list[ProtocolStep] = Field(..., min_length=5)
    total_duration_days: float
    expected_efficiency_pct: float = Field(..., ge=0.0, le=100.0)
    validation_assay: str
    safety_notes: list[str] = Field(..., min_length=1)


# ── Stage 4: Protocol Review ───────────────────────────────────────────────

class ReviewSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class ReviewComment(BaseModel):
    severity: ReviewSeverity
    step_reference: Optional[int] = None
    issue: str
    recommendation: str


class ProtocolReview(BaseModel):
    overall_feasibility: str = Field(..., description="high / medium / low")
    comments: list[ReviewComment]
    revised_steps: Optional[list[ProtocolStep]] = None
    approved: bool


# ── Stage 5: Execution Plan ────────────────────────────────────────────────

class Reagent(BaseModel):
    name: str
    quantity: str
    catalog_number: Optional[str] = None
    notes: Optional[str] = None


class WellAssignment(BaseModel):
    well: str   # e.g. "A1"
    sample: str
    condition: str


class ExecutionPlan(BaseModel):
    reagents: list[Reagent]
    plate_map: list[WellAssignment]
    timeline_days: list[str]  # day-by-day narrative
    pre_experiment_checklist: list[str]
    post_experiment_checklist: list[str]


# ── Pipeline Result (full packet) ─────────────────────────────────────────

class PipelineResult(BaseModel):
    hypothesis: ParsedHypothesis
    sgrna_results: SgRNAResults
    protocol: KnockoutProtocol
    review: ProtocolReview
    execution_plan: Optional[ExecutionPlan] = None
