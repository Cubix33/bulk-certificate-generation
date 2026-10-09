"""Renders one certificate PDF from the single predefined template."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


def render_certificate(path, *, recipient_name: str, title: str, issuer: str, issue_date: str) -> None:
    width, height = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=landscape(A4))

    # Template: double border, heading, recipient, course, footer.
    c.setStrokeColor(colors.HexColor("#1f3a5f"))
    c.setLineWidth(6)
    c.rect(25, 25, width - 50, height - 50)
    c.setLineWidth(1.5)
    c.rect(38, 38, width - 76, height - 76)

    c.setFillColor(colors.HexColor("#1f3a5f"))
    c.setFont("Helvetica-Bold", 40)
    c.drawCentredString(width / 2, height - 140, "Certificate of Completion")

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 200, "This is to certify that")

    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(width / 2, height - 260, recipient_name)

    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 310, "has successfully completed")

    c.setFont("Helvetica-BoldOblique", 24)
    c.drawCentredString(width / 2, height - 355, title)

    c.setFont("Helvetica", 14)
    c.drawString(90, 90, f"Date: {issue_date}")
    c.drawRightString(width - 90, 90, f"Issued by: {issuer}")

    c.showPage()
    c.save()
