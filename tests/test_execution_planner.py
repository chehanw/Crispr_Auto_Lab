"""Unit tests for agents/execution_planner.py (Stage 5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.execution_planner import (
    _parse_and_validate,
    generate_execution_packet,
    MAX_RETRIES,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

def _valid_packet_dict() -> dict:
    return {
        "execution_packet": {
            "reagent_checklist": [
                {"item": "SpCas9 plasmid", "purpose": "Provides Cas9 nuclease activity"},
                {"item": "sgRNA construct", "purpose": "Guides Cas9 to TP53 locus"},
                {"item": "Lipofectamine 3000", "purpose": "Transfection reagent"},
                {"item": "Puromycin", "purpose": "Antibiotic selection of transfected cells"},
                {"item": "T7E1 enzyme", "purpose": "Mismatch cleavage for editing verification"},
            ],
            "experimental_conditions": [
                {"condition": "TP53-KO", "description": "Cells transfected with TP53-targeting sgRNA"},
                {"condition": "NT-control", "description": "Cells transfected with non-targeting sgRNA"},
            ],
            "day_by_day_timeline": [
                {"day": 1, "activity": "Seed HEK293 cells in 6-well plate"},
                {"day": 2, "activity": "Transfect with Cas9 + sgRNA using Lipofectamine 3000"},
                {"day": 4, "activity": "Begin puromycin selection at 1 µg/mL"},
                {"day": 7, "activity": "Extract genomic DNA and run T7E1 assay"},
            ],
            "validation_checkpoints": [
                {
                    "stage": "Editing efficiency",
                    "method": "T7E1 assay",
                    "success_criteria": ">50% indel frequency on agarose gel",
                },
                {
                    "stage": "KO confirmation",
                    "method": "Sanger sequencing + TIDE",
                    "success_criteria": "Biallelic frameshift mutations in all clones",
                },
                {
                    "stage": "Protein loss",
                    "method": "Western blot anti-p53",
                    "success_criteria": "Absence of p53 band at 53 kDa",
                },
            ],
            "expected_outputs": [
                "Confirmed TP53 knockout HEK293 polyclonal pool",
                "T7E1 gel image documenting editing efficiency",
                "Sanger traces confirming biallelic indels",
            ],
        }
    }


def _make_mock_message(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


# ── Input validation ────────────────────────────────────────────────────────

class TestInputValidation:
    def test_empty_dict_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with pytest.raises(ValueError, match="non-empty dict"):
            generate_execution_packet({})

    def test_non_dict_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with pytest.raises(ValueError, match="non-empty dict"):
            generate_execution_packet("not a dict")  # type: ignore

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            generate_execution_packet({"gene": "TP53"})


# ── _parse_and_validate ─────────────────────────────────────────────────────

class TestParseAndValidate:
    def test_valid_packet_passes(self):
        result = _parse_and_validate(json.dumps(_valid_packet_dict()))
        assert "execution_packet" in result

    def test_missing_top_level_key_raises(self):
        with pytest.raises(ValueError, match="execution_packet"):
            _parse_and_validate('{"wrong_key": {}}')

    def test_missing_sub_key_raises(self):
        bad = _valid_packet_dict()
        del bad["execution_packet"]["reagent_checklist"]
        with pytest.raises(ValueError, match="missing keys"):
            _parse_and_validate(json.dumps(bad))

    def test_too_few_reagents_raises(self):
        bad = _valid_packet_dict()
        bad["execution_packet"]["reagent_checklist"] = bad["execution_packet"]["reagent_checklist"][:3]
        with pytest.raises(ValueError, match="reagent_checklist"):
            _parse_and_validate(json.dumps(bad))

    def test_too_few_timeline_days_raises(self):
        bad = _valid_packet_dict()
        bad["execution_packet"]["day_by_day_timeline"] = bad["execution_packet"]["day_by_day_timeline"][:2]
        with pytest.raises(ValueError, match="day_by_day_timeline"):
            _parse_and_validate(json.dumps(bad))

    def test_too_few_checkpoints_raises(self):
        bad = _valid_packet_dict()
        bad["execution_packet"]["validation_checkpoints"] = bad["execution_packet"]["validation_checkpoints"][:1]
        with pytest.raises(ValueError, match="validation_checkpoints"):
            _parse_and_validate(json.dumps(bad))

    def test_strips_markdown_fence(self):
        fenced = f"```json\n{json.dumps(_valid_packet_dict())}\n```"
        result = _parse_and_validate(fenced)
        assert "execution_packet" in result

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="JSON parse error"):
            _parse_and_validate("{not json}")


# ── generate_execution_packet — mocked LLM ─────────────────────────────────

class TestGenerateExecutionPacket:
    @patch("agents.execution_planner.anthropic.Anthropic")
    def test_happy_path_returns_dict(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_cls.return_value.messages.create.return_value = _make_mock_message(
            json.dumps(_valid_packet_dict())
        )
        result = generate_execution_packet({"gene": "TP53"})
        assert "execution_packet" in result

    @patch("agents.execution_planner.anthropic.Anthropic")
    def test_all_sub_keys_present(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_cls.return_value.messages.create.return_value = _make_mock_message(
            json.dumps(_valid_packet_dict())
        )
        result = generate_execution_packet({"gene": "TP53"})
        ep = result["execution_packet"]
        for key in ("reagent_checklist", "experimental_conditions",
                    "day_by_day_timeline", "validation_checkpoints", "expected_outputs"):
            assert key in ep

    @patch("agents.execution_planner.anthropic.Anthropic")
    def test_retries_on_invalid_json(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message("not json!!!"),
            _make_mock_message(json.dumps(_valid_packet_dict())),
        ]
        result = generate_execution_packet({"gene": "TP53"})
        assert "execution_packet" in result
        assert create_mock.call_count == 2

    @patch("agents.execution_planner.anthropic.Anthropic")
    def test_retry_message_includes_prior_error(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message("{bad}"),
            _make_mock_message(json.dumps(_valid_packet_dict())),
        ]
        generate_execution_packet({"gene": "TP53"})
        user_content = create_mock.call_args_list[1][1]["messages"][0]["content"]
        assert "Previous attempt failed" in user_content

    @patch("agents.execution_planner.anthropic.Anthropic")
    def test_raises_after_max_retries(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message("{always bad")
        with pytest.raises(ValueError, match=f"failed after {MAX_RETRIES} attempts"):
            generate_execution_packet({"gene": "TP53"})
        assert create_mock.call_count == MAX_RETRIES

    @patch("agents.execution_planner.anthropic.Anthropic")
    def test_retries_on_schema_error(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        bad = _valid_packet_dict()
        del bad["execution_packet"]["expected_outputs"]
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message(json.dumps(bad)),
            _make_mock_message(json.dumps(_valid_packet_dict())),
        ]
        result = generate_execution_packet({"gene": "TP53"})
        assert "expected_outputs" in result["execution_packet"]
        assert create_mock.call_count == 2
