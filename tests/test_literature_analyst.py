"""Unit tests for agents/literature_analyst.py (Stage 2.5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.literature_analyst import (
    _parse_and_validate,
    _validate_inputs,
    analyze_literature,
    MAX_RETRIES,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

FIXTURE_PAPERS = [
    {
        "title": "High-fidelity CRISPR-Cas9 variants",
        "journal": "Nature",
        "year": "2016",
        "abstract": "SpCas9-HF1 retains on-target activity while eliminating off-target mutations.",
    },
    {
        "title": "Optimized sgRNA design for CRISPR-Cas9",
        "journal": "Nature Biotechnology",
        "year": "2016",
        "abstract": "sgRNAs targeting early exons and avoiding repetitive regions show highest activity.",
    },
]


def _valid_result_dict() -> dict:
    return {
        "literature_insights": {
            "recommended_methods": ["Use SpCas9-HF1 to reduce off-target editing."],
            "validation_strategies": ["Confirm edits via Sanger sequencing with TIDE analysis."],
            "control_recommendations": ["Include a non-targeting sgRNA negative control."],
            "assay_examples": ["T7E1 mismatch cleavage assay for rapid efficiency screening."],
            "common_pitfalls": ["Repetitive genomic regions increase off-target risk."],
        },
        "source_papers": [
            {"title": "High-fidelity CRISPR-Cas9 variants", "journal": "Nature", "year": "2016"},
        ],
    }


def _make_mock_message(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


# ── _validate_inputs ────────────────────────────────────────────────────────

class TestValidateInputs:
    def test_empty_gene_raises(self):
        with pytest.raises(ValueError, match="target_gene"):
            _validate_inputs("", "some context", FIXTURE_PAPERS)

    def test_whitespace_gene_raises(self):
        with pytest.raises(ValueError, match="target_gene"):
            _validate_inputs("   ", "some context", FIXTURE_PAPERS)

    def test_empty_context_raises(self):
        with pytest.raises(ValueError, match="experimental_context"):
            _validate_inputs("TP53", "", FIXTURE_PAPERS)

    def test_whitespace_context_raises(self):
        with pytest.raises(ValueError, match="experimental_context"):
            _validate_inputs("TP53", "   ", FIXTURE_PAPERS)

    def test_empty_papers_raises(self):
        with pytest.raises(ValueError, match="papers"):
            _validate_inputs("TP53", "apoptosis", [])

    def test_paper_missing_field_raises(self):
        bad = [{"title": "T", "journal": "J", "year": "2020"}]  # no 'abstract'
        with pytest.raises(ValueError, match="abstract"):
            _validate_inputs("TP53", "apoptosis", bad)

    def test_paper_empty_field_raises(self):
        bad = [{"title": "T", "journal": "J", "year": "2020", "abstract": "   "}]
        with pytest.raises(ValueError, match="abstract"):
            _validate_inputs("TP53", "apoptosis", bad)

    def test_valid_inputs_pass(self):
        _validate_inputs("TP53", "apoptosis in HeLa", FIXTURE_PAPERS)


# ── _parse_and_validate ─────────────────────────────────────────────────────

class TestParseAndValidate:
    def test_valid_result_passes(self):
        result = _parse_and_validate(json.dumps(_valid_result_dict()))
        assert "literature_insights" in result
        assert "source_papers" in result

    def test_missing_literature_insights_raises(self):
        bad = {"source_papers": [{"title": "T", "journal": "J", "year": "2020"}]}
        with pytest.raises(ValueError, match="literature_insights"):
            _parse_and_validate(json.dumps(bad))

    def test_missing_source_papers_raises(self):
        bad = {"literature_insights": {k: [] for k in (
            "recommended_methods", "validation_strategies",
            "control_recommendations", "assay_examples", "common_pitfalls",
        )}}
        with pytest.raises(ValueError, match="source_papers"):
            _parse_and_validate(json.dumps(bad))

    def test_missing_insight_sub_key_raises(self):
        bad = _valid_result_dict()
        del bad["literature_insights"]["common_pitfalls"]
        with pytest.raises(ValueError, match="missing keys"):
            _parse_and_validate(json.dumps(bad))

    def test_non_list_insight_value_raises(self):
        bad = _valid_result_dict()
        bad["literature_insights"]["recommended_methods"] = "not a list"
        with pytest.raises(ValueError, match="must be a list"):
            _parse_and_validate(json.dumps(bad))

    def test_empty_source_papers_raises(self):
        bad = {**_valid_result_dict(), "source_papers": []}
        with pytest.raises(ValueError, match="source_papers"):
            _parse_and_validate(json.dumps(bad))

    def test_strips_markdown_fence(self):
        fenced = f"```json\n{json.dumps(_valid_result_dict())}\n```"
        result = _parse_and_validate(fenced)
        assert "literature_insights" in result

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="JSON parse error"):
            _parse_and_validate("{not json}")


# ── analyze_literature — mocked LLM ─────────────────────────────────────────

class TestAnalyzeLiterature:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            analyze_literature("TP53", "apoptosis", FIXTURE_PAPERS)

    @patch("agents.literature_analyst.anthropic.Anthropic")
    def test_happy_path_returns_insights(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_cls.return_value.messages.create.return_value = _make_mock_message(
            json.dumps(_valid_result_dict())
        )
        result = analyze_literature("TP53", "apoptosis in HeLa", FIXTURE_PAPERS)
        assert "literature_insights" in result
        assert "source_papers" in result

    @patch("agents.literature_analyst.anthropic.Anthropic")
    def test_gene_uppercased_in_prompt(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message(json.dumps(_valid_result_dict()))
        analyze_literature("tp53", "apoptosis", FIXTURE_PAPERS)
        user_content = create_mock.call_args[1]["messages"][0]["content"]
        assert "TP53" in user_content

    @patch("agents.literature_analyst.anthropic.Anthropic")
    def test_retries_on_invalid_json(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message("not json!!!"),
            _make_mock_message(json.dumps(_valid_result_dict())),
        ]
        result = analyze_literature("TP53", "apoptosis", FIXTURE_PAPERS)
        assert "literature_insights" in result
        assert create_mock.call_count == 2

    @patch("agents.literature_analyst.anthropic.Anthropic")
    def test_retry_message_includes_prior_error(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message("{bad}"),
            _make_mock_message(json.dumps(_valid_result_dict())),
        ]
        analyze_literature("TP53", "apoptosis", FIXTURE_PAPERS)
        user_content = create_mock.call_args_list[1][1]["messages"][0]["content"]
        assert "Previous attempt failed" in user_content

    @patch("agents.literature_analyst.anthropic.Anthropic")
    def test_raises_after_max_retries(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        create_mock = mock_cls.return_value.messages.create
        create_mock.return_value = _make_mock_message("{always bad")
        with pytest.raises(ValueError, match=f"failed after {MAX_RETRIES} attempts"):
            analyze_literature("TP53", "apoptosis", FIXTURE_PAPERS)
        assert create_mock.call_count == MAX_RETRIES

    @patch("agents.literature_analyst.anthropic.Anthropic")
    def test_retries_on_schema_error(self, mock_cls, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        bad = _valid_result_dict()
        del bad["literature_insights"]["common_pitfalls"]
        create_mock = mock_cls.return_value.messages.create
        create_mock.side_effect = [
            _make_mock_message(json.dumps(bad)),
            _make_mock_message(json.dumps(_valid_result_dict())),
        ]
        result = analyze_literature("TP53", "apoptosis", FIXTURE_PAPERS)
        assert "common_pitfalls" in result["literature_insights"]
        assert create_mock.call_count == 2
