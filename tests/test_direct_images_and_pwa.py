import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

from app.models import ImageAsset
from app.utils.objectid import new_id
from tests.test_phase_one import image_bytes, xlsx


def test_import_form_has_excel_and_multiple_images(auth):
    client, *_ = auth
    html = client.get("/imports/new").text
    assert "رفع ملف Excel أو صور المنتجات" in html
    assert 'name="file"' in html and 'accept=".xlsx"' in html
    assert 'name="images"' in html and "multiple" in html
    assert "رفع صور مباشرة" in html


def test_import_requires_excel_or_images(auth):
    client, _, _, _, token, _ = auth
    response = client.post("/imports/new", data={"csrf_token": token})
    assert response.status_code == 400
    assert "اختر ملف Excel أو صورة واحدة على الأقل" in response.text


def test_single_and_multiple_direct_images_one_batch(auth):
    client, _, fake, _, token, database = auth
    files = [
        ("images", ("a.png", image_bytes("PNG"), "image/png")),
        ("images", ("b.jpg", image_bytes("JPEG", "blue"), "image/jpeg")),
    ]
    response = client.post(
        "/imports/new", data={"csrf_token": token}, files=files, follow_redirects=False
    )
    assert response.status_code == 303
    assert len(fake.files.uploads) == 2
    batch = database.raw.imports.find_one()
    assert batch["filename"] == "صور مرفوعة مباشرة — 2 صور"
    assert batch["counters"]["total_media_entries"] == 2
    assert batch["counters"]["uploaded_images"] == 2
    images = list(database.raw.imported_images.find().sort("sequence_number"))
    assert [image["sequence_number"] for image in images] == [1, 2]
    html = client.get(response.headers["location"]).text
    assert "image-card" in html and "تم إنشاء المنتج" not in html


def test_excel_and_direct_images_share_batch_and_sequences(auth):
    client, _, fake, _, token, database = auth
    book = xlsx([("xl/media/a.png", image_bytes("PNG"))])
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files=[
            (
                "file",
                (
                    "fixture.xlsx",
                    book,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            ),
            ("images", ("b.webp", image_bytes("WEBP", "blue"), "image/webp")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(fake.files.uploads) == 2
    batch = database.raw.imports.find_one()
    assert batch["filename"] == "fixture.xlsx + 1 صور مباشرة"
    assert batch["counters"]["total_media_entries"] == 2
    assert [
        x["sequence_number"] for x in database.raw.imported_images.find().sort("sequence_number")
    ] == [1, 2]


def test_direct_image_duplicates_do_not_upload_again(auth):
    client, _, fake, _, token, database = auth
    png = image_bytes("PNG")
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files=[("images", ("a.png", png, "image/png")), ("images", ("copy.png", png, "image/png"))],
    )
    assert response.status_code == 200
    assert len(fake.files.uploads) == 1
    assert [x["status"] for x in database.raw.imported_images.find().sort("sequence_number")] == [
        "unnamed",
        "duplicate",
    ]


def test_direct_image_duplicate_with_existing_product(auth):
    client, app, fake, _, token, database = auth
    png = image_bytes("PNG")
    processed = app.state.processor.process(png)
    asset = ImageAsset(
        "existing-file",
        "/existing.png",
        "https://ik.imagekit.io/test/existing.png",
        None,
        processed.sha256,
        processed.mime_type,
        20,
        15,
        len(png),
    )
    database.raw.products.insert_one(
        {
            "_id": __import__("bson").ObjectId(new_id()),
            "name": "منتج",
            "normalized_name": "منتج",
            "primary_image": {
                "file_id": asset.file_id,
                "file_path": asset.file_path,
                "url": asset.url,
                "thumbnail_url": asset.thumbnail_url,
                "hash": asset.hash,
                "mime_type": asset.mime_type,
                "width": asset.width,
                "height": asset.height,
                "size": asset.size,
            },
            "metadata": {},
            "created_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
        }
    )
    response = client.post(
        "/imports/new", data={"csrf_token": token}, files={"images": ("a.png", png, "image/png")}
    )
    assert response.status_code == 200
    assert len(fake.files.uploads) == 0
    assert database.raw.imported_images.find_one()["status"] == "duplicate"


def test_direct_invalid_large_and_animated_fail_without_blocking_valid(auth):
    client, _, fake, _, token, database = auth
    big = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files=[
            ("images", ("bad.png", b"not image", "image/png")),
            ("images", ("big.png", big, "image/png")),
            ("images", ("ok.gif", image_bytes("GIF"), "image/gif")),
            ("images", ("animated.gif", image_bytes("GIF", animated=True), "image/gif")),
        ],
    )
    assert response.status_code == 200
    assert len(fake.files.uploads) == 1
    counts = database.raw.imports.find_one()["counters"]
    assert counts["total_media_entries"] == 4
    assert counts["failed_images"] == 3


def test_direct_image_can_be_saved_and_found_in_order(auth):
    client, _, _, _, token, database = auth
    client.post(
        "/imports/new",
        data={"csrf_token": token},
        files={"images": ("a.png", image_bytes(), "image/png")},
    )
    image_id = str(database.raw.imported_images.find_one()["_id"])
    response = client.post(
        f"/imports/images/{image_id}/save",
        data={"csrf_token": token, "name": "تمر فاخر"},
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    assert "تمر فاخر" in client.get("/products?q=تمر").text
    assert (
        "تمر فاخر" in client.get("/orders/new").text
        or client.get("/products?q=تمر").status_code == 200
    )


def test_branding_manifest_service_worker_and_icons(auth):
    client, *_ = auth
    assert Path("app/static/branding/talabiytak-logo-source.png").exists()
    subprocess.run([sys.executable, "scripts/build_web_icons.py"], check=True)
    sizes = {
        "talabiytak-logo-48.png": (48, 48),
        "talabiytak-favicon-32.png": (32, 32),
        "talabiytak-apple-touch-180.png": (180, 180),
        "talabiytak-icon-192.png": (192, 192),
        "talabiytak-icon-512.png": (512, 512),
        "talabiytak-maskable-512.png": (512, 512),
    }
    for filename, size in sizes.items():
        with Image.open(Path("app/static/branding") / filename) as image:
            assert image.format == "PNG" and image.size == size
        assert client.get(f"/static/branding/{filename}").status_code == 200
    html = client.get("/").text
    assert "طلبياتك" in html
    assert "إدارة صور المنتجات" not in html
    assert "talabiytak-logo-48.png" in html
    assert "<title>طلبياتك</title>" in html
    manifest_response = client.get("/static/manifest.webmanifest")
    assert manifest_response.status_code == 200
    manifest = json.loads(manifest_response.text)
    assert manifest["name"] == manifest["short_name"] == "طلبياتك"
    assert manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} >= {"192x192", "512x512"}
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])
    sw = client.get("/service-worker.js")
    assert sw.status_code == 200
    assert sw.headers["service-worker-allowed"] == "/"
    assert "serviceWorker.register" in client.get("/static/app.js").text
    assert "unsafe-inline" not in client.get("/").headers["content-security-policy"]
    assert "STATIC_ASSETS" in sw.text
    assert "/products" not in sw.text and "/orders" not in sw.text and "/login" not in sw.text
