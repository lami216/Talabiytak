from datetime import timedelta

from app.models import Order, OrderItem, now
from app.services.errors import ValidationError
from app.utils.objectid import new_id, to_object_id


class OrderService:
    def __init__(self, settings, orders, products):
        self.settings, self.orders, self.products = settings, orders, products

    def _title(self, title):
        title = title.strip()
        if not title:
            raise ValidationError("اسم الطلبية مطلوب.")
        if len(title) > 150:
            raise ValidationError("اسم الطلبية يجب ألا يتجاوز 150 حرفًا.")
        return title

    async def _items(self, product_ids, quantities):
        if not product_ids:
            raise ValidationError("يجب إضافة منتج واحد على الأقل إلى الطلبية.")
        if len(product_ids) > self.settings.max_order_items:
            raise ValidationError("تم تجاوز الحد الأقصى لعدد المنتجات.")
        if len(product_ids) != len(quantities):
            raise ValidationError("بيانات عناصر الطلبية غير صالحة.")
        if len(set(product_ids)) != len(product_ids):
            raise ValidationError("لا يمكن تكرار المنتج داخل الطلبية.")
        result = []
        for position, (product_id, raw_quantity) in enumerate(
            zip(product_ids, quantities, strict=True), 1
        ):
            to_object_id(product_id, "معرّف المنتج")
            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                raise ValidationError("الكمية غير صالحة.") from None
            if quantity < 1 or quantity > 1_000_000:
                raise ValidationError("الكمية يجب أن تكون بين 1 و1000000.")
            product = await self.products.get(product_id)
            if not product:
                raise ValidationError("المنتج غير موجود.")
            result.append(OrderItem(product.id, product.name, quantity, position))
        return result

    async def create(self, title, product_ids, quantities):
        created = now()
        order = Order(
            new_id(),
            self._title(title),
            await self._items(product_ids, quantities),
            created,
            created,
            created + timedelta(days=self.settings.order_retention_days),
        )
        return await self.orders.create(order)

    async def update(self, order_id, title, product_ids, quantities):
        order = await self.get_active(order_id)
        order.title, order.items, order.updated_at = (
            self._title(title),
            await self._items(product_ids, quantities),
            now(),
        )
        return await self.orders.update(order)

    async def get_active(self, order_id):
        order = await self.orders.get_active(order_id)
        if not order:
            raise ValidationError("انتهت صلاحية هذه الطلبية أو تم حذفها.")
        return order

    async def list_active(self, page=1, size=24):
        return await self.orders.list_active(page, size)

    async def delete(self, order_id):
        await self.get_active(order_id)
        return await self.orders.delete(order_id)
