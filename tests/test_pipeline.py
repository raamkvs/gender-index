from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doc_catalog import (
    build_catalog,
    build_summary_doc_text,
    catalog_entry_to_prompt_text,
    catalog_to_prompt_text,
)
from llm_client import (
    _extract_response_text,
    _looks_like_heading_only,
    analyze_all_documents,
    combine_document_extractions,
    format_extraction_for_api,
    normalize_llm_extraction,
    parse_llm_json_response,
)
from pipeline_download import download_pdfs_detailed, is_valid_pdf_file


# ------------------------------------------------------------------
# doc_catalog tests
# ------------------------------------------------------------------


def test_build_catalog_truncates_long_text() -> None:
    catalog = build_catalog(
        "chat-1",
        [{"source_url": "https://x/a.pdf", "filename": "a.pdf", "paragraphs": ["x" * 20_000]}],
        max_chars_per_doc=100,
    )
    doc = catalog["documents"][0]
    assert doc["truncated"] is True
    assert len(doc["text"]) == 100


def test_catalog_entry_to_prompt_text_includes_metadata() -> None:
    catalog = build_catalog(
        "chat-1",
        [{"source_url": "https://x/a.pdf", "filename": "a.pdf", "paragraphs": ["hello"]}],
    )
    text = catalog_entry_to_prompt_text(catalog["documents"][0])
    assert "a.pdf" in text
    assert "hello" in text


def test_catalog_entry_includes_target_keywords() -> None:
    catalog = build_catalog(
        "chat-1",
        [
            {
                "source_url": "https://x/a.pdf",
                "filename": "a.pdf",
                "paragraphs": ["hello"],
            }
        ],
    )
    text = catalog_entry_to_prompt_text(
        catalog["documents"][0], keywords=["gender", "policy"]
    )
    assert "Target keywords: gender, policy" in text
    assert "Full document text:" in text


def test_catalog_entry_no_keywords_when_empty() -> None:
    catalog = build_catalog(
        "chat-1",
        [{"source_url": "u", "filename": "a.pdf", "paragraphs": ["hello"]}],
    )
    text = catalog_entry_to_prompt_text(catalog["documents"][0])
    assert "Target keywords:" not in text


# ------------------------------------------------------------------
# llm_client tests
# ------------------------------------------------------------------


def test_combine_document_extractions() -> None:
    combined = combine_document_extractions(
        [
            "Convention on Biological Diversity (CBD). Recognizing the vital role that women play.",
            "UNFCCC FCCC/CP/2015/10/Add.1. Acknowledging gender equality.",
        ]
    )
    assert "Convention on Biological Diversity" in combined
    assert "UNFCCC" in combined
    assert combined.count("\n\n") == 1


def test_analyze_all_documents_calls_llm_per_doc() -> None:
    catalog = build_catalog(
        "chat-1",
        [
            {"source_url": "https://x/a.pdf", "filename": "a.pdf", "paragraphs": ["one"]},
            {"source_url": "https://x/b.pdf", "filename": "b.pdf", "paragraphs": ["two"]},
        ],
    )
    with patch("llm_client.analyze_document_with_llm") as mock_analyze:
        mock_analyze.side_effect = ["Doc A extract.", "Doc B extract."]
        result = analyze_all_documents(catalog)
    assert mock_analyze.call_count == 2
    assert "Doc A extract." in result
    assert "Doc B extract." in result


def test_extract_response_text_output_text() -> None:
    assert _extract_response_text({"output_text": "hello"}) == "hello"


def test_extract_response_text_output_array() -> None:
    payload = {
        "output": [
            {"content": [{"text": "line one"}, {"text": "line two"}]},
        ]
    }
    assert "line one" in _extract_response_text(payload)
    assert "line two" in _extract_response_text(payload)


def test_extract_response_text_output_text_field_in_content() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "output_text": '{"document_name":"A"}'}],
            }
        ]
    }
    assert _extract_response_text(payload) == '{"document_name":"A"}'


def test_parse_llm_json_response_from_code_fence() -> None:
    raw = '```json\n{"document_name": "Test", "relevant_paragraphs": ["hello"]}\n```'
    data = parse_llm_json_response(raw)
    assert data["document_name"] == "Test"
    assert data["relevant_paragraphs"] == ["hello"]


