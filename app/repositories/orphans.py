from app.models import now


class OrphanCleanupRepository:
    def __init__(self, database):
        self.collection = database.orphan_cleanup

    async def record(self, file_id, reason):
        await self.collection.update_one(
            {"file_id": file_id},
            {
                "$set": {
                    "file_id": file_id,
                    "reason": str(reason)[:1000],
                    "status": "pending",
                    "updated_at": now(),
                },
                "$setOnInsert": {"created_at": now()},
            },
            upsert=True,
        )
