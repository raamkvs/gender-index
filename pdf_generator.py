"""PDF report generator for Gender Reviewer pipeline."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


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
        filename = document.get('filename', 'Unknown Document')
        blob_url = document.get('blob_url', '')
        ai_extraction = document.get('ai_extraction', 'No provision available')
        
        # Document name (without number, cleaner format)
        # Remove file extension if present
        doc_name = filename.replace('.pdf', '').replace('.PDF', '')
        doc_name_html = f'<b>{doc_name}</b>'
        
        elements.append(Paragraph(doc_name_html, subheading_style))
        elements.append(Spacer(1, 0.1 * inch))
        
        # Clean and format the provision text
        # Keep newlines as paragraph breaks for better readability
        provision_cleaned = (
            ai_extraction
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('\n\n', '<br/><br/>')  # Double newlines become paragraph breaks
            .replace('\n', ' ')  # Single newlines become spaces
        )
        
        # Add blob link at the end of the provision if available
        if blob_url:
            provision_cleaned += f'<br/><br/><font color="#0066cc" size="9"><u>{blob_url}</u></font>'
        
        elements.append(Paragraph(provision_cleaned, body_style))
        elements.append(Spacer(1, 0.4 * inch))
    
    # Failed Downloads Section (if any)
    if undownloadable_links:
        elements.append(PageBreak())
        elements.append(Paragraph("Failed Downloads", heading_style))
        elements.append(Spacer(1, 0.2 * inch))
        
        failed_text = "The following documents could not be downloaded:<br/><br/>"
        elements.append(Paragraph(failed_text, body_style))
        
        for failed in undownloadable_links:
            url = failed.get('url', 'Unknown URL')
            reason = failed.get('reason', 'Unknown reason')
            
            failed_item = f'<b>URL:</b> {url}<br/><b>Reason:</b> {reason}<br/><br/>'
            elements.append(Paragraph(failed_item, body_style))
    
    # Build PDF
    try:
        doc.build(elements)
        logger.info(f"PDF report generated successfully: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"Failed to build PDF: {e}")
        raise
