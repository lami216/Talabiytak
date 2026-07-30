from bson import ObjectId

from app.services.errors import ValidationError


def new_id() -> str:
    return str(ObjectId())


def to_object_id(value: str, label: str = "المعرّف") -> ObjectId:
    if not isinstance(value, str) or not ObjectId.is_valid(value):
        raise ValidationError(f"{label} غير صالح")
    return ObjectId(value)


def serialize_id(value: ObjectId | str) -> str:
    return str(value)
