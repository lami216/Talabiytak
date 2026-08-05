from app.models import ImportedImage, now
from app.repositories.mapping import asset_to_doc, image_from_doc, oid
from app.utils.objectid import new_id, to_object_id


class ImportedImagesRepository:
    def __init__(self, database):
        self.collection = database.imported_images

    async def create(self, image: ImportedImage):
        if not image.id:
            image.id = new_id()
        duplicate = image.duplicate_of
        if duplicate:
            duplicate = {**duplicate, "id": to_object_id(duplicate["id"])}
        await self.collection.insert_one(
            {
                "_id": to_object_id(image.id),
                "import_id": to_object_id(image.import_id),
                "sequence_number": image.sequence_number,
                "original_media_name": image.original_media_name,
                "hash": image.hash,
                "status": image.status,
                "duplicate_of": duplicate,
                "linked_product_id": to_object_id(image.linked_product_id)
                if image.linked_product_id
                else None,
                "dimensions": image.dimensions,
                "mime_type": image.mime_type,
                "image_asset": asset_to_doc(image.image_asset),
                "error_message": image.error_message,
                "created_at": image.created_at,
                "updated_at": image.updated_at,
            }
        )
        return image

    async def get(self, image_id):
        doc = await self.collection.find_one({"_id": oid(image_id, "معرّف الصورة")})
        return image_from_doc(doc) if doc else None

    async def find_duplicate_by_hash(self, image_hash, exclude_id=None):
        query = {
            "hash": image_hash,
            "image_asset.file_id": {"$ne": None},
            "status": {"$ne": "deleted"},
        }
        if exclude_id:
            query["_id"] = {"$ne": oid(exclude_id)}
        doc = await self.collection.find_one(query, sort=[("created_at", 1)])
        return image_from_doc(doc) if doc else None

    async def update(self, image: ImportedImage):
        duplicate = image.duplicate_of
        if duplicate:
            duplicate = {**duplicate, "id": oid(duplicate["id"])}
        image.updated_at = now()
        await self.collection.update_one(
            {"_id": oid(image.id)},
            {
                "$set": {
                    "hash": image.hash,
                    "status": image.status,
                    "duplicate_of": duplicate,
                    "linked_product_id": oid(image.linked_product_id)
                    if image.linked_product_id
                    else None,
                    "dimensions": image.dimensions,
                    "mime_type": image.mime_type,
                    "image_asset": asset_to_doc(image.image_asset),
                    "error_message": image.error_message,
                    "updated_at": image.updated_at,
                }
            },
        )
        return image

    async def update_status(self, image_id, status):
        image = await self.get(image_id)
        if image:
            image.status = status
            await self.update(image)
        return image

    async def link_product(self, image_id, product_id):
        image = await self.get(image_id)
        if image:
            image.linked_product_id = product_id
            image.status = "saved_as_product"
            await self.update(image)
        return image

    async def list_images(self, import_id, status="all", page=1, size=48):
        query = {"import_id": oid(import_id, "معرّف الاستيراد")}
        if status == "all":
            query["status"] = {"$nin": ["ignored", "deleted"]}
        else:
            query["status"] = status
        cursor = (
            self.collection.find(query)
            .sort("sequence_number", 1)
            .skip((max(page, 1) - 1) * size)
            .limit(size)
        )
        docs = await cursor.to_list(length=None)
        return [image_from_doc(d) for d in docs]

    async def status_counts(self, import_id):
        cursor = await self.collection.aggregate(
            [
                {
                    "$match": {
                        "import_id": oid(import_id),
                        "status": {"$nin": ["ignored", "deleted"]},
                    }
                },
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
        )
        rows = await cursor.to_list(length=None)
        return {row["_id"]: row["count"] for row in rows}

    async def count(self, status=None):
        return await self.collection.count_documents({"status": status} if status else {})

    async def delete(self, image_id):
        return await self.collection.delete_one({"_id": oid(image_id)})

    async def mark_deleted(self, image_id):
        return await self.collection.update_one(
            {"_id": oid(image_id)},
            {"$set": {"status": "deleted", "image_asset": None, "updated_at": now()}},
        )

    async def asset_references(self, file_id, exclude_id=None):
        query = {"image_asset.file_id": file_id, "status": {"$nin": ["deleted", "ignored"]}}
        if exclude_id:
            query["_id"] = {"$ne": oid(exclude_id)}
        return await self.collection.count_documents(query)

    async def abandoned(self, cutoff):
        cursor = self.collection.find(
            {"created_at": {"$lt": cutoff}, "status": {"$in": ["unnamed", "ignored"]}}
        )
        docs = await cursor.to_list(length=None)
        return [image_from_doc(d) for d in docs]
