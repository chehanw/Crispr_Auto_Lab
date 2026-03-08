"""
Execution Planner Agent (Stage 5)

Converts a KnockoutProtocol into a lab-ready execution packet.
Does NOT generate new biology — compiles protocol steps into operational artifacts.

Input:  protocol_json (dict from protocol_generator)
Output: execution_packet dict with reagent checklist, timeline, validation checkpoints
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# TODO: remove sys.path hack after proper packaging (pyproject.toml)
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import MODEL_FAST, MAX_TOKENS
from utils.llm_utils import extract_json

MAX_RETRIES = 3

# ── Prompts ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a CRISPR lab operations specialist. Your job is to convert a structured \
knockout protocol into a concise, execution-ready lab packet.

You are NOT inventing new biology. You are extracting and organizing information \
already present in the protocol into operational artifacts.

Return ONLY valid JSON — no markdown, no code fences, no explanation.

Schema (all fields required):
{
  "execution_packet": {
    "reagent_checklist": [
      { "item": "<reagent name>", "purpose": "<one-line reason it is needed>" }
    ],
    "experimental_conditions": [
      { "condition": "<condition name, e.g. TP53-KO>", "description": "<what this condition tests>" }
    ],
    "day_by_day_timeline": [
      { "day": <integer>, "activity": "<concise activity description>" }
    ],
    "validation_checkpoints": [
      {
        "stage": "<checkpoint name>",
        "method": "<assay or technique>",
        "success_criteria": "<what passing looks like>"
      }
    ],
    "expected_outputs": [
      "<string describing a concrete deliverable from the experiment>"
    ]
  }
}

Rules:
- reagent_checklist: Include Cas9 system, sgRNA construct, selection antibiotic, \
PCR/sequencing reagents, and assay reagents. 8–14 items. No duplicates.
- experimental_conditions: At minimum include the knockout condition and a \
negative control (non-targeting sgRNA or mock). 2–4 conditions total.
- day_by_day_timeline: One entry per day. Derive from the protocol step durations. \
Days must be sequential integers starting at 1. Be concise — one activity per day.
- validation_checkpoints: At minimum include editing verification and functional \
phenotype assay. 3–5 checkpoints.
- expected_outputs: 3–5 concrete deliverables (e.g. "Confirmed biallelic TP53 \
knockout clones by Sanger sequencing").
- Be concise. No prose paragraphs. Each field value is one sentence maximum."""

USER_TEMPLATE = """\
Protocol JSON:
{protocol_json}

Generate the execution packet now."""

RETRY_SUFFIX = "\n\nPrevious attempt failed: {error}\nReturn corrected JSON only."


# ── Public API ─────────────────────────────────────────────────────────────

