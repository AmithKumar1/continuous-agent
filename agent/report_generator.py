import io
from datetime import datetime, timezone
from typing import Any, Dict, List

def generate_executive_pdf(
    scan_results: Dict[str, Any],
    iteration: int = 1
) -> io.BytesIO:
    """Generates an executive PDF report using ReportLab in pure Python."""
    buffer = io.BytesIO()
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        story = []

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Title"],
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#0f172a")
        )
        story.append(Paragraph("Autonomous Security & Discovery Audit", title_style))
        story.append(Spacer(1, 10))

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        meta_p = Paragraph(f"<b>Cycle:</b> #{iteration} &nbsp;|&nbsp; <b>Timestamp:</b> {ts}", styles["Normal"])
        story.append(meta_p)
        story.append(Spacer(1, 15))

        data = [["Property", "Value"]]
        for k, v in scan_results.items():
            data.append([str(k), str(v)[:80]])

        t = Table(data, colWidths=[150, 350])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1"))
        ]))
        story.append(t)

        doc.build(story)
        buffer.seek(0)
    except ImportError:
        buffer.write(b"%PDF-1.4 Mock PDF (reportlab not installed)")
        buffer.seek(0)

    return buffer
