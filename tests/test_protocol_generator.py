"""
Unit tests for agents/protocol_generator.py (Module 3).

Coverage strategy:
- Input validation (no LLM calls)
- Retry logic (mocked LLM)
- Schema validation (mocked LLM)
- Happy-path integration (mocked LLM)

JSON extraction tests live in test_llm_utils.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.schemas import (
    CellLine,
    EditType,
    KnockoutProtocol,
    ParsedHypothesis,
    SgRNACandidate,
    SgRNAResults,
    TransfectionMethod,
)
from agents.protocol_generator import (
    _format_review_flags,
    _validate_inputs,
    _validate_schema,
    generate_protocol,
    MAX_RETRIES,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def hypothesis() -> ParsedHypothesis:
    return ParsedHypothesis(
        target_gene="TP53",
        phenotype="Loss of apoptosis checkpoint",
        system_context="Cancer / p53 pathway",
        assumptions_made=["Cell line defaulted to HEK293"],
        edit_type=EditType.KNOCKOUT,
        cell_line=CellLine.HEK293,
        raw_hypothesis="Knock out TP53.",
    )


@pytest.fixture()
def sgrna_results() -> SgRNAResults:
    return SgRNAResults(
        gene="TP53",
        candidates=[
            SgRNACandidate(
                guide_id="TP53_g1",
                gene="TP53",
                sequence="GCACTTTGATGTCAACAGAT",
                efficiency_score=0.87,
                off_target_score=0.12,
                pam="NGG",
                chromosome="chr17",
                position=7676520,
            ),
            SgRNACandidate(
                guide_id="TP53_g2",
                gene="TP53",
                sequence="ACTTCCTGAAAACAACGTTC",
                efficiency_score=0.81,
                off_target_score=0.18,
                pam="NGG",
                chromosome="chr17",
                position=7676154,
            ),
        ],
    )


def _valid_protocol_dict() -> dict:
    """Minimal valid KnockoutProtocol payload (5 steps, 1 safety note)."""
    return {
        "gene": "TP53",
        "cell_line": "HEK293",
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
                "step_number": 1,
                "title": "Cell seeding",
                "description": "Seed 2×10⁵ HEK293 cells per well in 6-well plate.",
                "duration_hours": 24.0,
                "critical_notes": "Cells should be 70% confluent at transfection.",
            },
            {
                "step_number": 2,
                "title": "Lipofection",
                "description": "Transfect 1 µg Cas9 plasmid + 0.5 µg sgRNA with Lipofectamine 3000.",
                "duration_hours": 6.0,
                "critical_notes": "Prepare lipofection mix fresh.",
            },
            {
                "step_number": 3,
                "title": "Recovery",
                "description": "Replace media 6h post-transfection; incubate 48h.",
                "duration_hours": 48.0,
                "critical_notes": None,
            },
            {
                "step_number": 4,
                "title": "Selection",
                "description": "Add puromycin 1 µg/mL for 72h to select transfected cells.",
                "duration_hours": 72.0,
                "critical_notes": "Titrate antibiotic on untransfected cells first.",
            },
            {
                "step_number": 5,
                "title": "Validation",
                "description": "Extract genomic DNA; perform T7E1 assay; Sanger sequence.",
                "duration_hours": 8.0,
                "critical_notes": "Include non-transfected control.",
            },
        ],
        "total_duration_days": 7.0,
        "expected_efficiency_pct": 75.0,
        "validation_assay": "T7E1 mismatch cleavage + Sanger sequencing",
        "safety_notes": ["Work under BSL-2 conditions; dispose of cells as biological waste."],
    }


def _make_mock_message(text: str) -> MagicMock:
    """Return a mock anthropic message object with .content[0].text = text."""
    content_block = MagicMock()
    content_block.text = text
    msg = MagicMock()
    msg.content = [content_block]
    return msg


# ── Schema-level constraints (no LLM calls) ─────────────────────────────────

class TestSchemaConstraints:
    def test_sgrna_results_rejects_empty_candidates(self):
        """min_length=1 on SgRNAResults.candidates enforced by Pydantic."""
        with pytest.raises(ValidationError):
            SgRNAResults(gene="TP53", candidates=[])

    def test_knockout_protocol_rejects_fewer_than_5_steps(self):
        """min_length=5 on KnockoutProtocol.steps enforced by Pydantic."""
        four_steps = _valid_protocol_dict()
        four_steps["steps"] = four_steps["steps"][:4]
        with pytest.raises(ValidationError):
            KnockoutProtocol(**four_steps)

    def test_knockout_protocol_rejects_empty_safety_notes(self):
        """min_length=1 on KnockoutProtocol.safety_notes enforced by Pydantic."""
        no_safety = {**_valid_protocol_dict(), "safety_notes": []}
        with pytest.raises(ValidationError):
            KnockoutProtocol(**no_safety)


# ── _validate_inputs ────────────────────────────────────────────────────────

class TestValidateInputs:
    def test_empty_gene_raises(self, hypothesis):
        bad = hypothesis.model_copy(update={"target_gene": ""})
        with pytest.raises(ValueError, match="target_gene"):
            _validate_inputs(bad)

    def test_valid_inputs_pass(self, hypothesis):
        _validate_inputs(hypothesis)  # should not raise


# ── _validate_schema ────────────────────────────────────────────────────────

class TestValidateSchema:
    def test_valid_dict_returns_model(self):
        protocol = _validate_schema(_valid_protocol_dict())
        assert isinstance(protocol, KnockoutProtocol)
        assert protocol.gene == "TP53"

    def test_missing_required_field_raises(self):
        bad = {k: v for k, v in _valid_protocol_dict().items() if k != "validation_assay"}
        with pytest.raises(ValueError, match="Schema validation failed"):
            _validate_schema(bad)

    def test_invalid_enum_value_raises(self):
        bad = {**_valid_protocol_dict(), "transfection_method": "INVALID"}
        with pytest.raises(ValueError, match="Schema validation failed"):
            _validate_schema(bad)

    def test_efficiency_pct_out_of_range_raises(self):
        bad = {**_valid_protocol_dict(), "expected_efficiency_pct": 150.0}
        with pytest.raises(ValueError, match="Schema validation failed"):
            _validate_schema(bad)

    def test_fewer_than_5_steps_raises(self):
        bad = {**_valid_protocol_dict(), "steps": _valid_protocol_dict()["steps"][:4]}
        with pytest.raises(ValueError, match="Schema validation failed"):
            _validate_schema(bad)

    def test_empty_safety_notes_raises(self):
        bad = {**_valid_protocol_dict(), "safety_notes": []}
        with pytest.raises(ValueError, match="Schema validation failed"):
            _validate_schema(bad)


# ── generate_protocol — mocked LLM ─────────────────────────────────────────

class TestGenerateProtocol:
    def test_missing_api_key_raises(self, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            generate_protocol(hypothesis, sgrna_results)

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_happy_path_returns_model_and_dict(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        valid_json = json.dumps(_valid_protocol_dict())
        mock_cls.return_value.messages.create.return_value = _make_mock_message(valid_json)

        protocol, raw = generate_protocol(hypothesis, sgrna_results)

        assert isinstance(protocol, KnockoutProtocol)
        assert isinstance(raw, dict)
        assert protocol.gene == "TP53"
        assert protocol.transfection_method == TransfectionMethod.LIPOFECTAMINE

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_returns_parsed_dict_with_all_keys(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        valid_json = json.dumps(_valid_protocol_dict())
        mock_cls.return_value.messages.create.return_value = _make_mock_message(valid_json)

        _, raw = generate_protocol(hypothesis, sgrna_results)

        required_keys = {
            "gene", "cell_line", "transfection_method", "selected_sgrna",
            "steps", "total_duration_days", "expected_efficiency_pct",
            "validation_assay", "safety_notes",
        }
        assert required_keys.issubset(raw.keys())

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_accepts_markdown_fenced_json(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        fenced = f"```json\n{json.dumps(_valid_protocol_dict())}\n```"
        mock_cls.return_value.messages.create.return_value = _make_mock_message(fenced)

        protocol, _ = generate_protocol(hypothesis, sgrna_results)
        assert protocol.gene == "TP53"

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_passes_literature_in_user_message(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message(json.dumps(_valid_protocol_dict()))

        literature = "Joung et al. 2017: SpCas9 achieves >80% efficiency."
        generate_protocol(hypothesis, sgrna_results, literature=literature)

        user_content = create_mock.call_args[1]["messages"][0]["content"]
        assert literature in user_content

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_retries_on_invalid_json(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message("not json at all!!!"),
            _make_mock_message(json.dumps(_valid_protocol_dict())),
        ]

        protocol, _ = generate_protocol(hypothesis, sgrna_results)

        assert protocol.gene == "TP53"
        assert create_mock.call_count == 2

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_retry_message_includes_prior_error(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message("{bad json}"),
            _make_mock_message(json.dumps(_valid_protocol_dict())),
        ]

        generate_protocol(hypothesis, sgrna_results)

        user_content = create_mock.call_args_list[1][1]["messages"][0]["content"]
        assert "Previous attempt failed" in user_content

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_raises_after_max_retries_exhausted(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message("{always bad json !!!")

        with pytest.raises(ValueError, match=f"failed after {MAX_RETRIES} attempts"):
            generate_protocol(hypothesis, sgrna_results)

        assert create_mock.call_count == MAX_RETRIES

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_retries_on_schema_validation_error(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        bad_schema = {k: v for k, v in _valid_protocol_dict().items() if k != "validation_assay"}
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message(json.dumps(bad_schema)),
            _make_mock_message(json.dumps(_valid_protocol_dict())),
        ]

        protocol, _ = generate_protocol(hypothesis, sgrna_results)
        assert protocol.validation_assay is not None
        assert create_mock.call_count == 2


# ── prior_review / revision loop ────────────────────────────────────────────

class TestFormatReviewFlags:
    def test_empty_flags_returns_fallback(self):
        text = _format_review_flags({"validation_flags": []})
        assert "no specific flags" in text

    def test_missing_flags_key_returns_fallback(self):
        text = _format_review_flags({})
        assert "no specific flags" in text

    def test_formats_single_flag(self):
        review = {
            "validation_flags": [{
                "severity": "critical",
                "category": "controls",
                "issue": "No negative control.",
                "recommendation": "Add non-targeting sgRNA.",
            }]
        }
        text = _format_review_flags(review)
        assert "[CRITICAL]" in text
        assert "No negative control." in text
        assert "Add non-targeting sgRNA." in text

    def test_formats_multiple_flags_numbered(self):
        flags = [
            {"severity": "critical", "category": "controls",
             "issue": "Issue A", "recommendation": "Fix A"},
            {"severity": "warning", "category": "validation",
             "issue": "Issue B", "recommendation": "Fix B"},
        ]
        text = _format_review_flags({"validation_flags": flags})
        assert "1." in text
        assert "2." in text


class TestPriorReviewInjection:
    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_prior_review_appended_to_prompt(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message(json.dumps(_valid_protocol_dict()))

        prior_review = {
            "validation_flags": [{
                "severity": "critical",
                "category": "controls",
                "issue": "Missing negative control.",
                "recommendation": "Add non-targeting sgRNA condition.",
            }]
        }
        generate_protocol(hypothesis, sgrna_results, prior_review=prior_review)

        user_content = create_mock.call_args[1]["messages"][0]["content"]
        assert "REVISION REQUIRED" in user_content
        assert "Missing negative control." in user_content

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_no_prior_review_no_revision_suffix(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message(json.dumps(_valid_protocol_dict()))

        generate_protocol(hypothesis, sgrna_results, prior_review=None)

        user_content = create_mock.call_args[1]["messages"][0]["content"]
        assert "REVISION REQUIRED" not in user_content

    @patch("agents.protocol_generator.anthropic.Anthropic")
    def test_prior_review_with_empty_flags_uses_fallback(self, mock_cls, hypothesis, sgrna_results, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message(json.dumps(_valid_protocol_dict()))

        generate_protocol(hypothesis, sgrna_results, prior_review={"validation_flags": []})

        user_content = create_mock.call_args[1]["messages"][0]["content"]
        assert "REVISION REQUIRED" in user_content
        assert "no specific flags" in user_content
