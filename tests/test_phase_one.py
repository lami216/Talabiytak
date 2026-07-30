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
from app.services.errors import ImageKitError, ValidationError
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
    assert await images.status_counts(batch.id) == {ImageStatus.unnamed.value: 1}
    assert (await imports.list())[0].id == batch.id
    assert (await products.recent())[0].id == product.id


def test_auth_csrf_health_and_readiness(auth):
    client, app, *_ = auth
    client.cookies.clear()
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/login", data={"username": "bad", "password": "bad"}).status_code == 200
    client.post("/login", data={"username": "admin", "password": "strong-password"})
    token = app.state.security.load(client.cookies[app.state.settings.session_cookie_name])["csrf"]
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    csp = client.get("/").headers["content-security-policy"]
    img_src = csp.split("img-src ", 1)[1].split(";", 1)[0]
    assert "https://ik.imagekit.io" in img_src.split()
    assert "https://ik.imagekit.io/test" not in img_src.split()
    assert client.post("/logout", data={"csrf_token": "bad"}).status_code == 400
    assert (
        client.post("/logout", data={"csrf_token": token}, follow_redirects=False).status_code
        == 303
    )


def test_processing_preserves_original_file_and_arabic_normalization(auth):
    _, app, *_ = auth
    normalizer = ArabicNormalizationService()
    assert normalizer.normalize("مُنتَج  رائع!!!") == "منتج رائع"
    for fmt in ("PNG", "JPEG", "WEBP", "GIF"):
        original = image_bytes(fmt)
        processed = app.state.processor.process(original)
        assert processed.width == 20 and len(processed.sha256) == 64
        assert processed.data == original
        assert processed.original_format == processed.normalized_format == fmt
        assert processed.extension == {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}[
            fmt
        ]
    animated_gif = image_bytes("GIF", animated=True)
    assert app.state.processor.process(animated_gif).data == animated_gif


@pytest.mark.asyncio
async def test_imagekit_upload_requires_complete_response(auth, monkeypatch):
    _, app, fake, *_ = auth

    class IncompleteResult:
        file_id = ""
        file_path = "/test/incomplete.jpg"
        url = ""
        thumbnail_url = None

    monkeypatch.setattr(fake.files, "upload", lambda **kwargs: IncompleteResult())
    with pytest.raises(ImageKitError, match="فشل رفع الصورة"):
        await app.state.storage.upload(b"image", "jpg")


@pytest.mark.asyncio
async def test_imagekit_uses_configured_delivery_endpoint(auth, monkeypatch):
    _, app, fake, *_ = auth

    class ForeignUrlResult:
        file_id = "file-foreign"
        file_path = "/imports/صورة منتج.jpg"
        url = "https://unexpected-delivery.example/imports/image.jpg"
        thumbnail_url = "https://another-host.example/temporary-thumbnail.jpg"

    monkeypatch.setattr(fake.files, "upload", lambda **kwargs: ForeignUrlResult())
    stored = await app.state.storage.upload(b"image", "jpg")

    expected = (
        "https://ik.imagekit.io/test/imports/"
        "%D8%B5%D9%88%D8%B1%D8%A9%20%D9%85%D9%86%D8%AA%D8%AC.jpg"
    )
    assert stored.url == expected

    # Rendering must also rebuild legacy database URLs from file_path, rather than using a stale
    # URL or a thumbnail hosted outside the page's CSP allow-list.
    asset = ImageAsset(
        stored.file_id,
        stored.file_path,
        ForeignUrlResult.url,
        ForeignUrlResult.thumbnail_url,
        "a" * 64,
        "image/jpeg",
        1,
        1,
    )
    rendered = app.state.templates.env.globals["imagekit_url"](asset)
    assert rendered == expected


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
    assert fake.files.uploads[0]["file"] == png
    assert fake.files.uploads[0]["file_name"].endswith(".png")
    assert not list(tmp.rglob("*.xlsx"))
    raw_images = list(database.raw.imported_images.find().sort("sequence_number"))
    assert [x["status"] for x in raw_images] == ["unnamed", "duplicate", "invalid_image"]
    import_id = str(raw_images[0]["import_id"])
    image_url = "https://ik.imagekit.io/test/1.jpg"
    batch_html = client.get(f"/imports/{import_id}")
    assert batch_html.status_code == 200
    assert f'<img src="{image_url}"' in batch_html.text
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
    products_html = client.get("/products?q=حليب").text
    assert "حليب كامل الدسم" in products_html
    assert f'<img src="{image_url}"' in products_html
    assert f'<img src="{image_url}"' in client.get("/").text
    product = database.raw.products.find_one()
    assert product["metadata"]["source"] == "import"
    assert product["primary_image"] == raw_images[0]["image_asset"]
    assert f'<img src="{image_url}"' in client.get(f"/products/{product['_id']}/edit").text


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
