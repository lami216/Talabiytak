import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)


class ImportStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
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


@dataclass(frozen=True)
class ImageAsset:
    """Immutable metadata for one shared ImageKit object.

    Products and imported images may share a file_id. The object is storage-owned and may only be
    deleted after repositories confirm that no active application record references it.
    """

    file_id: str
    file_path: str
    url: str
    thumbnail_url: str | None
    hash: str
    mime_type: str
    width: int
    height: int
    size: int | None = None


@dataclass
class Import:
    id: str
    filename: str
    status: str = ImportStatus.pending.value
    counters: dict[str, int] = field(
        default_factory=lambda: {
            "total_media_entries": 0,
            "valid_images": 0,
            "uploaded_images": 0,
            "duplicate_images": 0,
            "skipped_images": 0,
            "failed_images": 0,
        }
    )
    errors: list[str] = field(default_factory=list)
    processing_state: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)

    @property
    def original_filename(self):
        return self.filename

    def __getattr__(self, name):
        if name in self.counters:
            return self.counters[name]
        raise AttributeError(name)


@dataclass
class ImportedImage:
    id: str
    import_id: str
    sequence_number: int
    original_media_name: str
    hash: str = ""
    status: str = ImageStatus.invalid_image.value
    duplicate_of: dict[str, str] | None = None
    linked_product_id: str | None = None
    dimensions: dict[str, int] = field(default_factory=lambda: {"width": 0, "height": 0})
    mime_type: str = ""
    image_asset: ImageAsset | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)

    @property
    def batch_id(self):
        return self.import_id

    @property
    def image_url(self):
        return self.image_asset.url if self.image_asset else None

    @property
    def thumbnail_url(self):
        return self.image_asset.thumbnail_url if self.image_asset else None


@dataclass
class Product:
    id: str
    name: str
    normalized_name: str
    primary_image: ImageAsset
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)

    @property
    def image_url(self):
        return self.primary_image.url

    @property
    def thumbnail_url(self):
        return self.primary_image.thumbnail_url


@dataclass
class OrderItem:
    product_id: str
    product_name: str
    quantity: int
    position: int


@dataclass
class Order:
    id: str
    title: str
    items: list[OrderItem]
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    expires_at: datetime | None = None


__all__ = [
    "ImageAsset",
    "ImageStatus",
    "Import",
    "ImportedImage",
    "ImportStatus",
    "Order",
    "OrderItem",
    "Product",
    "now",
]
