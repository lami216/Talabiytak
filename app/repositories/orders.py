from datetime import UTC, datetime

from app.repositories.mapping import oid, order_from_doc


class OrdersRepository:
    def __init__(self, database):
        self.collection = database.orders

    @staticmethod
    def _doc(order):
        return {
            "_id": oid(order.id, "معرّف الطلبية"),
            "title": order.title,
            "items": [
                {
                    "product_id": oid(i.product_id, "معرّف المنتج"),
                    "product_name": i.product_name,
                    "quantity": i.quantity,
                    "position": i.position,
                }
                for i in order.items
            ],
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "expires_at": order.expires_at,
        }

    async def create(self, order):
        await self.collection.insert_one(self._doc(order))
        return order

    async def get(self, order_id):
        doc = await self.collection.find_one({"_id": oid(order_id, "معرّف الطلبية")})
        return order_from_doc(doc) if doc else None

    async def get_active(self, order_id):
        doc = await self.collection.find_one(
            {"_id": oid(order_id, "معرّف الطلبية"), "expires_at": {"$gt": datetime.now(UTC)}}
        )
        return order_from_doc(doc) if doc else None

    async def list_active(self, page=1, size=24):
        cursor = (
            self.collection.find({"expires_at": {"$gt": datetime.now(UTC)}})
            .sort("created_at", -1)
            .skip((max(page, 1) - 1) * size)
            .limit(size)
        )
        return [order_from_doc(d) for d in await cursor.to_list(length=None)]

    async def update(self, order):
        doc = self._doc(order)
        doc.pop("_id")
        doc.pop("created_at")
        doc.pop("expires_at")
        await self.collection.update_one({"_id": oid(order.id)}, {"$set": doc})
        return order

    async def delete(self, order_id):
        return await self.collection.delete_one(
            {"_id": oid(order_id), "expires_at": {"$gt": datetime.now(UTC)}}
        )

    async def count_active(self):
        return await self.collection.count_documents({"expires_at": {"$gt": datetime.now(UTC)}})

    async def active_product_references(self, product_id):
        return await self.collection.count_documents(
            {
                "expires_at": {"$gt": datetime.now(UTC)},
                "items.product_id": oid(product_id, "معرّف المنتج"),
            }
        )

    async def recent(self, limit=6):
        return await self.list_active(1, limit)
