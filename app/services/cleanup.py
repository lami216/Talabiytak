from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import ImageStatus, ImportedImage, Product


class ImportCleanupService:
    def __init__(self, imagekit):
        self.imagekit = imagekit

    def cleanup(self, s, images, dry_run=False):
        result = {"deleted": 0, "failed": 0, "skipped": 0}
        for image in images:
            if (
                image.status not in {ImageStatus.unnamed.value, ImageStatus.ignored.value}
                or image.linked_product_id
                or not image.imagekit_file_id
            ):
                result["skipped"] += 1
                continue
            refs = (
                s.scalar(
                    select(func.count(Product.id)).where(
                        Product.imagekit_file_id == image.imagekit_file_id
                    )
                )
                or 0
            ) + (
                s.scalar(
                    select(func.count(ImportedImage.id)).where(
                        ImportedImage.imagekit_file_id == image.imagekit_file_id,
                        ImportedImage.id != image.id,
                        ImportedImage.status != ImageStatus.deleted.value,
                    )
                )
                or 0
            )
            if refs:
                result["skipped"] += 1
                continue
            if not dry_run:
                try:
                    self.imagekit.delete(image.imagekit_file_id)
                    image.status = ImageStatus.deleted.value
                    image.imagekit_file_id = None
                    image.imagekit_file_path = None
                    image.image_url = None
                    image.thumbnail_url = None
                    s.commit()
                except Exception:
                    s.rollback()
                    result["failed"] += 1
                    continue
            result["deleted"] += 1
        return result

    def abandoned(self, s, days):
        return s.scalars(
            select(ImportedImage).where(
                ImportedImage.created_at < datetime.now(UTC) - timedelta(days=days),
                ImportedImage.status.in_([ImageStatus.unnamed.value, ImageStatus.ignored.value]),
            )
        ).all()
