from pymongo import ASCENDING, DESCENDING, AsyncMongoClient

REQUIRED_INDEXES = {
    "products": {"normalized_name_1"},
    "imported_images": {"hash_1", "import_id_1_sequence_number_1", "status_1"},
    "imports": {"status_1", "created_at_-1"},
    "orders": {"orders_expires_at_ttl", "orders_created_at_desc"},
}


def create_mongo(settings):
    client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    return client, client[settings.mongodb_database]


async def close_mongo(client):
    await client.close()


async def ensure_indexes(db):
    await db.products.create_index([("normalized_name", ASCENDING)])
    await db.imported_images.create_index([("hash", ASCENDING)])
    await db.imported_images.create_index(
        [("import_id", ASCENDING), ("sequence_number", ASCENDING)], unique=True
    )
    await db.imported_images.create_index([("status", ASCENDING)])
    await db.imported_images.create_index([("image_asset.file_id", ASCENDING)])
    await db.imports.create_index([("status", ASCENDING)])
    await db.imports.create_index([("created_at", DESCENDING)])
    await db.orphan_cleanup.create_index([("file_id", ASCENDING)], unique=True)
    await db.orders.create_index(
        [("expires_at", ASCENDING)], expireAfterSeconds=0, name="orders_expires_at_ttl"
    )
    await db.orders.create_index([("created_at", DESCENDING)], name="orders_created_at_desc")


async def verify_database(db):
    await db.command("ping")
    names = set(await db.list_collection_names())
    missing_collections = set(REQUIRED_INDEXES) - names
    missing_indexes = {}
    for collection, required in REQUIRED_INDEXES.items():
        if collection in names:
            actual = set((await db[collection].index_information()).keys())
            if missing := required - actual:
                missing_indexes[collection] = sorted(missing)
    return {
        "ok": not missing_collections and not missing_indexes,
        "missing_collections": sorted(missing_collections),
        "missing_indexes": missing_indexes,
    }
