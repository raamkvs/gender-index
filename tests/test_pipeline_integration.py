"""Integration tests for the Gender Reviewer pipeline.

Mocked tests always run. Live tests (marked ``integration``) call real services
when credentials are configured in ``.env`` / ``.env.local``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=False)

from backend.main import app
from blob_client import BlobClient, BlobConfigError
from doc_catalog import build_catalog
from llm_client import analyze_document_with_llm, get_gpt54_settings
from ocr import analyze_pdf_paragraphs, get_azure_settings
from pipeline_download import download_pdfs_detailed
from pipeline_service import run_gender_pipeline
from supabase_client import SupabaseClient, SupabaseConfigError

SAMPLE_PDF_URL = (
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
)


def _has_azure_ocr() -> bool:
    try:
        get_azure_settings()
        return True
    except RuntimeError:
        return False


def _has_gpt54() -> bool:
    try:
        get_gpt54_settings()
        return True
    except Exception:
        return False


def _has_blob() -> bool:
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN", "").strip())


def _has_supabase() -> bool:
    return bool(
        os.getenv("SUPABASE_URL", "").strip()
        and os.getenv("SUPABASE_KEY", "").strip()
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestDownloadLayer:
    def test_downloads_public_pdf(self, tmp_path: Path) -> None:
        result = download_pdfs_detailed(tmp_path, [SAMPLE_PDF_URL], timeout=60)
        assert result.downloaded == 1 or result.skipped == 1
        assert len(result.files) == 1
        assert result.files[0].stat().st_size > 0

    def test_records_bad_url(self, tmp_path: Path) -> None:
        result = download_pdfs_detailed(
            tmp_path, ["https://example.invalid/nope.pdf"], timeout=10
        )
        assert result.failed == 1
        assert result.failed_links[0].reason


class TestCatalogLayer:
    def test_builds_one_entry_per_document(self) -> None:
        catalog = build_catalog(
            "chat-test",
            [
                {
                    "source_url": "https://x/a.pdf",
                    "filename": "a.pdf",
                    "paragraphs": ["Women and gender equality."],
                },
                {
                    "source_url": "https://x/b.pdf",
                    "filename": "b.pdf",
                    "paragraphs": ["Climate and human rights."],
                },
            ],
        )
        assert len(catalog["documents"]) == 2
        assert catalog["documents"][0]["doc_index"] == 1
        assert catalog["documents"][1]["doc_index"] == 2

    def test_includes_relevant_excerpts_in_entry(self) -> None:
        catalog = build_catalog(
            "chat-test",
            [
                {
                    "source_url": "https://x/a.pdf",
                    "filename": "a.pdf",
                    "paragraphs": ["Women and gender equality."],
                    "relevant_excerpts": ["gender equality excerpt"],
                }
            ],
        )
        assert catalog["documents"][0]["relevant_excerpts"] == ["gender equality excerpt"]


class TestLLMLayer:
    def test_analyze_document_mocked(self) -> None:
        entry = build_catalog(
            "c1",
            [{"source_url": "u", "filename": "treaty.pdf", "paragraphs": ["gender equality"]}],
        )["documents"][0]
        with patch("llm_client._call_llm", return_value="Treaty X. Extract about women."):
            text = analyze_document_with_llm(entry)
        assert "Treaty X" in text

    @pytest.mark.integration
    def test_live_gpt54_single_document(self) -> None:
        if not _has_gpt54():
            pytest.skip("GPT54 credentials not configured")
        entry = build_catalog(
            "live-test",
            [
                {
                    "source_url": SAMPLE_PDF_URL,
                    "filename": "dummy.pdf",
                    "paragraphs": [
                        "Convention on Biological Diversity. "
                        "Recognizing the vital role that women play in biodiversity."
                    ],
                }
            ],
        )["documents"][0]
        text = analyze_document_with_llm(entry, timeout_seconds=120)
        assert len(text.strip()) > 20


class TestBlobLayer:
    def test_from_env_raises_without_token(self) -> None:
        with patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": ""}):
            with pytest.raises(BlobConfigError):
                BlobClient.from_env()

    def test_from_env_succeeds_with_token(self) -> None:
        with patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "vercel_blob_test_token"}):
            client = BlobClient.from_env()
        assert client.token == "vercel_blob_test_token"

    @pytest.mark.integration
    def test_live_upload_and_download(self, tmp_path: Path) -> None:
        if not _has_blob():
            pytest.skip("BLOB_READ_WRITE_TOKEN not configured")

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4 test content for blob upload")

        client = BlobClient.from_env()
        url = client.upload_file(pdf, pdf.name)
        assert url.startswith("https://")

        dest = tmp_path / "downloaded.pdf"
        client.download_file(url, dest)
        assert dest.exists()
        assert dest.stat().st_size > 0


class TestSupabaseLayer:
    def test_from_env_raises_without_credentials(self) -> None:
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_KEY": ""}):
            with pytest.raises(SupabaseConfigError):
                SupabaseClient.from_env()

    @pytest.mark.integration
    def test_live_store_and_retrieve_extraction(self) -> None:
        if not _has_supabase():
            pytest.skip("Supabase credentials not configured")

        client = SupabaseClient.from_env()
        chat_id = f"pytest-{os.getpid()}"

        row_id = client.store_document_extraction(
            chat_id_topic=chat_id,
            filename="test.pdf",
            ai_extraction="Test extraction text.",
            keywords=["gender"],
        )
        assert row_id

        all_texts = client.get_all_extraction_texts(chat_id)
        assert "Test extraction text." in all_texts

    @pytest.mark.integration
    def test_live_upload_record_and_mark_processed(self) -> None:
        if not _has_supabase():
            pytest.skip("Supabase credentials not configured")

        client = SupabaseClient.from_env()
        chat_id = f"pytest-upload-{os.getpid()}"

        upload_id = client.create_upload_record(
            chat_id_topic=chat_id,
            blob_url="https://blob.example/test.pdf",
            filename="test.pdf",
        )
        assert upload_id

        unprocessed = client.get_unprocessed_uploads(chat_id)
        assert any(u["id"] == upload_id for u in unprocessed)

        client.mark_uploads_processed([upload_id])
        unprocessed_after = client.get_unprocessed_uploads(chat_id)
        assert not any(u["id"] == upload_id for u in unprocessed_after)


class TestOCRLayer:
    @pytest.mark.integration
    def test_live_azure_ocr_on_downloaded_pdf(self, tmp_path: Path) -> None:
        if not _has_azure_ocr():
            pytest.skip("Azure Document Intelligence not configured")

        dl = download_pdfs_detailed(tmp_path, [SAMPLE_PDF_URL], timeout=60)
        assert dl.files, "Could not download sample PDF for OCR test"
        endpoint, key = get_azure_settings()
        paragraphs = analyze_pdf_paragraphs(dl.files[0], endpoint, key)
        assert isinstance(paragraphs, list)


class TestPipelineOrchestration:
    def test_api_endpoint_mocked(self, client: TestClient) -> None:
        with patch("backend.routers.pipeline.run_gender_pipeline") as mock_run:
            mock_run.return_value = {
                "chat_id_topic": "climate-gender-2024",
                "run": "first",
                "ai_extractions": ["Doc A. Extract one.", "Doc B. Extract two."],
                "documents_processed": 2,
                "total_documents": 2,
                "undownloadable_links": [{"url": "https://bad.example/x.pdf", "reason": "HTTP 404"}],
                "blob_links": [{"url": "https://blob.vercel/a.pdf", "filename": "a.pdf"}],
                "ocr_errors": [],
            }
            response = client.post(
                "/api/pipeline/analyze",
                json={
                    "chat_id_topic": "climate-gender-2024",
                    "links": [
                        "https://example.com/a.pdf",
                        "https://bad.example/x.pdf",
                    ],
                    "run": "first",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["chat_id_topic"] == "climate-gender-2024"
        assert body["run"] == "first"
        assert body["documents_processed"] == 2
        assert len(body["ai_extractions"]) == 2
        assert len(body["undownloadable_links"]) == 1
        assert len(body["blob_links"]) == 1

    def test_api_rerun_endpoint_mocked(self, client: TestClient) -> None:
        with patch("backend.routers.pipeline.run_gender_pipeline") as mock_run:
            mock_run.return_value = {
                "chat_id_topic": "climate-gender-2024",
                "run": "rerun",
                "ai_extractions": ["Existing.", "New extract."],
                "documents_processed": 1,
                "total_documents": 2,
                "undownloadable_links": [],
                "blob_links": [],
                "ocr_errors": [],
            }
            response = client.post(
                "/api/pipeline/analyze",
                json={"chat_id_topic": "climate-gender-2024", "run": "rerun"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["run"] == "rerun"
        assert body["total_documents"] == 2

    def test_api_rejects_empty_chat_id(self, client: TestClient) -> None:
        response = client.post(
            "/api/pipeline/analyze",
            json={"chat_id_topic": "  ", "links": ["https://example.com/a.pdf"]},
        )
        assert response.status_code == 400

    def test_api_rejects_first_run_without_links(self, client: TestClient) -> None:
        response = client.post(
            "/api/pipeline/analyze",
            json={"chat_id_topic": "chat-1", "links": [], "run": "first"},
        )
        assert response.status_code == 400

    def test_api_accepts_rerun_without_links(self, client: TestClient) -> None:
        with patch("backend.routers.pipeline.run_gender_pipeline") as mock_run:
            mock_run.return_value = {
                "chat_id_topic": "chat-1",
                "run": "rerun",
                "ai_extractions": [],
                "documents_processed": 0,
                "total_documents": 0,
                "undownloadable_links": [],
                "blob_links": [],
                "ocr_errors": [],
            }
            response = client.post(
                "/api/pipeline/analyze",
                json={"chat_id_topic": "chat-1", "run": "rerun"},
            )
        assert response.status_code == 200

    @pytest.mark.integration
    def test_live_end_to_end_first_run(self, tmp_path: Path) -> None:
        if not (_has_azure_ocr() and _has_gpt54() and _has_blob() and _has_supabase()):
            pytest.skip(
                "Full live pipeline requires Azure OCR, GPT54, Vercel Blob, and Supabase"
            )

        chat_id = f"live-e2e-{os.getpid()}"
        with patch("pipeline_service.PIPELINE_DOWNLOAD_ROOT", tmp_path / "pipeline"):
            result = run_gender_pipeline(
                chat_id_topic=chat_id,
                links=[SAMPLE_PDF_URL],
                run="first",
                download_timeout=60,
            )

        assert result["documents_processed"] >= 1
        assert len(result["ai_extractions"]) >= 1
        assert len(result["blob_links"]) >= 1
        assert isinstance(result["ai_extractions"][0], str)
