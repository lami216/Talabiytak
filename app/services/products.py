import logging

from app.models import ImageAsset, ImageStatus, Product
from app.services.arabic import ArabicNormalizationService
from app.services.errors import ValidationError
from app.utils.objectid import new_id

log = logging.getLogger(__name__)


class ProductService:
    def __init__(self, storage, products, images, orphans, normalizer=None):
        self.storage, self.products, self.images, self.orphans = storage, products, images, orphans
        self.normalizer = normalizer or ArabicNormalizationService()

    def _name(self, name):
        name = name.strip()
        if not name:
            raise ValidationError("اسم المنتج مطلوب")
        return name

    async def create_from_import(self, image_id, name):
        name = self._name(name)
        image = await self.images.get(image_id)
        if (
            not image
            or not image.image_asset
            or image.status in {ImageStatus.deleted.value, ImageStatus.upload_failed.value}
        ):
            raise ValidationError("الصورة غير متاحة")
        product = Product(
            new_id(),
            name,
            self.normalizer.normalize(name),
            image.image_asset,
            {
                "source": "import",
                "source_import_id": image.import_id,
                "source_imported_image_id": image.id,
            },
        )
        await self.products.create(product)
        try:
            await self.images.link_product(image.id, product.id)
        except Exception:
            await self.products.delete(product.id)
            raise
        await self.storage.update_tags(
            product.primary_image.file_id, ["product-image-manager", "product"]
        )
        return product

    async def create_manual(self, name, processed):
        name = self._name(name)
        reusable = await self.products.find_by_hash(processed.sha256)
        if not reusable:
            reusable = await self.images.find_duplicate_by_hash(processed.sha256)
        if reusable:
            asset = (
                reusable.primary_image if isinstance(reusable, Product) else reusable.image_asset
            )
            product = Product(
                new_id(),
                name,
                self.normalizer.normalize(name),
                asset,
                {"source": "manual"},
            )
            return await self.products.create(product)
        stored = await self.storage.upload(
            processed.data,
            processed.extension,
            processed.mime_type,
            processed.width,
            processed.height,
            purpose="product",
            correlation_id=processed.sha256,
        )
        asset = ImageAsset(
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
        product = Product(
            new_id(), name, self.normalizer.normalize(name), asset, {"source": "manual"}
        )
        try:
            return await self.products.create(product)
        except Exception as exc:
            await self._rollback(stored.file_id, f"product save failed: {exc}")
            raise

    async def _rollback(self, file_id, reason):
        try:
            await self.storage.delete(file_id)
        except Exception as exc:
            log.exception("ImageKit rollback failed", extra={"file_id": file_id})
            await self.orphans.record(file_id, f"{reason}: {exc}")

    async def search(self, query, page=1, size=24):
        return await self.products.search(self.normalizer.normalize(query), page, size)

    async def get(self, product_id):
        return await self.products.get(product_id)

    async def rename(self, product_id, name):
        product = await self._required(product_id)
        product.name = self._name(name)
        product.normalized_name = self.normalizer.normalize(product.name)
        return await self.products.update(product)

    async def replace(self, product_id, processed):
        product = await self._required(product_id)
        stored = await self.storage.upload(
            processed.data,
            processed.extension,
            processed.mime_type,
            processed.width,
            processed.height,
            purpose="product",
            correlation_id=processed.sha256,
        )
        old = product.primary_image
        product.primary_image = ImageAsset(
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
        try:
            await self.products.update(product)
        except Exception as exc:
            await self._rollback(stored.file_id, f"product update failed: {exc}")
            raise
        if not await self._referenced(old.file_id):
            await self.storage.delete(old.file_id)
        return product

    async def delete(self, product_id):
        product = await self.products.get(product_id)
        if not product:
            return
        await self.products.delete(product_id)
        if not await self._referenced(product.primary_image.file_id, product_id):
            await self.storage.delete(product.primary_image.file_id)

    async def _required(self, product_id):
        product = await self.products.get(product_id)
        if not product:
            raise ValidationError("المنتج غير موجود")
        return product

    async def _referenced(self, file_id, exclude_product=None):
        return (
            await self.products.asset_references(file_id, exclude_product)
            + await self.images.asset_references(file_id)
        ) > 0
