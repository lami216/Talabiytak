from app.models import ImageAsset, Import, ImportedImage, Order, OrderItem, Product
from app.utils.objectid import serialize_id, to_object_id


def asset_to_doc(asset: ImageAsset | None):
    return (
        None
        if asset is None
        else {
            "file_id": asset.file_id,
            "file_path": asset.file_path,
            "url": asset.url,
            "thumbnail_url": asset.thumbnail_url,
            "hash": asset.hash,
            "mime_type": asset.mime_type,
            "width": asset.width,
            "height": asset.height,
            "size": asset.size,
        }
    )


def asset_from_doc(doc):
    return None if not doc else ImageAsset(**doc)


def import_from_doc(doc):
    return Import(
        id=serialize_id(doc["_id"]),
        filename=doc["filename"],
        status=doc["status"],
        counters=doc.get("counters", {}),
        errors=doc.get("errors", []),
        processing_state=doc.get("processing_state", {}),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def image_from_doc(doc):
    duplicate = doc.get("duplicate_of")
    if duplicate and duplicate.get("id"):
        duplicate = {**duplicate, "id": serialize_id(duplicate["id"])}
    return ImportedImage(
        id=serialize_id(doc["_id"]),
        import_id=serialize_id(doc["import_id"]),
        sequence_number=doc["sequence_number"],
        original_media_name=doc["original_media_name"],
        hash=doc.get("hash", ""),
        status=doc["status"],
        duplicate_of=duplicate,
        linked_product_id=serialize_id(doc["linked_product_id"])
        if doc.get("linked_product_id")
        else None,
        dimensions=doc.get("dimensions", {"width": 0, "height": 0}),
        mime_type=doc.get("mime_type", ""),
        image_asset=asset_from_doc(doc.get("image_asset")),
        error_message=doc.get("error_message"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def product_from_doc(doc):
    return Product(
        id=serialize_id(doc["_id"]),
        name=doc["name"],
        normalized_name=doc["normalized_name"],
        primary_image=asset_from_doc(doc["primary_image"]),
        metadata=doc.get("metadata", {}),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def order_from_doc(doc):
    return Order(
        id=serialize_id(doc["_id"]),
        title=doc["title"],
        items=[
            OrderItem(
                serialize_id(i["product_id"]), i["product_name"], i["quantity"], i["position"]
            )
            for i in doc.get("items", [])
        ],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        expires_at=doc["expires_at"],
    )


def oid(value, label="المعرّف"):
    return to_object_id(value, label)