def generate_execution_packet(protocol_json: dict, api_key: str | None = None) -> dict:
    """
    Convert a protocol dict into a lab execution packet.

    Args:
        protocol_json: Raw dict from protocol_generator (KnockoutProtocol.model_dump()).
        api_key:       Optional API key override; falls back to ANTHROPIC_API_KEY env var.

    Returns:
        Dict with key "execution_packet" containing all lab artifacts.

    Raises:
        ValueError:         If all retries fail JSON/schema validation.
        EnvironmentError:   If ANTHROPIC_API_KEY is not set.
        anthropic.APIError: On unrecoverable API failures.
    """
    if not isinstance(protocol_json, dict) or not protocol_json:
        raise ValueError("protocol_json must be a non-empty dict.")

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    base_msg = USER_TEMPLATE.format(protocol_json=json.dumps(protocol_json, indent=2))
    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        user_content = base_msg
        if last_error:
            user_content += RETRY_SUFFIX.format(error=last_error)

        try:
            message = client.messages.create(
                model=MODEL_FAST,
                max_tokens=MAX_TOKENS,
                temperature=0.1,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = message.content[0].text.strip()
            packet = _parse_and_validate(raw)
            return packet

        except ValueError as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise ValueError(
                    f"Execution planner failed after {MAX_RETRIES} attempts. "
                    f"Last error: {last_error}"
                ) from exc

    raise RuntimeError("Unexpected exit from retry loop.")  # pragma: no cover


# ── Validation ─────────────────────────────────────────────────────────────

def _parse_and_validate(text: str) -> dict:
    data = extract_json(text)

    if "execution_packet" not in data:
        raise ValueError("Missing top-level key: 'execution_packet'")

    packet = data["execution_packet"]
    required_keys = {
        "reagent_checklist", "experimental_conditions",
        "day_by_day_timeline", "validation_checkpoints", "expected_outputs",
    }
    missing = required_keys - packet.keys()
    if missing:
        raise ValueError(f"execution_packet missing keys: {missing}")

    if len(packet["reagent_checklist"]) < 4:
        raise ValueError("reagent_checklist must have at least 4 items.")
    if len(packet["day_by_day_timeline"]) < 3:
        raise ValueError("day_by_day_timeline must have at least 3 days.")
    if len(packet["validation_checkpoints"]) < 2:
        raise ValueError("validation_checkpoints must have at least 2 checkpoints.")

    return data


# ── Display ────────────────────────────────────────────────────────────────

def print_execution_packet(packet: dict) -> None:
    ep = packet["execution_packet"]

    print("\n  — Reagent Checklist —")
    for r in ep["reagent_checklist"]:
        print(f"    • {r['item']:<40}  {r['purpose']}")

    print("\n  — Experimental Conditions —")
    for c in ep["experimental_conditions"]:
        print(f"    [{c.get('condition', '?')}]  {c.get('description', '')}")

    print("\n  — Day-by-Day Timeline —")
    for d in ep["day_by_day_timeline"]:
        print(f"    Day {d['day']:>2}:  {d['activity']}")

    print("\n  — Validation Checkpoints —")
    for v in ep["validation_checkpoints"]:
        print(f"    [{v['stage']}]")
        print(f"      Method  : {v['method']}")
        print(f"      Pass if : {v['success_criteria']}")

    print("\n  — Expected Outputs —")
    for o in ep["expected_outputs"]:
        print(f"    • {o}")


# ── Test Harness ───────────────────────────────────────────────────────────

FIXTURE_PROTOCOL = {
    "gene": "TP53",
    "cell_line": "HeLa",
    "transfection_method": "lipofectamine",
    "selected_sgrna": {
        "guide_id": "TP53_g1",
        "gene": "TP53",
        "sequence": "GCACTTTGATGTCAACAGAT",
        "efficiency_score": 0.87,
        "off_target_score": 0.12,
        "pam": "NGG",
        "chromosome": "chr17",
        "position": 7676520,
    },
    "steps": [
        {
            "step_number": 1, "title": "Cell seeding",
            "description": "Seed HeLa at 70% confluency in antibiotic-free DMEM.",
            "duration_hours": 24.0, "critical_notes": None,
        },
        {
            "step_number": 2, "title": "Transfection",
            "description": "Lipofectamine 3000 with pX459-sgRNA plasmid.",
            "duration_hours": 0.5, "critical_notes": "No antibiotics during transfection.",
        },
        {
            "step_number": 3, "title": "Recovery",
            "description": "Replace media at 6h; incubate 48h total.",
            "duration_hours": 48.0, "critical_notes": None,
        },
        {
            "step_number": 4, "title": "Puromycin selection",
            "description": "Select with 2 µg/mL puromycin for 5–7 days.",
            "duration_hours": 168.0, "critical_notes": "Kill curve required.",
        },
        {
            "step_number": 5, "title": "Clonal expansion",
            "description": "Single-cell clone in 96-well plates for 14 days.",
            "duration_hours": 336.0, "critical_notes": None,
        },
        {
            "step_number": 6, "title": "Validation",
            "description": "T7E1, Sanger sequencing, Western blot for p53.",
            "duration_hours": 24.0, "critical_notes": "Confirm biallelic KO.",
        },
        {
            "step_number": 7, "title": "Functional assay",
            "description": "Annexin V/PI flow cytometry + cisplatin IC50.",
            "duration_hours": 72.0, "critical_notes": "BSL-2 for cisplatin.",
        },
    ],
    "total_duration_days": 24.0,
    "expected_efficiency_pct": 72.0,
    "validation_assay": "T7E1, Sanger, Western blot, Annexin V/PI",
    "safety_notes": ["BSL-2 containment required.", "Handle cisplatin as hazardous waste."],
}


def _run_tests() -> None:
    print("=" * 60)
    print("AutoLab-CRISPR  |  Execution Planner  |  Test Harness")
    print("=" * 60)

    t0 = time.perf_counter()
    try:
        packet = generate_execution_packet(FIXTURE_PROTOCOL)
        elapsed = time.perf_counter() - t0
        print_execution_packet(packet)
        print(f"\n  PASS  ({elapsed:.2f}s)")
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  FAIL  ({elapsed:.2f}s): {exc}")


if __name__ == "__main__":
    _run_tests()