def test_normalize_llm_extraction_from_prose() -> None:
    normalized = normalize_llm_extraction(
        "### Convention on Biological Diversity\n\nRecognizing the role of **women**.",
        "fallback.pdf",
    )
    data = json.loads(normalized)
    assert "Convention on Biological Diversity" in data["document_name"]
    assert len(data["relevant_paragraphs"]) >= 1


def test_format_extraction_for_api_from_json() -> None:
    payload = json.dumps(
        {
            "document_name": "Paris Agreement",
            "relevant_paragraphs": ["Acknowledging **gender equality**."],
        }
    )
    formatted = format_extraction_for_api(payload)
    assert formatted.startswith("Paris Agreement.")
    assert "gender equality" in formatted
    assert "**" not in formatted


def test_looks_like_heading_only_detects_titles() -> None:
    assert _looks_like_heading_only("EQUIDAD DE GÉNERO")
    assert _looks_like_heading_only(
        '"EQUIDAD DE GÉNERO" - "POLÍTICA MONETARIA Y FINANCIERA" - "POLÍTICA FISCAL"'
    )


def test_normalize_llm_extraction_filters_heading_fragments() -> None:
    raw = json.dumps(
        {
            "document_name": "PNCL-DH Plan",
            "relevant_paragraphs": [
                "EQUIDAD DE GÉNERO",
                '"EQUIDAD DE GÉNERO" - "POLÍTICA MONETARIA Y FINANCIERA"',
                "El Plan Nacional reconoce la importancia de la **política** de **género** para reducir brechas estructurales y garantizar la participación de las mujeres en la toma de decisiones públicas.",
            ],
        }
    )
    normalized = normalize_llm_extraction(raw, "fallback.pdf")
    data = json.loads(normalized)
    assert len(data["relevant_paragraphs"]) == 1
    assert "Plan Nacional" in data["relevant_paragraphs"][0]


def test_catalog_entry_prompt_instructs_substantive_paragraphs() -> None:
    text = catalog_entry_to_prompt_text(
        {"doc_index": 1, "filename": "a.pdf", "source_url": "https://x/a.pdf", "text": "body"},
        keywords=["policy", "gender"],
    )
    assert "not section headings" in text.lower()


# ------------------------------------------------------------------
# pipeline_download tests
# ------------------------------------------------------------------


