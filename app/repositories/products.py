import re

from app.models import Product, now
from app.repositories.mapping import asset_to_doc, oid, product_from_doc
from app.utils.objectid import to_object_id


class ProductsRepository:
    def __init__(self, database):
        self.collection = database.products

    async def create(self, product: Product):
        await self.collection.insert_one(
            {
                "_id": to_object_id(product.id),
                "name": product.name,
                "normalized_name": product.normalized_name,
                "primary_image": asset_to_doc(product.primary_image),
                "metadata": product.metadata,
                "created_at": product.created_at,
                "updated_at": product.updated_at,
            }
        )
        return product

    async def get(self, product_id):
        doc = await self.collection.find_one({"_id": oid(product_id, "معرّف المنتج")})
        return product_from_doc(doc) if doc else None

    async def find_by_hash(self, image_hash):
        doc = await self.collection.find_one({"primary_image.hash": image_hash})
        return product_from_doc(doc) if doc else None

    async def search(self, normalized_query, page=1, size=24):
        query = (
            {"normalized_name": {"$regex": re.escape(normalized_query)}} if normalized_query else {}
        )
        total = await self.collection.count_documents(query)
        cursor = (
            self.collection.find(query)
            .sort("created_at", -1)
            .skip((max(page, 1) - 1) * size)
            .limit(size)
        )
        docs = await cursor.to_list(length=None)
        items = [product_from_doc(d) for d in docs]
        if normalized_query:
            items.sort(
                key=lambda p: (
                    0
                    if p.normalized_name == normalized_query
                    else 1
                    if p.normalized_name.startswith(normalized_query)
                    else 2,
                    -p.created_at.timestamp(),
                )
            )
        return items, total

    async def update(self, product):
        product.updated_at = now()
        await self.collection.update_one(
            {"_id": oid(product.id)},
            {
                "$set": {
                    "name": product.name,
                    "normalized_name": product.normalized_name,
                    "primary_image": asset_to_doc(product.primary_image),
                    "metadata": product.metadata,
                    "updated_at": product.updated_at,
                }
            },
        )
        return product

    async def delete(self, product_id):
        return await self.collection.delete_one({"_id": oid(product_id)})

    async def count(self):
        return await self.collection.count_documents({})

    async def asset_references(self, file_id, exclude_id=None):
        query = {"primary_image.file_id": file_id}
        if exclude_id:
            query["_id"] = {"$ne": oid(exclude_id)}
        return await self.collection.count_documents(query)

    async def recent(self, limit=6):
        cursor = self.collection.find({}).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=None)
        return [product_from_doc(d) for d in docs]
