import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath

from app.models import ImageAsset, ImageStatus, ImportedImage, ImportStatus
from app.services.errors import ImageProcessingError, UnsafeWorkbookError, ValidationError
from app.utils.objectid import new_id

log = logging.getLogger(__name__)


@dataclass
class DirectImageSource:
    filename: str
    upload: object


class ImportService:
    def __init__(self, settings, processor, storage, imports, images, products, orphans):
        self.settings, self.processor, self.storage = settings, processor, storage
        self.imports, self.images, self.products, self.orphans = imports, images, products, orphans

    async def import_upload(self, filename, upload):
        return await self.import_sources(filename, upload, [])

    async def import_sources(self, excel_filename=None, excel_upload=None, direct_images=None):
        direct_images = [image for image in (direct_images or []) if getattr(image, "filename", "")]
        excel_filename = excel_filename or ""
        if not excel_filename and not direct_images:
            raise ValidationError("اختر ملف Excel أو صورة واحدة على الأقل")
        if excel_filename and not excel_filename.lower().endswith(".xlsx"):
            raise UnsafeWorkbookError("يُسمح بملفات xlsx فقط")
        batch_name = self._batch_name(excel_filename, len(direct_images))
        item = await self.imports.create(batch_name)
        await self.imports.update_status(
            item.id, ImportStatus.processing.value, processing_state={"stage": "extracting"}
        )
        path = None
        uploaded = []
        try:
            if excel_upload:
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp:
                    path, total = temp.name, 0
                    while chunk := excel_upload.read(1024 * 1024):
                        total += len(chunk)
                        if total > self.settings.max_excel_upload_mb * 1024 * 1024:
                            raise UnsafeWorkbookError("حجم ملف Excel يتجاوز الحد المسموح")
                        temp.write(chunk)
            counters, uploaded = await self._process_sources(item.id, path, direct_images)
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
            for file_id in list(uploaded):
                await self._rollback_asset(file_id, f"failed import {item.id}")
            raise
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    def _batch_name(self, excel_filename, image_count):
        safe_excel = os.path.basename(excel_filename) if excel_filename else ""
        if safe_excel and image_count:
            return f"{safe_excel} + {image_count} صور مباشرة"
        if safe_excel:
            return safe_excel
        return f"صور مرفوعة مباشرة — {image_count} صور"

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
        return await self._process_sources(import_id, path, [])

    async def _process_sources(self, import_id, path, direct_images):
        counters = self._empty_counters()
        uploaded, seen = [], {}
        sequence = 0
        if path:
            with zipfile.ZipFile(path) as archive:
                media = self._validate(archive)
                counters["total_media_entries"] += len(media)
                if counters["total_media_entries"] > self.settings.max_images_per_import:
                    raise UnsafeWorkbookError("عدد الصور يتجاوز الحد المسموح")
                for info in media:
                    sequence += 1
                    try:
                        if info.file_size > self.settings.max_single_image_mb * 1024 * 1024:
                            raise ImageProcessingError("حجم الصورة يتجاوز الحد المسموح")
                        original_data = archive.read(info)
                    except ImageProcessingError as exc:
                        await self._record_failed_image(
                            import_id, sequence, info.filename, exc, counters
                        )
                        continue
                    await self._process_image_bytes(
                        import_id=import_id,
                        sequence_number=sequence,
                        original_name=info.filename,
                        original_data=original_data,
                        seen=seen,
                        uploaded=uploaded,
                        counters=counters,
                    )
        counters["total_media_entries"] += len(direct_images)
        if counters["total_media_entries"] > self.settings.max_images_per_import:
            raise UnsafeWorkbookError("عدد الصور يتجاوز الحد المسموح")
        for source in direct_images:
            sequence += 1
            name = self._safe_media_name(getattr(source, "filename", "image"))
            try:
                original_data = await self._read_direct_image(source)
            except ImageProcessingError as exc:
                await self._record_failed_image(import_id, sequence, name, exc, counters)
                continue
            await self._process_image_bytes(
                import_id=import_id,
                sequence_number=sequence,
                original_name=name,
                original_data=original_data,
                seen=seen,
                uploaded=uploaded,
                counters=counters,
            )
        return counters, uploaded

    def _empty_counters(self):
        return {
            "total_media_entries": 0,
            "valid_images": 0,
            "uploaded_images": 0,
            "duplicate_images": 0,
            "skipped_images": 0,
            "failed_images": 0,
        }

    async def _read_direct_image(self, source):
        limit = self.settings.max_direct_image_upload_mb * 1024 * 1024
        data = await source.read(limit + 1)
        if len(data) > limit:
            raise ImageProcessingError(
                "حجم الصورة يتجاوز الحد المسموح "
                f"({self.settings.max_direct_image_upload_mb} ميجابايت)"
            )
        return data

    def _safe_media_name(self, name):
        return os.path.basename((name or "image").replace("\\", "/"))[:255] or "image"

    async def _record_failed_image(self, import_id, sequence, name, exc, counters):
        image = ImportedImage(
            id=new_id(),
            import_id=import_id,
            sequence_number=sequence,
            original_media_name=self._safe_media_name(name),
            status=ImageStatus.invalid_image.value,
            error_message=str(exc),
        )
        counters["skipped_images"] += 1
        counters["failed_images"] += 1
        await self.images.create(image)

    async def _process_image_bytes(
        self, *, import_id, sequence_number, original_name, original_data, seen, uploaded, counters
    ):
        image = ImportedImage(
            id=new_id(),
            import_id=import_id,
            sequence_number=sequence_number,
            original_media_name=self._safe_media_name(original_name),
        )
        try:
            processed = self.processor.process(original_data)
            if (
                not processed.data
                or len(processed.data) != len(original_data)
                or processed.sha256 != sha256(original_data).hexdigest()
            ):
                raise ImageProcessingError("تغيرت بيانات الصورة الأصلية أثناء المعالجة")
            image.hash, image.mime_type = processed.sha256, processed.mime_type
            image.dimensions = {"width": processed.width, "height": processed.height}
            counters["valid_images"] += 1
            product = await self.products.find_by_hash(processed.sha256)
            previous = seen.get(processed.sha256) or await self.images.find_duplicate_by_hash(
                processed.sha256
            )
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
                    processed.mime_type,
                    processed.width,
                    processed.height,
                    purpose="import",
                    correlation_id=f"{import_id}-{sequence_number}-{processed.sha256[:12]}",
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
                    stored.size if stored.size is not None else len(processed.data),
                )
                image.status = ImageStatus.unnamed.value
                counters["uploaded_images"] += 1
                seen[processed.sha256] = image
        except ImageProcessingError as exc:
            image.error_message = str(exc)
            counters["skipped_images"] += 1
            counters["failed_images"] += 1
        except Exception:
            image.status = ImageStatus.upload_failed.value
            image.error_message = "تعذر رفع الصورة أو حفظها"
            counters["failed_images"] += 1
            log.exception(
                "image import failed", extra={"import_id": import_id, "sequence": sequence_number}
            )
        try:
            await self.images.create(image)
        except Exception:
            if image.image_asset and image.image_asset.file_id in uploaded:
                await self._rollback_asset(image.image_asset.file_id, "imported image save failed")
                uploaded.remove(image.image_asset.file_id)
            raise

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

    async def delete_imported_image(self, image_id):
        image = await self.images.get(image_id)
        if not image:
            raise ValidationError("الصورة غير موجودة")
        if image.linked_product_id or image.status == ImageStatus.saved_as_product.value:
            raise ValidationError(
                "لا يمكن حذف هذه الصورة لأنها مرتبطة بمنتج محفوظ. "
                "احذف المنتج من صفحة المنتجات أولًا."
            )
        if image.status not in {ImageStatus.unnamed.value, ImageStatus.duplicate.value}:
            raise ValidationError("لا يمكن حذف هذه الصورة من صفحة الدفعة.")
        import_id = image.import_id
        file_id = image.image_asset.file_id if image.image_asset else None
        shared_asset = True
        storage_deleted = False
        if file_id:
            references = await self.products.asset_references(
                file_id
            ) + await self.images.asset_references(file_id, exclude_id=image.id)
            shared_asset = references > 0
            if not shared_asset:
                await self.storage.delete(file_id)
                storage_deleted = True
        try:
            result = await self.images.delete(image.id)
            record_deleted = getattr(result, "deleted_count", 0) > 0
        except Exception:
            log.exception(
                "Imported image record delete failed after storage cleanup",
                extra={"image_id": image.id},
            )
            await self.images.mark_deleted(image.id)
            record_deleted = True
        return {
            "import_id": import_id,
            "record_deleted": record_deleted,
            "storage_deleted": storage_deleted,
            "shared_asset": shared_asset,
        }

    async def ignore_image(self, image_id):
        return await self.images.get(image_id)

    async def get_image(self, image_id):
        return await self.images.get(image_id)