def test_download_pdfs_detailed_records_failures(tmp_path: Path) -> None:
    with patch("pipeline_download.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_response

        result = download_pdfs_detailed(tmp_path, ["https://example.com/a.pdf"])

    assert result.failed == 1
    assert result.downloaded == 0
    assert len(result.failed_links) == 1
    assert result.failed_links[0].reason == "HTTP 403"


def test_download_pdfs_detailed_success(tmp_path: Path) -> None:
    with patch("pipeline_download.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.iter_content = MagicMock(return_value=[b"%PDF-1.4", b" content"])
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_response

        result = download_pdfs_detailed(tmp_path, ["https://example.com/report.pdf"])

    assert result.downloaded == 1
    assert len(result.files) == 1
    assert result.url_by_file[result.files[0].name] == "https://example.com/report.pdf"


def test_download_pdfs_detailed_rejects_html(tmp_path: Path) -> None:
    with patch("pipeline_download.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.iter_content = MagicMock(return_value=[b"<!DOCTYPE html><html><body>"])
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_response

        result = download_pdfs_detailed(tmp_path, ["https://example.com/page.pdf"])

    assert result.failed == 1
    assert result.downloaded == 0
    assert len(result.failed_links) == 1
    assert "html" in result.failed_links[0].reason.lower()


def test_is_valid_pdf_file_detects_real_pdf(tmp_path: Path) -> None:
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    assert is_valid_pdf_file(pdf_file) is True


def test_is_valid_pdf_file_rejects_html(tmp_path: Path) -> None:
    html_file = tmp_path / "fake.pdf"
    html_file.write_bytes(b"<!DOCTYPE html><html><head><title>Fake PDF</title></head></html>")
    assert is_valid_pdf_file(html_file) is False


def test_is_valid_pdf_file_rejects_empty(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")
    assert is_valid_pdf_file(empty_file) is False


# ------------------------------------------------------------------
# pipeline_service tests (run_gender_pipeline)
# ------------------------------------------------------------------


def test_run_gender_pipeline_first_empty_links() -> None:
    from pipeline_service import run_gender_pipeline

    with pytest.raises(ValueError, match="links are required"):
        run_gender_pipeline("chat-topic-1", [], run="first")


def test_run_gender_pipeline_invalid_run_type() -> None:
    from pipeline_service import run_gender_pipeline

    with pytest.raises(ValueError, match="Invalid run type"):
        run_gender_pipeline("chat-topic-1", [], run="invalid")  # type: ignore[arg-type]


def test_run_gender_pipeline_first_full_mock(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "report.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    mock_supabase = MagicMock()
    mock_supabase.get_all_extractions.return_value = [
        {
            "ai_extraction": '{"document_name":"Doc A","relevant_paragraphs":["Extract about women."]}',
            "filename": "report.pdf",
        }
    ]
    mock_supabase.get_generated_document.return_value = None
    mock_blob = MagicMock()
    mock_blob.upload_file.return_value = "https://blob.vercel-storage.com/report.pdf"

    with (
        patch("pipeline_service.download_pdfs_detailed") as mock_dl,
        patch("pipeline_service._init_supabase", return_value=mock_supabase),
        patch("pipeline_service._init_blob", return_value=mock_blob),
        patch("pipeline_service.get_azure_settings", return_value=("https://ep", "key")),
        patch("pipeline_service._load_keywords", return_value=["gender", "women"]),
        patch("pipeline_service.analyze_pdf_paragraphs", return_value=["Women play a vital role."]),
        patch(
            "pipeline_service.analyze_document_with_llm",
            return_value='{"document_name":"Doc A","relevant_paragraphs":["Extract about women."]}',
        ),
        patch("pipeline_service._generate_and_upload_pdf", return_value=None),
        patch("pipeline_service.PIPELINE_DOWNLOAD_ROOT", tmp_path / "pipeline"),
    ):
        from pipeline_download import DetailedDownloadResult

        mock_dl.return_value = DetailedDownloadResult(
            downloaded=1,
            files=[fake_pdf],
            url_by_file={fake_pdf.name: "https://example.com/report.pdf"},
        )

        result = __import__("pipeline_service").run_gender_pipeline(
            chat_id_topic="test-topic",
            links=["https://example.com/report.pdf"],
            run="first",
        )

    assert result["run"] == "first"
    assert result["documents_processed"] == 1
    assert result["ai_extractions"] == ["Doc A. Extract about women."]
    assert len(result["blob_links"]) == 1
    mock_supabase.store_document_extraction.assert_called_once()
    mock_supabase.upsert_pipeline_metadata.assert_called_once()


def test_run_gender_pipeline_rerun_no_uploads(tmp_path: Path) -> None:
    mock_supabase = MagicMock()
    mock_supabase.get_unprocessed_uploads.return_value = []
    mock_supabase.get_all_extractions.return_value = [
        {"ai_extraction": "Existing extract.", "filename": "existing.pdf"}
    ]
    mock_supabase.get_generated_document.return_value = None
    mock_blob = MagicMock()

    with (
        patch("pipeline_service._init_supabase", return_value=mock_supabase),
        patch("pipeline_service._init_blob", return_value=mock_blob),
        patch("pipeline_service.get_azure_settings", return_value=("ep", "key")),
        patch("pipeline_service._load_keywords", return_value=["gender"]),
    ):
        result = __import__("pipeline_service").run_gender_pipeline(
            chat_id_topic="test-topic",
            links=[],
            run="rerun",
        )

    assert result["run"] == "rerun"
    assert result["documents_processed"] == 0
    assert result["ai_extractions"] == ["Existing extract."]


def test_build_ai_extractions_response_prepends_pdf_link() -> None:
    from pipeline_service import _build_ai_extractions_response

    result = _build_ai_extractions_response(
        ["Doc A extract.", "Doc B extract."],
        "https://blob.vercel-storage.com/report.pdf",
        "first",
    )
    assert result[0] == (
        "Gender Reviewer Report — Download PDF: https://blob.vercel-storage.com/report.pdf"
    )
    assert result[1:] == ["Doc A extract.", "Doc B extract."]


def test_run_gender_pipeline_rerun_returns_combined_extractions(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "upload.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 uploaded")

    mock_supabase = MagicMock()
    mock_supabase.get_unprocessed_uploads.return_value = [
        {"id": "uuid-1", "blob_url": "https://blob.vercel/upload.pdf", "filename": "upload.pdf"}
    ]
    mock_supabase.get_all_extractions.return_value = [
        {"ai_extraction": "Run 1 extract.", "filename": "a.pdf"},
        {"ai_extraction": '{"document_name":"Upload","relevant_paragraphs":["Run 2 new extract."]}', "filename": "upload.pdf"},
    ]
    mock_blob = MagicMock()
    mock_blob.download_file.return_value = fake_pdf

    with (
        patch("pipeline_service._init_supabase", return_value=mock_supabase),
        patch("pipeline_service._init_blob", return_value=mock_blob),
        patch("pipeline_service.get_azure_settings", return_value=("ep", "key")),
        patch("pipeline_service._load_keywords", return_value=["gender"]),
        patch("pipeline_service.analyze_pdf_paragraphs", return_value=["New paragraph."]),
        patch(
            "pipeline_service.analyze_document_with_llm",
            return_value='{"document_name":"Upload","relevant_paragraphs":["Run 2 new extract."]}',
        ),
        patch("pipeline_service._generate_and_upload_pdf", return_value=None),
        patch("pipeline_service.PIPELINE_DOWNLOAD_ROOT", tmp_path / "pipeline"),
    ):
        result = __import__("pipeline_service").run_gender_pipeline(
            chat_id_topic="test-topic",
            links=[],
            run="rerun",
        )

    assert result["run"] == "rerun"
    assert result["documents_processed"] == 1
    assert "Run 1 extract." in result["ai_extractions"]
    assert any("Run 2 new extract." in item for item in result["ai_extractions"])
    mock_supabase.mark_uploads_processed.assert_called_once_with(["uuid-1"])
    mock_supabase.store_document_extraction.assert_called_once()


def test_per_document_storage_called_per_file(tmp_path: Path) -> None:
    """Each downloaded document should produce exactly one Supabase store call."""
    fake_a = tmp_path / "a.pdf"
    fake_b = tmp_path / "b.pdf"
    fake_a.write_bytes(b"%PDF a")
    fake_b.write_bytes(b"%PDF b")

    mock_supabase = MagicMock()
    mock_supabase.get_all_extractions.return_value = [
        {"ai_extraction": "A extract.", "filename": "a.pdf"},
        {"ai_extraction": "B extract.", "filename": "b.pdf"},
    ]
    mock_blob = MagicMock()
    mock_blob.upload_file.return_value = "https://blob.vercel/x.pdf"

    with (
        patch("pipeline_service.download_pdfs_detailed") as mock_dl,
        patch("pipeline_service._init_supabase", return_value=mock_supabase),
        patch("pipeline_service._init_blob", return_value=mock_blob),
        patch("pipeline_service.get_azure_settings", return_value=("ep", "key")),
        patch("pipeline_service._load_keywords", return_value=["gender"]),
        patch("pipeline_service.analyze_pdf_paragraphs", return_value=["paragraph."]),
        patch(
            "pipeline_service.analyze_document_with_llm",
            side_effect=[
                '{"document_name":"A","relevant_paragraphs":["A extract."]}',
                '{"document_name":"B","relevant_paragraphs":["B extract."]}',
            ],
        ),
        patch("pipeline_service._generate_and_upload_pdf", return_value=None),
        patch("pipeline_service.PIPELINE_DOWNLOAD_ROOT", tmp_path / "pipeline"),
    ):
        from pipeline_download import DetailedDownloadResult

        mock_dl.return_value = DetailedDownloadResult(
            downloaded=2,
            files=[fake_a, fake_b],
            url_by_file={fake_a.name: "https://ex/a.pdf", fake_b.name: "https://ex/b.pdf"},
        )
        __import__("pipeline_service").run_gender_pipeline(
            "test", ["https://ex/a.pdf", "https://ex/b.pdf"], run="first"
        )

    assert mock_supabase.store_document_extraction.call_count == 2
