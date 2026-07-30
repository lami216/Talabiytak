import logging
import os
import tempfile
import zipfile
from pathlib import PurePosixPath

from app.models import ImageAsset, ImageStatus, ImportedImage, ImportStatus
from app.services.errors import ImageProcessingError, UnsafeWorkbookError
from app.utils.objectid import new_id

log = logging.getLogger(__name__)


class ImportService:
    def __init__(self, settings, processor, storage, imports, images, products, orphans):
        self.settings, self.processor, self.storage = settings, processor, storage
        self.imports, self.images, self.products, self.orphans = imports, images, products, orphans

    async def import_upload(self, filename, upload):
        if not filename.lower().endswith(".xlsx"):
            raise UnsafeWorkbookError("يُسمح بملفات xlsx فقط")
        item = await self.imports.create(os.path.basename(filename))
        await self.imports.update_status(
            item.id, ImportStatus.processing.value, processing_state={"stage": "extracting"}
        )
        path = None
        uploaded = []
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp:
                path, total = temp.name, 0
                while chunk := upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.max_excel_upload_mb * 1024 * 1024:
                        raise UnsafeWorkbookError("حجم ملف Excel يتجاوز الحد المسموح")
                    temp.write(chunk)
            counters, uploaded = await self._process(item.id, path)
            return await self.imports.update_status(
                item.id,
                ImportStatus.completed.value,
                counters=counters,
                processing_state={"stage": "completed"},
            )
        except zipfile.BadZipFile as exc:
            await self._failed(item.id, exc)
            raise UnsafeWorkbookError("ملف xlsx ليس أرشيف ZIP صالحاً") from exc
        except Exception as exc:
            await self._failed(item.id, exc)
            for file_id in uploaded:
                await self._rollback_asset(file_id, f"failed import {item.id}")
            raise
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    async def _failed(self, import_id, exc):
        await self.imports.update_status(
            import_id,
            ImportStatus.failed.value,
            errors=[str(exc)[:1000]],
            processing_state={"stage": "failed"},
        )

    def _validate(self, archive):
        infos = archive.infolist()
        if len(infos) > self.settings.max_zip_entries:
            raise UnsafeWorkbookError("عدد عناصر الأرشيف يتجاوز الحد المسموح")
        if sum(i.file_size for i in infos) > self.settings.max_uncompressed_import_mb * 1024 * 1024:
            raise UnsafeWorkbookError("الحجم غير المضغوط يتجاوز الحد المسموح")
        for info in infos:
            path = PurePosixPath(info.filename)
            if info.flag_bits & 1:
                raise UnsafeWorkbookError("ملفات Excel المشفرة غير مدعومة")
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise UnsafeWorkbookError("يحتوي الأرشيف على مسار غير آمن")
        return [i for i in infos if i.filename.startswith("xl/media/") and not i.is_dir()]

    async def _process(self, import_id, path):
        counters = {
            "total_media_entries": 0,
            "valid_images": 0,
            "uploaded_images": 0,
            "duplicate_images": 0,
            "skipped_images": 0,
            "failed_images": 0,
        }
        uploaded, seen = [], {}
        with zipfile.ZipFile(path) as archive:
            media = self._validate(archive)
            counters["total_media_entries"] = len(media)
            if len(media) > self.settings.max_images_per_import:
                raise UnsafeWorkbookError("عدد الصور يتجاوز الحد المسموح")
            for sequence, info in enumerate(media, 1):
                image = ImportedImage(
                    id=new_id(),
                    import_id=import_id,
                    sequence_number=sequence,
                    original_media_name=info.filename,
                )
                try:
                    if info.file_size > self.settings.max_single_image_mb * 1024 * 1024:
                        raise ImageProcessingError("حجم الصورة يتجاوز الحد المسموح")
                    processed = self.processor.process(archive.read(info))
                    image.hash, image.mime_type = processed.sha256, processed.mime_type
                    image.dimensions = {"width": processed.width, "height": processed.height}
                    counters["valid_images"] += 1
                    product = await self.products.find_by_hash(processed.sha256)
                    previous = seen.get(
                        processed.sha256
                    ) or await self.images.find_duplicate_by_hash(processed.sha256)
                    source = product or previous
                    if source:
                        image.image_asset = source.primary_image if product else source.image_asset
                        image.status = ImageStatus.duplicate.value
                        image.duplicate_of = {
                            "type": "product" if product else "imported_image",
                            "id": source.id,
                        }
                        counters["duplicate_images"] += 1
                    else:
                        stored = await self.storage.upload(
                            processed.data,
                            processed.extension,
                            purpose="import",
                            correlation_id=f"{import_id}-{sequence}-{processed.sha256[:12]}",
                        )
                        uploaded.append(stored.file_id)
                        image.image_asset = ImageAsset(
                            stored.file_id,
                            stored.file_path,
                            stored.url,
                            stored.thumbnail_url,
                            processed.sha256,
                            processed.mime_type,
                            processed.width,
                            processed.height,
                        )
                        image.status = ImageStatus.unnamed.value
                        counters["uploaded_images"] += 1
                        seen[processed.sha256] = image
                except ImageProcessingError as exc:
                    image.error_message = str(exc)
                    counters["skipped_images"] += 1
                    counters["failed_images"] += 1
                except Exception as exc:
                    image.status = ImageStatus.upload_failed.value
                    image.error_message = str(exc)
                    counters["failed_images"] += 1
                try:
                    await self.images.create(image)
                except Exception:
                    if image.image_asset and image.image_asset.file_id in uploaded:
                        await self._rollback_asset(
                            image.image_asset.file_id, "imported image save failed"
                        )
                        uploaded.remove(image.image_asset.file_id)
                    raise
        return counters, uploaded

    async def _rollback_asset(self, file_id, reason):
        try:
            await self.storage.delete(file_id)
        except Exception as exc:
            log.exception("ImageKit rollback failed", extra={"file_id": file_id})
            await self.orphans.record(file_id, f"{reason}: {exc}")

    async def list_imports(self, limit=100):
        return await self.imports.list(limit)

    async def get_batch(self, import_id, page=1, status="all"):
        item = await self.imports.get(import_id)
        if not item:
            return None
        return (
            item,
            await self.images.list_images(import_id, status, page),
            await self.images.status_counts(import_id),
        )

    async def ignore_image(self, image_id):
        image = await self.images.get(image_id)
        if image and not image.linked_product_id:
            await self.images.update_status(image_id, ImageStatus.ignored.value)
        return image

    async def get_image(self, image_id):
        return await self.images.get(image_id)
