from datetime import UTC, datetime, timedelta

from app.models import ImageStatus


class ImportCleanupService:
    def __init__(self, storage, products, images):
        self.storage, self.products, self.images = storage, products, images

    async def cleanup(self, images, dry_run=False):
        result = {"deleted": 0, "failed": 0, "skipped": 0}
        for image in images:
            if (
                image.status not in {ImageStatus.unnamed.value, ImageStatus.ignored.value}
                or image.linked_product_id
                or not image.image_asset
            ):
                result["skipped"] += 1
                continue
            file_id = image.image_asset.file_id
            refs = await self.products.asset_references(
                file_id
            ) + await self.images.asset_references(file_id, image.id)
            if refs:
                result["skipped"] += 1
                continue
            if not dry_run:
                try:
                    await self.storage.delete(file_id)
                    image.status, image.image_asset = ImageStatus.deleted.value, None
                    await self.images.update(image)
                except Exception:
                    result["failed"] += 1
                    continue
            result["deleted"] += 1
        return result

    async def cleanup_import(self, import_id, dry_run=False):
        return await self.cleanup(await self.images.list_images(import_id, size=10000), dry_run)

    async def cleanup_abandoned(self, days, dry_run=False):
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return await self.cleanup(await self.images.abandoned(cutoff), dry_run)
