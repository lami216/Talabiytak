from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.config import Settings
from app.services.errors import ImageProcessingError


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    mime_type: str
    extension: str
    width: int
    height: int
    sha256: str
    original_format: str
    normalized_format: str


class ImageProcessingService:
    def __init__(self, settings: Settings):
        self.settings = settings
        Image.MAX_IMAGE_PIXELS = settings.image_max_pixels

    def process(self, data: bytes) -> ProcessedImage:
        if not data or len(data) > self.settings.max_single_image_mb * 1024 * 1024:
            raise ImageProcessingError("حجم الصورة غير صالح أو يتجاوز الحد المسموح")
        try:
            with BytesIO(data) as source, Image.open(source) as opened:
                opened.load()
                original = (opened.format or "").upper()
                formats = {
                    "PNG": ("png", "image/png"),
                    "JPEG": ("jpg", "image/jpeg"),
                    "WEBP": ("webp", "image/webp"),
                    "GIF": ("gif", "image/gif"),
                }
                if original not in formats:
                    raise ImageProcessingError("تنسيق الصورة غير مدعوم")
                if (
                    opened.width > self.settings.image_max_width
                    or opened.height > self.settings.image_max_height
                    or opened.width * opened.height > self.settings.image_max_pixels
                ):
                    raise ImageProcessingError("أبعاد الصورة تتجاوز الحد المسموح")
                width, height = opened.width, opened.height
                extension, mime_type = formats[original]

                # Pillow is used only to validate the image. Re-encoding here used to change PNG,
                # WEBP and GIF files (often into JPEG), alter their byte size, discard metadata,
                # and make the ImageKit object differ from the workbook media. Upload the exact
                # bytes embedded in XLSX after validation instead.
                return ProcessedImage(
                    data,
                    mime_type,
                    extension,
                    width,
                    height,
                    sha256(data).hexdigest(),
                    original,
                    original,
                )
        except ImageProcessingError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageProcessingError("ملف الصورة تالف أو غير صالح") from exc
