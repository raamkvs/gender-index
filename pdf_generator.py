"""PDF report generator for Gender Reviewer pipeline."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _parse_json_extraction(ai_extraction: str) -> Optional[Tuple[str, str, List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """Parse structured JSON extraction into document name, type, paragraphs with pages, and case studies.
    
    Returns:
        Tuple of (document_name, document_type, paragraphs_with_pages, case_studies) or None if parsing fails
    """
    try:
        data = json.loads(ai_extraction)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    document_name = str(data.get("document_name", "")).strip()
    document_type = str(data.get("document_type", "A")).strip()
    paragraphs = data.get("relevant_paragraphs", [])
    case_studies = data.get("case_studies", [])
    
    if not isinstance(paragraphs, list):
        paragraphs = []
    if not isinstance(case_studies, list):
        case_studies = []

    # Handle new format (objects) and old format (strings) for backward compatibility
    cleaned_paragraphs = []
    for p in paragraphs:
        if isinstance(p, dict):
            # New format: {"text": "...", "page_number": N}
            text = str(p.get("text", "")).strip()
            page_number = p.get("page_number")
            if text:
                cleaned_paragraphs.append({
                    "text": text,
                    "page_number": page_number
                })
        elif isinstance(p, str) and p.strip():
            # Old format: plain string - convert to new format
            cleaned_paragraphs.append({
                "text": p.strip(),
                "page_number": None
            })
    
    # Clean case studies
    cleaned_case_studies = []
    for cs in case_studies:
        if isinstance(cs, dict):
            name = str(cs.get("name", "")).strip()
            if name:
                cleaned_case_studies.append({
                    "name": name,
                    "year": str(cs.get("year", "")).strip(),
                    "environmental_topic": str(cs.get("environmental_topic", "")).strip(),
                    "summary": str(cs.get("summary", "")).strip(),
                    "source": str(cs.get("source", "")).strip(),
                    "page_number": cs.get("page_number")
                })
    
    return document_name, document_type, cleaned_paragraphs, cleaned_case_studies


def _parse_markdown_to_flowables(text: str, styles: Any) -> List[Any]:
    """
    Parse markdown-style text into ReportLab Flowable elements.
    
    Supports:
    - ## Section headers
    - ### Subsection headers
    - **bold text**
    - *italic text*
    - (a), (b), (c) list items
    - Horizontal rules (---)
    - Paragraphs
    """
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    
    elements = []
    lines = text.split('\n')
    
    # Define styles for different elements
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=15,
        textColor=colors.HexColor('#003366'),
        spaceAfter=10,
        spaceBefore=16,
        fontName='Helvetica-Bold',
    )
    
    subsection_style = ParagraphStyle(
        'Subsection',
        parent=styles['Heading3'],
        fontSize=13,
        textColor=colors.HexColor('#006699'),
        spaceAfter=8,
        spaceBefore=12,
        fontName='Helvetica-Bold',
    )
    
    body_style = ParagraphStyle(
        'Body',
        parent=styles['BodyText'],
        fontSize=11,
        leading=16,
        spaceAfter=8,
        alignment=4,  # Justify
    )
    
    list_item_style = ParagraphStyle(
        'ListItem',
        parent=styles['BodyText'],
        fontSize=11,
        leading=16,
        spaceAfter=6,
        leftIndent=20,
        alignment=4,  # Justify
    )
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Skip empty lines
        if not line:
            i += 1
            continue
        
        # Horizontal rule
        if line.startswith('---'):
            elements.append(Spacer(1, 0.2 * inch))
            i += 1
            continue
        
        # Section header (##) - must check before subsection
        if line.startswith('##') and not line.startswith('###'):
            header_text = line[2:].strip()
            # Escape HTML entities
            header_text = (
                header_text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
            )
            elements.append(Paragraph(f'<b>{header_text}</b>', section_style))
            i += 1
            continue
        
        # Subsection header (###)
        if line.startswith('###'):
            header_text = line[3:].strip()
            # Escape HTML entities
            header_text = (
                header_text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
            )
            elements.append(Paragraph(f'<b>{header_text}</b>', subsection_style))
            i += 1
            continue
        
        # Regular paragraph or list item
        # Collect multiple lines that form a paragraph
        paragraph_lines = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            # Stop at empty line, header (## or ###), or horizontal rule
            if not next_line or next_line.startswith('##') or next_line.startswith('---'):
                break
            paragraph_lines.append(next_line)
            i += 1
        
        # Join the paragraph lines
        paragraph_text = ' '.join(paragraph_lines)
        
        # Determine if it's a list item
        is_list_item = re.match(r'^\*\*\([a-z]\)\*\*', paragraph_text)
        
        # Parse markdown formatting
        # First, handle bold (**text**) - must be done before italic
        paragraph_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', paragraph_text)
        
        # Then handle italic (*text*) - but not ** which might be leftover
        # Split by <b> and </b> tags to avoid italicizing content inside bold tags
        parts = re.split(r'(<b>.*?</b>)', paragraph_text)
        for idx, part in enumerate(parts):
            if not part.startswith('<b>'):
                # Only process parts outside of bold tags
                parts[idx] = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', part)
        paragraph_text = ''.join(parts)
        
        # Escape remaining HTML entities
        # First, protect our tags
        paragraph_text = paragraph_text.replace('<b>', '___BOLD_START___')
        paragraph_text = paragraph_text.replace('</b>', '___BOLD_END___')
        paragraph_text = paragraph_text.replace('<i>', '___ITALIC_START___')
        paragraph_text = paragraph_text.replace('</i>', '___ITALIC_END___')
        
        # Escape entities
        paragraph_text = (
            paragraph_text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
        )
        
        # Restore our tags
        paragraph_text = paragraph_text.replace('___BOLD_START___', '<b>')
        paragraph_text = paragraph_text.replace('___BOLD_END___', '</b>')
        paragraph_text = paragraph_text.replace('___ITALIC_START___', '<i>')
        paragraph_text = paragraph_text.replace('___ITALIC_END___', '</i>')
        
        # Choose appropriate style
        style = list_item_style if is_list_item else body_style
        
        # Add the paragraph
        elements.append(Paragraph(paragraph_text, style))
    
    return elements


def generate_gender_report_pdf(
    chat_id_topic: str,
    documents: List[Dict[str, Any]],
    undownloadable_links: List[Dict[str, str]],
    run_type: str,
) -> Path:
    """
    Generate a formatted PDF report containing document excerpts and links.
    
    Args:
        chat_id_topic: Session ID for the pipeline run
        documents: List of document dicts with 'filename', 'ai_extraction', 'blob_url'
        undownloadable_links: List of failed downloads with 'url' and 'reason'
        run_type: "first" or "rerun"
    
    Returns:
        Path to the generated PDF file (in temp directory)
    """
    logger.info(f"[PDF GENERATOR] Starting PDF generation for session: {chat_id_topic}")
    logger.info(f"[PDF GENERATOR] Documents to include: {len(documents)}, Failed downloads: {len(undownloadable_links)}")
    
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    # Create temp file
    import tempfile
    temp_dir = Path(tempfile.gettempdir())
    pdf_path = temp_dir / f"{chat_id_topic}-report.pdf"
    
    logger.info(f"[PDF GENERATOR] PDF output path: {pdf_path}")
    
    # Create document
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72,
    )
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#003366'),
        spaceAfter=30,
        alignment=1,  # Center
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#003366'),
        spaceAfter=12,
        spaceBefore=12,
    )
    
    subheading_style = ParagraphStyle(
        'CustomSubHeading',
        parent=styles['Heading3'],
        fontSize=14,
        textColor=colors.HexColor('#006699'),
        spaceAfter=10,
        spaceBefore=10,
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=11,
        leading=14,
        spaceAfter=10,
    )
    
    doc_type_style = ParagraphStyle(
        'DocType',
        parent=styles['BodyText'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
        spaceAfter=6,
        fontName='Helvetica-Oblique',
    )
    
    page_ref_style = ParagraphStyle(
        'PageRef',
        parent=styles['BodyText'],
        fontSize=9,
        textColor=colors.HexColor('#888888'),
        spaceAfter=4,
        fontName='Helvetica-Oblique',
    )
    
    # Title page
    report_title = "Gender Reviewer Report"
    if run_type == "rerun":
        report_title += " (Updated)"
    
    elements.append(Spacer(1, 2 * inch))
    elements.append(Paragraph(report_title, title_style))
    elements.append(Spacer(1, 0.3 * inch))
    
    # Session info
    session_info = f"<b>Session ID:</b> {chat_id_topic}"
    elements.append(Paragraph(session_info, body_style))
    
    generation_time = datetime.now().strftime("%B %d, %Y at %H:%M:%S")
    time_info = f"<b>Generated:</b> {generation_time}"
    elements.append(Paragraph(time_info, body_style))
    
    doc_count_info = f"<b>Documents Processed:</b> {len(documents)}"
    elements.append(Paragraph(doc_count_info, body_style))
    
    elements.append(PageBreak())
    
    # Documents Section
    elements.append(Paragraph("Gender Provisions by Document", heading_style))
    elements.append(Spacer(1, 0.3 * inch))
    
    for idx, document in enumerate(documents, 1):
        filename = document.get("filename", "Unknown Document")
        blob_url = document.get("blob_url", "")
        source_url = blob_url or document.get("source_url", "")
        ai_extraction = document.get("ai_extraction", "No provision available")

        parsed = _parse_json_extraction(ai_extraction)
        if parsed:
            document_name, document_type, paragraphs_with_pages, case_studies = parsed
            doc_title = document_name or filename.replace(".pdf", "").replace(".PDF", "")
            elements.append(Paragraph(f"<b>{doc_title}</b>", subheading_style))
            
            # Display document type
            doc_type_labels = {
                "A": "Multilateral Environmental Agreement (MEA)",
                "B": "Gender Equality Global Agreement",
                "C": "National Environmental Law/Policy",
                "D": "National Gender Equality Law/Policy",
                "E": "Case Study"
            }
            type_label = doc_type_labels.get(document_type, f"Type {document_type}")
            elements.append(Paragraph(f"Document Type: {type_label}", doc_type_style))
            elements.append(Spacer(1, 0.1 * inch))

            if source_url:
                link_style = ParagraphStyle(
                    "Link",
                    parent=styles["BodyText"],
                    fontSize=9,
                    textColor=colors.HexColor("#0066cc"),
                    spaceAfter=12,
                )
                safe_url = source_url.replace("&", "&amp;")
                link_text = f'Source: <link href="{safe_url}" color="blue">{safe_url}</link>'
                elements.append(Paragraph(link_text, link_style))

            # Display paragraphs with page references
            if paragraphs_with_pages:
                for para_obj in paragraphs_with_pages:
                    text = para_obj.get("text", "")
                    page_number = para_obj.get("page_number")
                    
                    # Add page reference if available
                    if page_number is not None:
                        page_ref_text = f"(page {page_number})"
                        elements.append(Paragraph(page_ref_text, page_ref_style))
                    
                    # Render the paragraph text with markdown formatting
                    provision_elements = _parse_markdown_to_flowables(text, styles)
                    elements.extend(provision_elements)
            
            # Display case studies if present
            if case_studies:
                elements.append(Spacer(1, 0.2 * inch))
                elements.append(Paragraph("<b>Case Studies</b>", subheading_style))
                
                for cs in case_studies:
                    name = cs.get("name", "")
                    year = cs.get("year", "")
                    environmental_topic = cs.get("environmental_topic", "")
                    summary = cs.get("summary", "")
                    source = cs.get("source", "")
                    page_number = cs.get("page_number")
                    
                    # Case study name and metadata
                    if name:
                        cs_header = f"<b>{name}</b>"
                        if year:
                            cs_header += f" ({year})"
                        elements.append(Paragraph(cs_header, body_style))
                    
                    if environmental_topic:
                        elements.append(Paragraph(f"<i>Topic: {environmental_topic}</i>", body_style))
                    
                    if page_number is not None:
                        elements.append(Paragraph(f"(page {page_number})", page_ref_style))
                    
                    if summary:
                        # Render summary with markdown formatting
                        summary_elements = _parse_markdown_to_flowables(summary, styles)
                        elements.extend(summary_elements)
                    
                    if source:
                        # Make source clickable if it's a URL
                        if source.startswith("http://") or source.startswith("https://"):
                            safe_source = source.replace("&", "&amp;")
                            source_text = f'Source: <link href="{safe_source}" color="blue">{safe_source}</link>'
                        else:
                            source_text = f"Source: {source}"
                        elements.append(Paragraph(source_text, link_style))
                    
                    elements.append(Spacer(1, 0.15 * inch))
            
            # Show message if no content found
            if not paragraphs_with_pages and not case_studies:
                elements.append(
                    Paragraph(
                        "<i>No relevant gender-related provisions found.</i>",
                        body_style,
                    )
                )
        else:
            # Legacy markdown/plain-text extraction fallback
            doc_title = (
                filename.replace(".pdf", "")
                .replace(".PDF", "")
                .replace("-", " ")
                .replace("_", " ")
                .upper()
            )
            elements.append(Paragraph(f"<b>{doc_title}</b>", subheading_style))
            elements.append(Spacer(1, 0.1 * inch))

            if blob_url:
                link_style = ParagraphStyle(
                    "Link",
                    parent=styles["BodyText"],
                    fontSize=9,
                    textColor=colors.HexColor("#0066cc"),
                    spaceAfter=12,
                )
                safe_url = blob_url.replace("&", "&amp;")
                link_text = f"<u>{safe_url}</u>"
                elements.append(Paragraph(link_text, link_style))

            provision_elements = _parse_markdown_to_flowables(ai_extraction, styles)
            elements.extend(provision_elements)

        elements.append(Spacer(1, 0.4 * inch))
    
    # Failed Downloads Section (if any) - list URLs only without reasons
    if undownloadable_links:
        elements.append(PageBreak())
        elements.append(Paragraph("Failed Downloads", heading_style))
        elements.append(Spacer(1, 0.2 * inch))
        
        failed_text = "The following documents could not be downloaded:<br/><br/>"
        elements.append(Paragraph(failed_text, body_style))
        
        for failed in undownloadable_links:
            url = failed.get('url', 'Unknown URL')
            failed_item = f'<b>URL:</b> {url}<br/><br/>'
            elements.append(Paragraph(failed_item, body_style))
    
    # Build PDF
    try:
        doc.build(elements)
        logger.info(f"PDF report generated successfully: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"Failed to build PDF: {e}")
        raise
