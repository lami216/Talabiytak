import enum
import uuid as uuidlib
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now():
    return datetime.now(UTC)


class BatchStatus(enum.StrEnum):
    processing = "processing"
    ready = "ready"
    completed = "completed"
    partially_failed = "partially_failed"
    failed = "failed"


class ImageStatus(enum.StrEnum):
    unnamed = "unnamed"
    saved_as_product = "saved_as_product"
    ignored = "ignored"
    duplicate = "duplicate"
    upload_failed = "upload_failed"
    invalid_image = "invalid_image"
    unsupported_format = "unsupported_format"
    deleted = "deleted"


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_product_name"),
        Index("ix_products_normalized_name", "normalized_name"),
        Index("ix_products_image_sha256", "image_sha256"),
        Index("ix_products_created_at", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300))
    imagekit_file_id: Mapped[str] = mapped_column(String(255))
    imagekit_file_path: Mapped[str] = mapped_column(String(1000))
    image_url: Mapped[str] = mapped_column(String(2000))
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000))
    image_sha256: Mapped[str] = mapped_column(String(64))
    image_mime_type: Mapped[str] = mapped_column(String(50))
    image_width: Mapped[int]
    image_height: Mapped[int]
    source_imported_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("imported_images.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuidlib.uuid4()))
    original_filename: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default=BatchStatus.processing.value)
    total_media_entries: Mapped[int] = mapped_column(Integer, default=0)
    valid_images: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_images: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_images: Mapped[int] = mapped_column(Integer, default=0)
    skipped_images: Mapped[int] = mapped_column(Integer, default=0)
    failed_images: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    images: Mapped[list["ImportedImage"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportedImage(Base):
    __tablename__ = "imported_images"
    __table_args__ = (
        Index("ix_imported_images_sha256", "sha256"),
        Index("ix_imported_images_batch_status", "batch_id", "status"),
        CheckConstraint("sequence_number > 0", name="ck_image_sequence"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    sequence_number: Mapped[int]
    original_media_name: Mapped[str] = mapped_column(String(1000))
    imagekit_file_id: Mapped[str | None] = mapped_column(String(255))
    imagekit_file_path: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(2000))
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000))
    sha256: Mapped[str] = mapped_column(String(64), default="")
    mime_type: Mapped[str] = mapped_column(String(50), default="")
    width: Mapped[int] = mapped_column(default=0)
    height: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(30))
    linked_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL")
    )
    duplicate_of_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL")
    )
    duplicate_of_imported_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("imported_images.id", ondelete="SET NULL")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    batch: Mapped[ImportBatch] = relationship(back_populates="images")
