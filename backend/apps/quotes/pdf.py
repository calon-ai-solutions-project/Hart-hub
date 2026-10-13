"""Tidy Codeweavers' quote document: where it shows its grey "Image not available" box, show the
standard no-vehicle picture instead. Nothing else in the document is touched: every figure, the
wording and the layout stay exactly as Codeweavers produced them.
"""

import hashlib
import io
import logging
from pathlib import Path

from PIL import ImageStat
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

NO_VEHICLE_IMAGE = Path(__file__).parent / "assets" / "no-vehicle-image.png"
# Codeweavers' "Image not available" box, by its pixels (how the file is compressed can vary).
PLACEHOLDER_SIZE = (354, 200)
PLACEHOLDER_PIXELS = "87fa30674a26cc1553b5007c396ba408f9acfced8682cd6f160b6441ba7af422"


def is_placeholder(image):
    """Is this picture Codeweavers' grey "Image not available" box (and not a photo of the car)?"""
    if image.size != PLACEHOLDER_SIZE:
        return False
    rgb = image.convert("RGB")
    if hashlib.sha256(rgb.tobytes()).hexdigest() == PLACEHOLDER_PIXELS:
        return True
    # a re-drawn version of the same box: pure grey from edge to edge, which no car photo is
    low, high = zip(*ImageStat.Stat(rgb).extrema)
    return max(high) - min(low) < 60 and all(abs(a - b) < 3 for a, b in zip(low[1:] + high[1:], low[:-1] + high[:-1]))


def placeholder_boxes(page):
    """[(x, y, width, height)] in PDF points for each placeholder on a page."""
    images = {f"/{image.name.rsplit('.', 1)[0]}": image for image in page.images}
    placed = []

    def note(operator, operands, matrix, text_matrix):
        if operator == b"Do" and operands and str(operands[0]) in images:
            placed.append((str(operands[0]), [float(value) for value in matrix]))

    page.extract_text(visitor_operand_before=note)
    boxes = []
    for name, (width, skew_y, skew_x, height, x, y) in placed:
        if skew_x or skew_y or width <= 0 or height <= 0:
            continue  # only a plain upright picture is replaced
        if is_placeholder(images[name].image):
            boxes.append((x, y, width, height))
    return boxes


def with_vehicle_image(pdf):
    """The same PDF with the no-vehicle picture in place of "Image not available".

    Returns the original bytes untouched when there is nothing to replace or anything goes wrong.
    """
    try:
        reader = PdfReader(io.BytesIO(pdf))
        writer = PdfWriter()
        changed = False
        picture = ImageReader(str(NO_VEHICLE_IMAGE))
        picture_width, picture_height = picture.getSize()
        for page in reader.pages:
            boxes = placeholder_boxes(page)
            if boxes:
                layer = io.BytesIO()
                sheet = canvas.Canvas(layer, pagesize=(float(page.mediabox.width), float(page.mediabox.height)))
                for x, y, width, height in boxes:
                    sheet.setFillColorRGB(1, 1, 1)
                    sheet.rect(x - 0.5, y - 0.5, width + 1, height + 1, stroke=0, fill=1)  # cover the grey box
                    scale = min(width / picture_width, height / picture_height)
                    drawn_width, drawn_height = picture_width * scale, picture_height * scale
                    sheet.drawImage(picture, x + (width - drawn_width) / 2, y + (height - drawn_height) / 2,
                                    drawn_width, drawn_height, mask="auto")
                sheet.save()
                page.merge_page(PdfReader(io.BytesIO(layer.getvalue())).pages[0])
                changed = True
            writer.add_page(page)
        if not changed:
            return pdf
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception as e:
        logger.warning("Quote PDF kept as Codeweavers made it; the picture was not replaced (%s)", type(e).__name__)
        return pdf
