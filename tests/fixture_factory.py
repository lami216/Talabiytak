"""Generate valid XLSX test workbooks without committing binary archives."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image


def image_bytes(image_format: str, color: str) -> bytes:
    """Create a small deterministic image for an XLSX media entry."""
    output = BytesIO()
    with Image.new("RGB", (32, 24), color) as image:
        image.save(output, image_format)
    return output.getvalue()


def embedded_images_xlsx() -> bytes:
    """Return a real XLSX ZIP containing PNG, JPEG, and WEBP media entries."""
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Default Extension="webp" ContentType="image/webp"/>
</Types>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>""",
        )
        archive.writestr("xl/media/image1.png", image_bytes("PNG", "red"))
        archive.writestr("xl/media/image2.jpg", image_bytes("JPEG", "blue"))
        archive.writestr("xl/media/image3.webp", image_bytes("WEBP", "green"))
    return output.getvalue()
