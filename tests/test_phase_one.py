import zipfile
from io import BytesIO

import pytest
from bson import ObjectId
from PIL import Image

from app.config import Settings
from app.database import ensure_indexes, verify_database
from app.models import ImageAsset, ImageStatus, ImportedImage, Product
from app.repositories import ImportedImagesRepository, ImportsRepository, ProductsRepository
from app.services.arabic import ArabicNormalizationService
from app.services.errors import ImageProcessingError, ValidationError
from app.utils.objectid import serialize_id, to_object_id


def image_bytes(fmt="PNG", color="red", animated=False):
    output = BytesIO()
    image = Image.new("RGBA" if fmt == "PNG" else "RGB", (20, 15), color)
    if animated:
        image.save(
            output,
            format="GIF",
            save_all=True,
            append_images=[Image.new("RGB", (20, 15), "blue")],
            duration=10,
        )
    else:
        image.save(output, format=fmt)
    image.close()
    return output.getvalue()


def xlsx(entries):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


def test_settings_and_object_ids(monkeypatch):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            secret_key="a" * 40,
            admin_username="a",
            admin_password="b",
            mongodb_uri="mongodb://localhost",
            imagekit_private_key="",
            imagekit_public_key="x",
            imagekit_url_endpoint="https://x.example",
        )
    value = str(ObjectId())
    assert serialize_id(to_object_id(value)) == value
    with pytest.raises(ValidationError, match="غير صالح"):
        to_object_id("bad")


@pytest.mark.asyncio
async def test_repositories_and_indexes(database):
    await ensure_indexes(database)
    assert (await verify_database(database))["ok"]
    imports, images, products = (
        ImportsRepository(database),
        ImportedImagesRepository(database),
        ProductsRepository(database),
    )
    batch = await imports.create("test.xlsx")
    asset = ImageAsset("f1", "/f1", "https://x/f1", None, "a" * 64, "image/png", 1, 1)
    image = await images.create(
        ImportedImage(
            str(ObjectId()),
            batch.id,
            1,
            "xl/media/a.png",
            hash=asset.hash,
            status=ImageStatus.unnamed.value,
            image_asset=asset,
        )
    )
    assert (await images.find_duplicate_by_hash(asset.hash)).id == image.id
    product = await products.create(Product(str(ObjectId()), "منتج", "منتج", asset))
    assert (await products.get(product.id)).primary_image.file_id == "f1"
    assert (await products.search("منتج"))[1] == 1
    assert (await images.list_images(batch.id))[0].import_id == batch.id


def test_auth_csrf_health_and_readiness(auth):
    client, app, *_ = auth
    client.cookies.clear()
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/login", data={"username": "bad", "password": "bad"}).status_code == 200
    client.post("/login", data={"username": "admin", "password": "strong-password"})
    token = app.state.security.load(client.cookies[app.state.settings.session_cookie_name])["csrf"]
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    assert client.post("/logout", data={"csrf_token": "bad"}).status_code == 400
    assert (
        client.post("/logout", data={"csrf_token": token}, follow_redirects=False).status_code
        == 303
    )


def test_processing_and_normalization(auth):
    _, app, *_ = auth
    normalizer = ArabicNormalizationService()
    assert normalizer.normalize("مُنتَج  رائع!!!") == "منتج رائع"
    for fmt in ("PNG", "JPEG", "WEBP", "GIF"):
        processed = app.state.processor.process(image_bytes(fmt))
        assert processed.width == 20 and len(processed.sha256) == 64
    with pytest.raises(ImageProcessingError):
        app.state.processor.process(image_bytes("GIF", animated=True))


def test_import_duplicate_product_and_cleanup(auth):
    client, app, fake, tmp, token, database = auth
    png = image_bytes()
    book = xlsx(
        [
            ("xl/media/a.png", png),
            ("xl/media/b.png", png),
            ("xl/media/bad.png", b"bad"),
            ("xl/worksheets/sheet.xml", b"ignored"),
        ]
    )
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files={"file": ("fixture.xlsx", book)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(fake.files.uploads) == 1
    assert not list(tmp.rglob("*.xlsx"))
    raw_images = list(database.raw.imported_images.find().sort("sequence_number"))
    assert [x["status"] for x in raw_images] == ["unnamed", "duplicate", "invalid_image"]
    image_id = str(raw_images[0]["_id"])
    assert (
        client.post(
            f"/imports/images/{image_id}/save",
            data={"csrf_token": token, "name": "حليب كامل الدسم"},
            headers={"X-Requested-With": "fetch"},
        ).status_code
        == 200
    )
    assert len(fake.files.uploads) == 1
    assert "حليب كامل الدسم" in client.get("/products?q=حليب").text
    product = database.raw.products.find_one()
    assert product["metadata"]["source"] == "import"


@pytest.mark.asyncio
async def test_manual_upload_rollback_and_orphan_record(auth, monkeypatch):
    _, app, fake, _, _, database = auth

    async def failed_create(product):
        raise RuntimeError("mongo unavailable")

    monkeypatch.setattr(app.state.repositories.products, "create", failed_create)
    processed = app.state.processor.process(image_bytes())
    with pytest.raises(RuntimeError):
        await app.state.products.create_manual("ماء", processed)
    assert len(fake.files.deleted) == 1
    fake.files.fail_delete = True
    with pytest.raises(RuntimeError):
        await app.state.products.create_manual("ماء", processed)
    assert database.raw.orphan_cleanup.count_documents({"status": "pending"}) == 1


def test_cleanup_is_reference_safe_and_idempotent(auth):
    client, app, fake, _, token, database = auth
    client.post(
        "/imports/new",
        data={"csrf_token": token},
        files={"file": ("x.xlsx", xlsx([("xl/media/a.png", image_bytes())]))},
    )
    image = database.raw.imported_images.find_one()
    image_id, import_id = str(image["_id"]), str(image["import_id"])
    client.post(f"/imports/images/{image_id}/ignore", data={"csrf_token": token})
    client.post(f"/imports/{import_id}/cleanup", data={"csrf_token": token})
    client.post(f"/imports/{import_id}/cleanup", data={"csrf_token": token})
    assert len(fake.files.deleted) == 1
