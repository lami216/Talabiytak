import logging
import os
import tempfile
import zipfile
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BatchStatus, ImageStatus, ImportBatch, ImportedImage, Product
from app.services.errors import ImageProcessingError, UnsafeWorkbookError
from app.services.image_processing import ImageProcessingService
from app.services.imagekit import ImageKitService

log = logging.getLogger(__name__)


class ExcelImportService:
    def __init__(self, settings, processor: ImageProcessingService, imagekit: ImageKitService):
        self.settings = settings
        self.processor = processor
        self.imagekit = imagekit

    def import_upload(self, session: Session, filename: str, upload) -> ImportBatch:
        if not filename.lower().endswith(".xlsx"):
            raise UnsafeWorkbookError("يُسمح بملفات xlsx فقط")
        batch = ImportBatch(original_filename=os.path.basename(filename))
        session.add(batch)
        session.commit()
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp:
                path = temp.name
                total = 0
                while chunk := upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.max_excel_upload_mb * 1024 * 1024:
                        raise UnsafeWorkbookError("حجم ملف Excel يتجاوز الحد المسموح")
                    temp.write(chunk)
            try:
                self._process(session, batch, path)
            except zipfile.BadZipFile as exc:
                raise UnsafeWorkbookError("ملف xlsx ليس أرشيف ZIP صالحاً") from exc
            return batch
        except Exception as exc:
            session.rollback()
            batch = session.get(ImportBatch, batch.id)
            batch.status = BatchStatus.failed.value
            batch.error_message = str(exc)[:1000]
            session.commit()
            raise
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    def _validate(self, zf):
        infos = zf.infolist()
        if len(infos) > self.settings.max_zip_entries:
            raise UnsafeWorkbookError("عدد عناصر الأرشيف يتجاوز الحد المسموح")
        if sum(i.file_size for i in infos) > self.settings.max_uncompressed_import_mb * 1024 * 1024:
            raise UnsafeWorkbookError("الحجم غير المضغوط يتجاوز الحد المسموح")
        for i in infos:
            p = PurePosixPath(i.filename)
            if i.flag_bits & 1:
                raise UnsafeWorkbookError("ملفات Excel المشفرة غير مدعومة")
            if p.is_absolute() or ".." in p.parts or "\\" in i.filename:
                raise UnsafeWorkbookError("يحتوي الأرشيف على مسار غير آمن")
        return [i for i in infos if i.filename.startswith("xl/media/") and not i.is_dir()]

    def _process(self, session, batch, path):
        uploaded = []
        try:
            with zipfile.ZipFile(path) as zf:
                media = self._validate(zf)
                batch.total_media_entries = len(media)
                if len(media) > self.settings.max_images_per_import:
                    raise UnsafeWorkbookError("عدد الصور يتجاوز الحد المسموح")
                seen = {}
                for seq, info in enumerate(media, 1):
                    record = ImportedImage(
                        batch_id=batch.id,
                        sequence_number=seq,
                        original_media_name=info.filename,
                        status=ImageStatus.invalid_image.value,
                    )
                    session.add(record)
                    try:
                        if info.file_size > self.settings.max_single_image_mb * 1024 * 1024:
                            raise ImageProcessingError("حجم الصورة يتجاوز الحد المسموح")
                        processed = self.processor.process(zf.read(info))
                        record.sha256 = processed.sha256
                        record.mime_type = processed.mime_type
                        record.width = processed.width
                        record.height = processed.height
                        batch.valid_images += 1
                        product = session.scalar(
                            select(Product).where(Product.image_sha256 == processed.sha256).limit(1)
                        )
                        previous = session.scalar(
                            select(ImportedImage)
                            .where(
                                ImportedImage.sha256 == processed.sha256,
                                ImportedImage.id != record.id,
                                ImportedImage.imagekit_file_id.is_not(None),
                            )
                            .order_by(ImportedImage.id)
                            .limit(1)
                        )
                        source = product or seen.get(processed.sha256) or previous
                        if source:
                            record.imagekit_file_id = source.imagekit_file_id
                            record.imagekit_file_path = source.imagekit_file_path
                            record.image_url = source.image_url
                            record.thumbnail_url = source.thumbnail_url
                            record.status = ImageStatus.duplicate.value
                            record.duplicate_of_product_id = product.id if product else None
                            record.duplicate_of_imported_image_id = (
                                source.id if isinstance(source, ImportedImage) else None
                            )
                            batch.duplicate_images += 1
                        else:
                            asset = self.imagekit.upload(
                                processed.data, processed.extension, batch.uuid
                            )
                            uploaded.append(asset.file_id)
                            record.imagekit_file_id = asset.file_id
                            record.imagekit_file_path = asset.file_path
                            record.image_url = asset.url
                            record.thumbnail_url = asset.thumbnail_url
                            record.status = ImageStatus.unnamed.value
                            batch.uploaded_images += 1
                            session.flush()
                            seen[processed.sha256] = record
                    except ImageProcessingError as exc:
                        record.error_message = str(exc)
                        batch.skipped_images += 1
                        batch.failed_images += 1
                    except Exception as exc:
                        record.status = ImageStatus.upload_failed.value
                        record.error_message = str(exc)
                        batch.failed_images += 1
                batch.status = (
                    BatchStatus.partially_failed.value
                    if batch.failed_images
                    else BatchStatus.ready.value
                )
                from app.models.entities import now

                batch.completed_at = now()
                session.commit()
        except Exception:
            session.rollback()
            for file_id in uploaded:
                try:
                    self.imagekit.delete(file_id)
                except Exception:
                    log.exception("orphan cleanup failed", extra={"file_id": file_id})
            raise
