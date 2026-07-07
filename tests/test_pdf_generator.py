from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf_generator import _format_legal_heading_line, _parse_json_extraction


def test_format_legal_heading_line_both_parts() -> None:
    line = _format_legal_heading_line("GA res 74/236", "A/RES/74/236")
    assert line == "GA res 74/236 - A/RES/74/236"


def test_format_legal_heading_line_partial() -> None:
    line = _format_legal_heading_line("General Assembly resolution 74/236", None)
    assert line == "General Assembly resolution 74/236"


def test_format_legal_heading_line_empty() -> None:
    assert _format_legal_heading_line(None, None) is None


def test_parse_json_extraction_includes_new_fields() -> None:
    payload = json.dumps(
        {
            "document_name": "Convention on Biological Diversity",
            "document_type": "A",
            "document_symbol": "A/RES/74/236",
            "legal_heading": "General Assembly resolution 74/236",
            "relevant_paragraphs": [
                {
                    "subheading": "Article 14 — Rural women",
                    "text": "Recognizing the role of **women** in biodiversity conservation.",
                    "page_number": 3,
                }
            ],
            "case_studies": [],
        }
    )

    parsed = _parse_json_extraction(payload)
    assert parsed is not None

    (
        document_name,
        document_type,
        legal_heading,
        document_symbol,
        paragraphs,
        case_studies,
    ) = parsed

    assert document_name == "Convention on Biological Diversity"
    assert document_type == "A"
    assert legal_heading == "General Assembly resolution 74/236"
    assert document_symbol == "A/RES/74/236"
    assert case_studies == []
    assert paragraphs[0]["subheading"] == "Article 14 — Rural women"
    assert paragraphs[0]["text"].startswith("Recognizing the role")
    assert paragraphs[0]["page_number"] == 3


def test_parse_json_extraction_backward_compat() -> None:
    payload = json.dumps(
        {
            "document_name": "Legacy Doc",
            "document_type": "C",
            "relevant_paragraphs": [
                {"text": "Legacy paragraph one.", "page_number": 4},
                "Legacy paragraph two.",
            ],
            "case_studies": [],
        }
    )

    parsed = _parse_json_extraction(payload)
    assert parsed is not None

    _, _, legal_heading, document_symbol, paragraphs, _ = parsed
    assert legal_heading is None
    assert document_symbol is None
    assert len(paragraphs) == 2
    assert paragraphs[0]["subheading"] is None
    assert paragraphs[1]["subheading"] is None