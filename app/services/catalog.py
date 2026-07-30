from app.models import ImageStatus


class CatalogQueryService:
    def __init__(self, database, imports, images, products, orders=None):
        self.database, self.imports, self.images, self.products = (
            database,
            imports,
            images,
            products,
        )
        self.orders = orders

    async def readiness(self):
        await self.database.command("ping")
        return {"status": "ready", "database": "ok", "imagekit": "configured"}

    async def dashboard(self):
        return (
            {
                "products": await self.products.count(),
                "unnamed": await self.images.count(ImageStatus.unnamed.value),
                "batches": await self.imports.count(),
                "orders": await self.orders.count_active() if self.orders else 0,
            },
            await self.imports.list(6),
            await self.products.recent(6),
            await self.orders.recent(6) if self.orders else [],
        )
