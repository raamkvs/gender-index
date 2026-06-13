"""PDF report generator for Gender Reviewer pipeline."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def generate_gender_report_pdf(
    chat_id_topic: str,
    ai_extractions: List[str],
    documents_processed: int,
    run_type: str,
) -> Path:
    """
    Generate a formatted PDF report containing all AI extractions.
    
    Args:
        chat_id_topic: Session ID for the pipeline run
        ai_extractions: List of AI extraction texts from documents
        documents_processed: Number of documents successfully processed
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
    
    elements.append(PageBreak())
    
    # Executive Summary
    elements.append(Paragraph("Executive Summary", heading_style))
    summary_text = f"""
    This report contains gender-related analysis from {len(ai_extractions)} policy document(s) 
    processed through the UNDP Gender Reviewer pipeline. The analysis identifies gender provisions, 
    gaps, and alignment with international frameworks such as CEDAW, the Beijing Platform for Action, 
    and SDG 5.
    """
    elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 0.2 * inch))
    
    # Document Overview
    elements.append(Paragraph("Document Overview", heading_style))
    
    overview_data = [
        ["Metric", "Count"],
        ["Documents Processed", str(documents_processed)],
        ["Total Extractions", str(len(ai_extractions))],
        ["Run Type", run_type.capitalize()],
    ]
    
    overview_table = Table(overview_data, colWidths=[3 * inch, 2 * inch])
    overview_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    elements.append(overview_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Gender Provisions Found
    elements.append(Paragraph("Gender Provisions Analysis", heading_style))
    elements.append(Spacer(1, 0.1 * inch))
    
    for idx, extraction in enumerate(ai_extractions, 1):
        # Subheading for each document
        doc_heading = f"Document {idx}"
        elements.append(Paragraph(doc_heading, subheading_style))
        
        # Clean and format the extraction text
        # Escape HTML special characters
        extraction_cleaned = (
            extraction
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('\n', '<br/>')
        )
        
        # Wrap long lines
        if len(extraction_cleaned) > 5000:
            extraction_cleaned = extraction_cleaned[:5000] + "...<br/><i>[Extraction truncated for brevity]</i>"
        
        elements.append(Paragraph(extraction_cleaned, body_style))
        elements.append(Spacer(1, 0.2 * inch))
    
    # Gender Gaps Section
    elements.append(PageBreak())
    elements.append(Paragraph("Gender Gaps Identified", heading_style))
    gaps_text = """
    Based on the analysis of the provided documents, gender gaps may include:
    <br/><br/>
    <b>1. Representation Gaps:</b> Limited mention of women's participation in decision-making processes
    or leadership roles.<br/><br/>
    <b>2. Data Gaps:</b> Insufficient sex-disaggregated data for monitoring and evaluation.<br/><br/>
    <b>3. Budget Allocation:</b> Lack of specific budget allocations for gender-responsive programs.<br/><br/>
    <b>4. Implementation Mechanisms:</b> Absence of clear implementation strategies for gender commitments.
    """
    elements.append(Paragraph(gaps_text, body_style))
    elements.append(Spacer(1, 0.2 * inch))
    
    # Framework Alignment
    elements.append(Paragraph("Framework Alignment", heading_style))
    framework_text = """
    <b>CEDAW (Convention on the Elimination of All Forms of Discrimination Against Women):</b><br/>
    Review document provisions against CEDAW articles, particularly Articles 2, 3, and 7 related to 
    policy measures, guarantees of rights, and political participation.<br/><br/>
    
    <b>Beijing Platform for Action:</b><br/>
    Assess alignment with the 12 critical areas of concern, especially regarding women in power and 
    decision-making, and institutional mechanisms for advancement.<br/><br/>
    
    <b>SDG 5 (Gender Equality):</b><br/>
    Evaluate how the documents support SDG 5 targets, including ending discrimination, ensuring 
    participation and leadership, and adopting sound policies for gender equality.
    """
    elements.append(Paragraph(framework_text, body_style))
    elements.append(Spacer(1, 0.2 * inch))
    
    # Recommendations
    elements.append(Paragraph("Recommendations", heading_style))
    recommendations_text = """
    <b>1. Strengthen Gender Mainstreaming:</b> Integrate gender considerations across all policy areas
    and ensure gender impact assessments are conducted.<br/><br/>
    
    <b>2. Enhance Monitoring Systems:</b> Develop robust systems for tracking gender-related indicators
    with sex-disaggregated data collection.<br/><br/>
    
    <b>3. Allocate Adequate Resources:</b> Ensure sufficient budget allocations for gender equality 
    initiatives with clear accountability mechanisms.<br/><br/>
    
    <b>4. Build Institutional Capacity:</b> Invest in training and capacity building for government 
    officials on gender-responsive policy making.<br/><br/>
    
    <b>5. Engage Stakeholders:</b> Foster inclusive consultation processes with women's organizations 
    and civil society in policy development and implementation.
    """
    elements.append(Paragraph(recommendations_text, body_style))
    
    # Footer note
    elements.append(Spacer(1, 0.5 * inch))
    footer_text = """
    <i>Note: This report is automatically generated by the UNDP Gender Reviewer Pipeline. 
    The analysis is based on AI extraction of policy documents and should be reviewed by 
    gender experts for comprehensive assessment.</i>
    """
    elements.append(Paragraph(footer_text, body_style))
    
    # Build PDF
    try:
        doc.build(elements)
        logger.info(f"PDF report generated successfully: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"Failed to build PDF: {e}")
        raise
