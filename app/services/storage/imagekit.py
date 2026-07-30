import asyncio
import time
import uuid
from dataclasses import dataclass

from imagekitio import ImageKit
from imagekitio.models.UpdateFileRequestOptions import UpdateFileRequestOptions
from imagekitio.models.UploadFileRequestOptions import UploadFileRequestOptions

from app.services.errors import ImageKitError, RemoteDeleteError


@dataclass(frozen=True)
class StoredAsset:
    file_id: str
    file_path: str
    url: str
    thumbnail_url: str | None


class ImageKitStorage:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or ImageKit(
            public_key=settings.imagekit_public_key,
            private_key=settings.imagekit_private_key,
            url_endpoint=settings.imagekit_url_endpoint,
        )

    @property
    def files(self):
        return getattr(self.client, "file", getattr(self.client, "files", None))

    async def upload(self, data: bytes, extension: str, *, purpose="product", correlation_id=None):
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
        # A deterministic name plus overwrite semantics makes a timed-out upload retry safe.
        options = UploadFileRequestOptions(folder=folder, tags=tags, use_unique_file_name=False)
        filename = f"{correlation_id or uuid.uuid4().hex}.{extension}"

        def call():
            last = None
            for attempt in range(3):
                try:
                    result = self.files.upload(file=data, file_name=filename, options=options)
                    raw = getattr(getattr(result, "response_metadata", None), "raw", {})
                    return StoredAsset(
                        getattr(result, "file_id", raw.get("fileId")),
                        getattr(result, "file_path", raw.get("filePath")),
                        getattr(result, "url", raw.get("url")),
                        getattr(result, "thumbnail_url", raw.get("thumbnailUrl") or raw.get("url")),
                    )
                except Exception as exc:
                    last = exc
                    if attempt < 2:
                        time.sleep(0.15 * (attempt + 1))
            raise ImageKitError("فشل رفع الصورة إلى ImageKit") from last

        return await asyncio.to_thread(call)

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
