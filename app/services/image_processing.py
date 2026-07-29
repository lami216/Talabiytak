from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

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
                if original not in {"PNG", "JPEG", "WEBP", "GIF"}:
                    raise ImageProcessingError("تنسيق الصورة غير مدعوم")
                if original == "GIF" and getattr(opened, "n_frames", 1) > 1:
                    raise ImageProcessingError("صور GIF المتحركة غير مدعومة")
                if (
                    opened.width > self.settings.image_max_width
                    or opened.height > self.settings.image_max_height
                    or opened.width * opened.height > self.settings.image_max_pixels
                ):
                    raise ImageProcessingError("أبعاد الصورة تتجاوز الحد المسموح")
                image = ImageOps.exif_transpose(opened).copy()
            try:
                has_alpha = image.mode in ("RGBA", "LA") or (
                    image.mode == "P" and "transparency" in image.info
                )
                output = BytesIO()
                if has_alpha:
                    normalized = image.convert("RGBA")
                    fmt, ext, mime = "PNG", "png", "image/png"
                    normalized.save(output, "PNG", optimize=True)
                else:
                    normalized = image.convert("RGB")
                    fmt, ext, mime = "JPEG", "jpg", "image/jpeg"
                    normalized.save(output, "JPEG", quality=90, optimize=True, progressive=True)
                normalized.close()
                payload = output.getvalue()
                output.close()
                return ProcessedImage(
                    payload,
                    mime,
                    ext,
                    image.width,
                    image.height,
                    sha256(payload).hexdigest(),
                    original,
                    fmt,
                )
            finally:
                image.close()
        except ImageProcessingError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageProcessingError("ملف الصورة تالف أو غير صالح") from exc
