"""
Example client script for the Doc Indexer API.
Shows how to interact with the keyword OCR endpoints.
"""

import json
import sys
from pathlib import Path

import requests


def process_pdfs_from_urls(api_base_url: str, pdf_urls: list[str], keywords: list[str]) -> dict:
    """
    Send PDF URLs to the API for keyword extraction.
    """
    endpoint = f"{api_base_url}/api/ocr/keyword-report"
    
    payload = {
        "pdf_urls": pdf_urls,
        "keywords": keywords
    }
    
    print(f"Sending request to {endpoint}...")
    print(f"PDFs: {len(pdf_urls)}, Keywords: {keywords}")
    
    try:
        response = requests.post(
            endpoint,
            json=payload,
            timeout=300  # 5 minutes - OCR can be slow
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out. Azure OCR may be taking too long.")
        sys.exit(1)
    except requests.exceptions.RequestException as exc:
        print(f"ERROR: {exc}")
        if hasattr(exc.response, 'text'):
            print(f"Response: {exc.response.text}")
        sys.exit(1)


def upload_and_process_pdfs(api_base_url: str, pdf_files: list[Path], keywords: list[str]) -> dict:
    """
    Upload PDF files to the API for keyword extraction.
    """
    endpoint = f"{api_base_url}/api/ocr/keyword-report-upload"
    
    # Prepare files for upload
    files = [
        ("files", (pdf_file.name, pdf_file.open("rb"), "application/pdf"))
        for pdf_file in pdf_files
    ]
    
    data = {
        "keywords": ",".join(keywords)
    }
    
    print(f"Uploading {len(pdf_files)} PDFs to {endpoint}...")
    print(f"Keywords: {keywords}")
    
    try:
        response = requests.post(
            endpoint,
            files=files,
            data=data,
            timeout=300  # 5 minutes
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out. Azure OCR may be taking too long.")
        sys.exit(1)
    except requests.exceptions.RequestException as exc:
        print(f"ERROR: {exc}")
        if hasattr(exc.response, 'text'):
            print(f"Response: {exc.response.text}")
        sys.exit(1)
    finally:
        # Close file handles
        for _, file_tuple in files:
            file_tuple[1].close()


def download_report(api_base_url: str, report_filename: str, output_path: Path) -> None:
    """
    Download the generated Word report.
    """
    endpoint = f"{api_base_url}/api/ocr/download-report/{report_filename}"
    
    print(f"Downloading report from {endpoint}...")
    
    try:
        response = requests.get(endpoint, timeout=30)
        response.raise_for_status()
        
        output_path.write_bytes(response.content)
        print(f"Report saved to: {output_path}")
    except requests.exceptions.RequestException as exc:
        print(f"ERROR downloading report: {exc}")
        sys.exit(1)


def print_results(result: dict) -> None:
    """
    Pretty print the API response.
    """
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    
    print("\nDownload Summary:")
    print(f"  Downloaded: {result['download_summary']['downloaded']}")
    print(f"  Skipped:    {result['download_summary']['skipped']}")
    print(f"  Failed:     {result['download_summary']['failed']}")
    
    print("\nOCR Summary:")
    print(f"  Processed: {result['ocr_summary']['processed']}")
    print(f"  Failed:    {result['ocr_summary']['failed']}")
    
    if result['ocr_summary']['errors']:
        print("\nOCR Errors:")
        for error in result['ocr_summary']['errors']:
            print(f"  - {error['file']}: {error['error']}")
    
    print("\nKeyword Matches:")
    for keyword, matches in result['keyword_index'].items():
        print(f"\n  {keyword}: {len(matches)} matches")
        for match in matches[:2]:  # Show first 2 matches
            print(f"    File: {match['file']}")
            print(f"    Text: {match['paragraph'][:100]}...")
        if len(matches) > 2:
            print(f"    ... and {len(matches) - 2} more")
    
    print("\nReport:")
    if result['report_available']:
        print(f"  Available: {result['report_filename']}")
    else:
        print("  No report generated")
    print("="*60 + "\n")


def main():
    # Configuration
    API_BASE_URL = "http://localhost:8000"  # Change to your Railway URL
    # API_BASE_URL = "https://your-app.railway.app"
    
    # Example 1: Process PDFs from URLs
    print("Example 1: Processing PDFs from URLs")
    print("-" * 60)
    
    pdf_urls = [
        "https://ulii.org/akn/ug/act/2015/3/eng%402015-03-06.pdf",
    ]
    keywords = ["woman", "gender"]
    
    result = process_pdfs_from_urls(API_BASE_URL, pdf_urls, keywords)
    print_results(result)
    
    # Download the report if available
    if result['report_available']:
        download_report(
            API_BASE_URL,
            result['report_filename'],
            Path("downloaded_report.docx")
        )
    
    # Example 2: Upload local PDF files (uncomment to use)
    # print("\nExample 2: Uploading local PDF files")
    # print("-" * 60)
    # 
    # local_pdfs = [
    #     Path("path/to/your/document1.pdf"),
    #     Path("path/to/your/document2.pdf"),
    # ]
    # keywords = ["climate", "sustainability"]
    # 
    # result = upload_and_process_pdfs(API_BASE_URL, local_pdfs, keywords)
    # print_results(result)


if __name__ == "__main__":
    main()
