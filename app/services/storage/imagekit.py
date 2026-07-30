import asyncio
import logging
import uuid
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from urllib.parse import urlparse

import httpx
from imagekitio import ImageKit
from imagekitio.models.UpdateFileRequestOptions import UpdateFileRequestOptions
from PIL import Image, UnidentifiedImageError

from app.services.errors import ImageKitError, RemoteDeleteError

log = logging.getLogger(__name__)
UPLOAD_URL = "https://upload.imagekit.io/api/v1/files/upload"
FORMAT_METADATA = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}


@dataclass(frozen=True)
class StoredAsset:
    file_id: str
    file_path: str
    url: str
    thumbnail_url: str | None
    size: int | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None


class ImageKitStorage:
    def __init__(self, settings, client=None, upload_transport=None):
        self.settings = settings
        self.client = client or ImageKit(
            public_key=settings.imagekit_public_key,
            private_key=settings.imagekit_private_key,
            url_endpoint=settings.imagekit_url_endpoint,
        )
        self.upload_transport = upload_transport

    @property
    def files(self):
        return getattr(self.client, "file", getattr(self.client, "files", None))

    @staticmethod
    def _validate_file(data, extension, mime_type, expected_width, expected_height):
        if not data:
            raise ImageKitError("لا يمكن رفع صورة فارغة")
        try:
            with Image.open(BytesIO(data)) as image:
                detected = (image.format or "").upper()
                width, height = image.size
                metadata = FORMAT_METADATA.get(detected)
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageKitError("فشل التحقق المحلي من الصورة قبل الرفع") from exc
        if metadata != (extension, mime_type):
            raise ImageKitError("صيغة الصورة لا تطابق الامتداد أو MIME type المرسل")
        if (width, height) != (expected_width, expected_height):
            raise ImageKitError("أبعاد الصورة المحلية تغيرت قبل الرفع")

    async def upload(
        self,
        data: bytes,
        extension: str,
        mime_type: str,
        width: int,
        height: int,
        *,
        purpose="product",
        correlation_id=None,
    ):
        expected_size = len(data)
        expected_hash = sha256(data).hexdigest()
        self._validate_file(data, extension, mime_type, width, height)
        if len(data) != expected_size or sha256(data).hexdigest() != expected_hash:
            raise ImageKitError("تغيرت بيانات الصورة قبل الرفع")

        folder = (
            f"{self.settings.imagekit_folder}/imports/{correlation_id}"
            if purpose == "import"
            else f"{self.settings.imagekit_folder}/products"
        )
        tags = (
            ["product-image-manager", "imported-image", "unnamed"]
            if purpose == "import"
            else ["product-image-manager", "product"]
        )
        filename = f"{correlation_id or uuid.uuid4().hex}.{extension}"
        fields = {
            "fileName": filename,
            "folder": folder,
            "useUniqueFileName": "false",
            "tags": ",".join(tags),
        }
        last = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    auth=(self.settings.imagekit_private_key, ""),
                    transport=self.upload_transport,
                    timeout=30,
                ) as client:
                    response = await client.post(
                        UPLOAD_URL,
                        data=fields,
                        files={"file": (filename, data, mime_type)},
                    )
                response.raise_for_status()
                return self._asset_from_response(
                    response.json(), expected_size, width, height, mime_type
                )
            except ImageKitError:
                raise
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last = exc
                if attempt < 2:
                    await asyncio.sleep(0.15 * (attempt + 1))
        raise ImageKitError("فشل رفع الصورة إلى ImageKit") from last

    def _asset_from_response(self, raw, expected_size, expected_width, expected_height, mime_type):
        file_id, file_path, url = raw.get("fileId"), raw.get("filePath"), raw.get("url")
        parsed_url = urlparse(url or "")
        if (
            not file_id
            or not file_path
            or parsed_url.scheme != "https"
            or not parsed_url.netloc
            or raw.get("fileType") != "image"
        ):
            raise ImageKitError("استجابة ImageKit لا تحتوي على بيانات صورة صالحة")
        actual_size = raw.get("size")
        actual_width = raw.get("width")
        actual_height = raw.get("height")
        mismatch = (
            (actual_size is not None and actual_size != expected_size)
            or (actual_width is not None and actual_width != expected_width)
            or (actual_height is not None and actual_height != expected_height)
        )
        if mismatch:
            log.error(
                "ImageKit upload integrity mismatch",
                extra={
                    "file_id": file_id,
                    "expected_size": expected_size,
                    "actual_size": actual_size,
                    "expected_width": expected_width,
                    "actual_width": actual_width,
                    "expected_height": expected_height,
                    "actual_height": actual_height,
                },
            )
            try:
                self.files.delete(file_id=file_id)
            except Exception:
                log.exception(
                    "Failed to delete mismatched ImageKit upload", extra={"file_id": file_id}
                )
            raise ImageKitError("بيانات الصورة المرفوعة لا تطابق الملف الأصلي؛ تم رفض الرفع")
        return StoredAsset(
            file_id,
            file_path,
            self.settings.imagekit_delivery_url(file_path),
            raw.get("thumbnailUrl"),
            actual_size,
            actual_width,
            actual_height,
            raw.get("mime") or raw.get("mimeType") or mime_type,
        )

    async def delete(self, file_id):
        try:
            await asyncio.to_thread(self.files.delete, file_id=file_id)
        except Exception as exc:
            raise RemoteDeleteError("تعذر حذف الصورة من ImageKit، حاول مرة أخرى") from exc

    async def update_tags(self, file_id, tags):
        try:
            await asyncio.to_thread(
                self.files.update_file_details,
                file_id=file_id,
                options=UpdateFileRequestOptions(tags=tags),
            )
            return True
        except Exception:
            return False

    async def details(self, file_id):
        return await asyncio.to_thread(self.files.details, file_id=file_id)
