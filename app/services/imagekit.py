import time
import uuid
from dataclasses import dataclass
from io import BytesIO

from app.config import Settings
from app.services.errors import ImageKitError, RemoteDeleteError


@dataclass(frozen=True)
class Asset:
    file_id: str
    file_path: str
    url: str
    thumbnail_url: str | None


class ImageKitService:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        if client is None:
            from imagekitio import ImageKit

            client = ImageKit(
                public_key=settings.imagekit_public_key,
                private_key=settings.imagekit_private_key,
                url_endpoint=settings.imagekit_url_endpoint,
            )
        self.client = client

    def upload(
        self, data: bytes | BytesIO, extension: str, batch_uuid: str | None = None, tags=None
    ) -> Asset:
        from imagekitio.models.UploadFileRequestOptions import UploadFileRequestOptions

        payload = data.getvalue() if isinstance(data, BytesIO) else data
        if not isinstance(payload, bytes):
            raise ImageKitError("تعذر تجهيز الصورة للرفع")
        filename = f"{uuid.uuid4().hex}.{extension}"
        folder = (
            f"{self.settings.imagekit_folder}/imports/{batch_uuid}"
            if batch_uuid
            else f"{self.settings.imagekit_folder}/products"
        )
        options = UploadFileRequestOptions(
            folder=folder,
            tags=tags or ["product-image-manager", "imported-image", "unnamed"],
            use_unique_file_name=True,
        )
        last = None
        for attempt in range(3):
            try:
                result = self.client.file.upload(file=payload, file_name=filename, options=options)
                raw = getattr(result, "response_metadata", None)
                raw = getattr(raw, "raw", None) or result

                def get(k, response=raw):
                    return (
                        response.get(k)
                        if isinstance(response, dict)
                        else getattr(response, k, None)
                    )

                return Asset(
                    get("fileId") or get("file_id"),
                    get("filePath") or get("file_path"),
                    get("url"),
                    get("thumbnailUrl") or get("thumbnail_url") or get("url"),
                )
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(0.15 * (attempt + 1))
        raise ImageKitError("فشل رفع الصورة إلى ImageKit") from last

    def delete(self, file_id: str):
        try:
            self.client.file.delete(file_id=file_id)
        except Exception as exc:
            raise RemoteDeleteError("تعذر حذف الصورة من ImageKit، حاول مرة أخرى") from exc

    def update_tags(self, file_id: str, tags: list[str]):
        from imagekitio.models.UpdateFileRequestOptions import UpdateFileRequestOptions

        try:
            self.client.file.update_file_details(
                file_id=file_id,
                options=UpdateFileRequestOptions(tags=tags),
            )
        except Exception:
            return False
        return True

    def details(self, file_id: str):
        return self.client.file.details(file_id=file_id)
