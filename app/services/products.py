from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import ImageStatus, ImportedImage, Product
from app.services.arabic import ArabicNormalizationService
from app.services.errors import ValidationError


class ProductService:
    def __init__(self, imagekit, normalizer=None):
        self.imagekit = imagekit
        self.normalizer = normalizer or ArabicNormalizationService()

    def create_from_import(self, s: Session, image_id: int, name: str):
        name = name.strip()
        if not name:
            raise ValidationError("اسم المنتج مطلوب")
        image = s.get(ImportedImage, image_id)
        if (
            not image
            or not image.imagekit_file_id
            or image.status in {ImageStatus.deleted.value, ImageStatus.upload_failed.value}
        ):
            raise ValidationError("الصورة غير متاحة")
        p = Product(
            name=name,
            normalized_name=self.normalizer.normalize(name),
            imagekit_file_id=image.imagekit_file_id,
            imagekit_file_path=image.imagekit_file_path,
            image_url=image.image_url,
            thumbnail_url=image.thumbnail_url,
            image_sha256=image.sha256,
            image_mime_type=image.mime_type,
            image_width=image.width,
            image_height=image.height,
            source_imported_image_id=image.id,
        )
        s.add(p)
        s.flush()
        image.linked_product_id = p.id
        image.status = ImageStatus.saved_as_product.value
        s.commit()
        self.imagekit.update_tags(p.imagekit_file_id, ["product-image-manager", "product"])
        return p

    def create_manual(self, s, name, processed):
        name = name.strip()
        if not name:
            raise ValidationError("اسم المنتج مطلوب")
        asset = self.imagekit.upload(
            processed.data, processed.extension, tags=["product-image-manager", "product"]
        )
        try:
            p = Product(
                name=name,
                normalized_name=self.normalizer.normalize(name),
                imagekit_file_id=asset.file_id,
                imagekit_file_path=asset.file_path,
                image_url=asset.url,
                thumbnail_url=asset.thumbnail_url,
                image_sha256=processed.sha256,
                image_mime_type=processed.mime_type,
                image_width=processed.width,
                image_height=processed.height,
            )
            s.add(p)
            s.commit()
            return p
        except Exception:
            s.rollback()
            self.imagekit.delete(asset.file_id)
            raise

    def search(self, s, q, page=1, size=24):
        stmt = select(Product)
        norm = self.normalizer.normalize(q)
        if norm:
            rank = case(
                (Product.normalized_name == norm, 0),
                (Product.normalized_name.like(norm + "%"), 1),
                else_=2,
            )
            stmt = stmt.where(Product.normalized_name.like(f"%{norm}%")).order_by(
                rank, Product.created_at.desc()
            )
        else:
            stmt = stmt.order_by(Product.created_at.desc())
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        return s.scalars(stmt.offset((page - 1) * size).limit(size)).all(), total

    def rename(self, s, p, name):
        name = name.strip()
        if not name:
            raise ValidationError("اسم المنتج مطلوب")
        p.name = name
        p.normalized_name = self.normalizer.normalize(name)
        s.commit()

    def referenced(self, s, file_id, exclude_product=None):
        pc = s.scalar(
            select(func.count(Product.id)).where(
                Product.imagekit_file_id == file_id,
                Product.id != exclude_product if exclude_product else Product.id > 0,
            )
        )
        ic = s.scalar(
            select(func.count(ImportedImage.id)).where(ImportedImage.imagekit_file_id == file_id)
        )
        return (pc or 0) + (ic or 0)

    def replace(self, s, p, processed):
        asset = self.imagekit.upload(
            processed.data, processed.extension, tags=["product-image-manager", "product"]
        )
        old = p.imagekit_file_id
        try:
            p.imagekit_file_id = asset.file_id
            p.imagekit_file_path = asset.file_path
            p.image_url = asset.url
            p.thumbnail_url = asset.thumbnail_url
            p.image_sha256 = processed.sha256
            p.image_mime_type = processed.mime_type
            p.image_width = processed.width
            p.image_height = processed.height
            s.commit()
        except Exception:
            s.rollback()
            self.imagekit.delete(asset.file_id)
            raise
        if not self.referenced(s, old):
            self.imagekit.delete(old)

    def delete(self, s, p):
        file_id = p.imagekit_file_id
        pid = p.id
        s.delete(p)
        s.commit()
        if not self.referenced(s, file_id, exclude_product=pid):
            self.imagekit.delete(file_id)
