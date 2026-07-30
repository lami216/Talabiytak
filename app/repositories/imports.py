from app.models import Import, now
from app.repositories.mapping import import_from_doc, oid
from app.utils.objectid import new_id, to_object_id


class ImportsRepository:
    def __init__(self, database):
        self.collection = database.imports

    async def create(self, filename: str) -> Import:
        item = Import(id=new_id(), filename=filename)
        await self.collection.insert_one(
            {
                "_id": to_object_id(item.id),
                "filename": filename,
                "status": item.status,
                "counters": item.counters,
                "errors": [],
                "processing_state": {},
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
        )
        return item

    async def get(self, import_id: str):
        doc = await self.collection.find_one({"_id": oid(import_id, "معرّف الاستيراد")})
        return import_from_doc(doc) if doc else None

    async def update(
        self, import_id: str, *, status=None, counters=None, errors=None, processing_state=None
    ):
        values = {"updated_at": now()}
        for key, value in (
            ("status", status),
            ("counters", counters),
            ("errors", errors),
            ("processing_state", processing_state),
        ):
            if value is not None:
                values[key] = value
        await self.collection.update_one({"_id": oid(import_id)}, {"$set": values})
        return await self.get(import_id)

    async def update_status(self, import_id, status, **kwargs):
        return await self.update(import_id, status=status, **kwargs)

    async def list(self, limit=100):
        cursor = self.collection.find({}).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=None)
        return [import_from_doc(d) for d in docs]

    async def count(self):
        return await self.collection.count_documents({})
