"""
AutoLab-CRISPR — FastAPI server

Endpoints:
    POST /run/stream  — SSE stream: emits stage events then final result
    POST /run         — non-streaming fallback (returns final JSON only)
    GET  /demo/{name} — load the most recent cached result for a gene name
    GET  /health
"""

from __future__ import annotations

import asyncio
import json
import queue
import sys
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Project path ───────────────────────────────────────────────────────────

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from agents.feasibility_check import check_feasibility
from agents.literature_analyst import analyze_literature
from agents.protocol_generator import generate_protocol
from agents.protocol_patcher import apply_patches
from agents.reviewer import review_protocol
from agents.sgrna_retriever import get_guides
from agents.execution_planner import generate_execution_packet
from agents.parser import parse_hypothesis
from config import OUTPUT_DIR, TOP_K_GUIDES
from models.schemas import SgRNACandidate, SgRNAResults
from utils.pubmed_fetcher import fetch_papers

# ── App setup ──────────────────────────────────────────────────────────────

app = FastAPI(title="AutoLab-CRISPR API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request schema ─────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    hypothesis: str


# ── Pipeline helpers ───────────────────────────────────────────────────────

def _build_sgrna_results(gene: str, raw_guides: list[dict]) -> SgRNAResults:
    candidates = [
        SgRNACandidate(
            guide_id=g["guide_id"],
            gene=g["gene_symbol"],
            sequence=g["sgrna_sequence"],
            efficiency_score=g["gc_content"],
            off_target_score=0.0,
            pam=g.get("pam_sequence", "NGG"),
            chromosome=None,
            position=None,
        )
        for g in raw_guides
    ]
    return SgRNAResults(gene=gene, candidates=candidates)


def _fetch_literature(gene: str, context: str) -> tuple[dict | None, str]:
    try:
        papers = fetch_papers(gene, context, max_papers=4)
        if not papers:
            return None, "No additional context provided."
        lit_result = analyze_literature(gene, context, papers)
        lines = []
        insights = lit_result.get("literature_insights", {})
        for key, label in [
            ("recommended_methods", "Recommended methods"),
            ("validation_strategies", "Validation strategies"),
            ("control_recommendations", "Controls"),
        ]:
            items = insights.get(key, [])
            if items:
                lines.append(f"{label}: " + "; ".join(items))
        return lit_result, "\n".join(lines) or "No additional context provided."
    except Exception:
        return None, "No additional context provided."


# ── Transform backend → frontend response shape ────────────────────────────

def _to_response(hypothesis, feasibility_flags, sgrna_results, lit_result,
                 protocol, review, patches_applied, exec_packet) -> dict:
    blockers = [f for f in feasibility_flags if f.severity == "blocker"]
    warnings  = [f for f in feasibility_flags if f.severity == "warning"]
    feasibility_verdict = "block" if blockers else ("warn" if warnings else "pass")

    return {
        "hypothesis_text":    hypothesis.raw_hypothesis,
        "gene":               hypothesis.target_gene,
        "cell_line":          hypothesis.cell_line.value,
        "edit_type":          hypothesis.edit_type.value.title(),
        "phenotype":          hypothesis.phenotype,
        "system_context":     hypothesis.system_context,
        "assumptions":        hypothesis.assumptions_made,

        "feasibility_verdict": feasibility_verdict,
        "feasibility_flags": [
            {"severity": f.severity, "message": f.issue}
            for f in feasibility_flags
        ],

        "sgrna_candidates": [
            {
                "guide_id":         c.guide_id,
                "sequence":         c.sequence,
                "efficiency_score": c.efficiency_score,
                "pam":              c.pam,
            }
            for c in sgrna_results.candidates
        ],

        "protocol_steps": [
            {
                "step_number":    s.step_number,
                "title":          s.title,
                "duration_hours": s.duration_hours,
            }
            for s in protocol.steps
        ],
        "total_duration_days":  protocol.total_duration_days,
        "validation_assay":     protocol.validation_assay,
        "transfection_method":  protocol.transfection_method.value.title(),

        "verdict":          review.get("overall_verdict", "approve"),
        "flags":            review.get("validation_flags", []),
        "review_summary":   review.get("review_summary", ""),
        "patches_applied":  patches_applied,

        "timeline":  exec_packet.get("day_by_day_timeline", []),
        "reagents":  [
            {"item": r["item"], "purpose": r["purpose"]}
            for r in exec_packet.get("reagent_checklist", [])
        ],

        "literature_sources": [
            {
                "title":   p.get("title", ""),
                "journal": p.get("journal", ""),
                "year":    str(p.get("year", "")),
            }
            for p in (lit_result or {}).get("source_papers", [])
        ],
    }


# ── Streaming pipeline ─────────────────────────────────────────────────────
# Runs in a worker thread; emits dicts into event_queue.
# Sentinel None signals completion.

def _run_pipeline_streaming(hypothesis_text: str, event_queue: queue.Queue) -> None:
    def emit(event_type: str, **kwargs) -> None:
        event_queue.put({"type": event_type, **kwargs})

    try:
        # Stage 1 — Parse
        emit("stage", id="parse", status="active")
        hypothesis = parse_hypothesis(hypothesis_text)
        emit("stage", id="parse", status="done")

        # Stage 2 — Feasibility
        emit("stage", id="feasibility", status="active")
        flags = check_feasibility(hypothesis)
        blockers = [f for f in flags if f.is_blocker()]
        if blockers:
            raise ValueError(f"Feasibility blocker: {blockers[0].issue}")
        emit("stage", id="feasibility", status="done")

        # Stage 3 — sgRNA retrieval
        emit("stage", id="sgrna", status="active")
        raw_guides = get_guides(hypothesis.target_gene, max_guides=TOP_K_GUIDES)
        if not raw_guides:
            raise ValueError(f"No sgRNA guides found for '{hypothesis.target_gene}'.")
        sgrna_results = _build_sgrna_results(hypothesis.target_gene, raw_guides)
        emit("stage", id="sgrna", status="done")

        # Stage 4 — Literature
        emit("stage", id="literature", status="active")
        lit_result, literature_text = _fetch_literature(
            hypothesis.target_gene,
            f"{hypothesis.phenotype} {hypothesis.system_context}",
        )
        emit("stage", id="literature", status="done")

        # Stage 5 — Protocol generation
        emit("stage", id="protocol", status="active")
        protocol, _ = generate_protocol(hypothesis, sgrna_results, literature=literature_text)
        emit("stage", id="protocol", status="done")

        # Stage 6 — Review + patch
        emit("stage", id="review", status="active")
        review = review_protocol(hypothesis, protocol)
        protocol_json = json.loads(protocol.model_dump_json())
        patches_applied: list[str] = []

        criticals     = [f for f in review["validation_flags"] if f["severity"] == "critical"]
        non_patchable = [f for f in criticals if not f.get("patchable", True)]

        if non_patchable:
            protocol, _ = generate_protocol(
                hypothesis, sgrna_results,
                literature=literature_text, prior_review=review,
            )
            protocol_json = json.loads(protocol.model_dump_json())
            review = review_protocol(hypothesis, protocol)
        elif criticals:
            protocol_json, patches_applied = apply_patches(protocol_json, review, raw_guides)

        emit("stage", id="review", status="done")

        # Stage 7 — Execution packet
        emit("stage", id="execution", status="active")
        raw_exec = generate_execution_packet(protocol_json)
        exec_packet = raw_exec.get("execution_packet", raw_exec)
        emit("stage", id="execution", status="done")

        # Final result
        result = _to_response(
            hypothesis, flags, sgrna_results, lit_result,
            protocol, review, patches_applied, exec_packet,
        )
        emit("result", data=result)

    except ValueError as exc:
        emit("error", message=str(exc))
    except EnvironmentError as exc:
        emit("error", message=str(exc))
    except Exception as exc:
        emit("error", message=f"Pipeline error: {exc}")
    finally:
        event_queue.put(None)  # sentinel — stream is done


# ── SSE helpers ────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ── Routes ─────────────────────────────────────────────────────────────────

@app.post("/run/stream")
async def run_stream(body: RunRequest):
    if not body.hypothesis or len(body.hypothesis.strip()) < 10:
        raise HTTPException(status_code=422, detail="Hypothesis is too short.")

    event_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_event_loop()

    threading.Thread(
        target=_run_pipeline_streaming,
        args=(body.hypothesis.strip(), event_queue),
        daemon=True,
    ).start()

    async def generate():
        while True:
            # Poll queue without blocking the event loop
            event = await loop.run_in_executor(None, event_queue.get)
            if event is None:
                break
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@app.get("/demo/{name}")
async def demo_endpoint(name: str):
    gene = name.upper()
    candidates = sorted(OUTPUT_DIR.glob("*.json"), reverse=True)
    matches = [p for p in candidates if gene in p.name.upper()]
    path = matches[0] if matches else (candidates[0] if candidates else None)

    if path is None:
        raise HTTPException(status_code=404, detail="No cached output files found.")

    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read cache: {exc}")

    h     = data["hypothesis"]
    proto = data["protocol"]
    rev   = data["review"]
    ep    = data["execution_packet"]
    lit   = data.get("literature")

    feas_flags = [f for f in rev.get("validation_flags", []) if f.get("category") == "feasibility"]
    has_warning = any(f["severity"] in ("warning", "critical") for f in feas_flags)
    feasibility_verdict = "warn" if has_warning else "pass"

    return {
        "hypothesis_text":    h.get("raw_hypothesis", ""),
        "gene":               h.get("target_gene", ""),
        "cell_line":          h.get("cell_line", ""),
        "edit_type":          h.get("edit_type", "knockout").title(),
        "phenotype":          h.get("phenotype", ""),
        "system_context":     h.get("system_context", ""),
        "assumptions":        h.get("assumptions_made", []),
        "feasibility_verdict": feasibility_verdict,
        "feasibility_flags":  [
            {"severity": f.get("severity", "warning"), "message": f.get("issue", "")}
            for f in feas_flags
        ],
        "sgrna_candidates": [
            {
                "guide_id":         c["guide_id"],
                "sequence":         c["sequence"],
                "efficiency_score": c["efficiency_score"],
                "pam":              c.get("pam", "NGG"),
            }
            for c in data.get("sgrna_results", {}).get("candidates", [])
        ],
        "protocol_steps": [
            {
                "step_number":    s["step_number"],
                "title":          s["title"],
                "duration_hours": s.get("duration_hours"),
            }
            for s in proto.get("steps", [])
        ],
        "total_duration_days":  proto.get("total_duration_days", 0),
        "validation_assay":     proto.get("validation_assay", ""),
        "transfection_method":  proto.get("transfection_method", "").title(),
        "verdict":              rev.get("overall_verdict", "approve"),
        "flags":                rev.get("validation_flags", []),
        "review_summary":       rev.get("review_summary", ""),
        "patches_applied":      data.get("patches_applied", []),
        "timeline":  ep.get("day_by_day_timeline", []),
        "reagents":  [
            {"item": r["item"], "purpose": r["purpose"]}
            for r in ep.get("reagent_checklist", [])
        ],
        "literature_sources": [
            {
                "title":   p.get("title", ""),
                "journal": p.get("journal", ""),
                "year":    str(p.get("year", "")),
            }
            for p in (lit or {}).get("source_papers", [])
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
