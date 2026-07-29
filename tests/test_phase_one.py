import zipfile
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import inspect, select

from app.config import Settings
from app.models import ImportedImage, Product
from app.services.arabic import ArabicNormalizationService
from app.services.errors import ImageProcessingError


def image_bytes(fmt="PNG", color="red", animated=False):
    out = BytesIO()
    im = Image.new("RGBA" if fmt == "PNG" else "RGB", (20, 15), color)
    if animated:
        im.save(
            out,
            format="GIF",
            save_all=True,
            append_images=[Image.new("RGB", (20, 15), "blue")],
            duration=10,
        )
    else:
        im.save(out, format=fmt)
    im.close()
    return out.getvalue()


def xlsx(entries):
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for name, data in entries:
            z.writestr(name, data)
    return out.getvalue()


def test_missing_imagekit_rejected(monkeypatch):
    monkeypatch.delenv("IMAGEKIT_PRIVATE_KEY", raising=False)
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            secret_key="a" * 40,
            admin_username="a",
            admin_password="b",
            database_url="sqlite://",
            imagekit_private_key="",
            imagekit_public_key="x",
            imagekit_url_endpoint="https://x.example",
        )


def test_auth_redirect_csrf_and_health(setup, auth):
    client, app, *_ = setup
    client.cookies.clear()
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/login", data={"username": "bad", "password": "bad"}).status_code == 200
    client, app, _, _, _ = auth
    client.post("/login", data={"username": "admin", "password": "strong-password"})
    token = app.state.security.load(client.cookies[app.state.settings.session_cookie_name])["csrf"]
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    assert client.post("/logout", data={"csrf_token": "bad"}).status_code == 400
    assert (
        client.post("/logout", data={"csrf_token": token}, follow_redirects=False).status_code
        == 303
    )


def test_arabic_normalization():
    n = ArabicNormalizationService()
    assert n.normalize(" آإأٱبـــ ١۲3 ") == n.normalize("ااااب 123")
    assert n.normalize("مُنتَج  رائع!!!") == "منتج رائع"
    assert n.normalize("ABC") == "abc"
    assert n.normalize("عبوة") == n.normalize("عبوه")


def test_processing_formats(auth):
    _, app, *_ = auth
    for fmt in ("PNG", "JPEG", "WEBP", "GIF"):
        p = app.state.processor.process(image_bytes(fmt))
        assert isinstance(p.data, bytes) and p.width == 20 and len(p.sha256) == 64
    with pytest.raises(ImageProcessingError):
        app.state.processor.process(b"no")
    with pytest.raises(ImageProcessingError):
        app.state.processor.process(image_bytes("GIF", animated=True))


def test_invalid_xlsx_and_zip_safety(auth):
    client, app, _, _, token = auth
    assert (
        client.post(
            "/imports/new", data={"csrf_token": token}, files={"file": ("x.xls", b"x")}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/imports/new", data={"csrf_token": token}, files={"file": ("x.xlsx", b"notzip")}
        ).status_code
        >= 400
    )
    unsafe = xlsx([("../xl/media/a.png", image_bytes())])
    assert (
        client.post(
            "/imports/new", data={"csrf_token": token}, files={"file": ("x.xlsx", unsafe)}
        ).status_code
        == 400
    )
    app.state.settings.max_zip_entries = 1
    assert (
        client.post(
            "/imports/new",
            data={"csrf_token": token},
            files={"file": ("x.xlsx", xlsx([("a", b"1"), ("b", b"2")]))},
        ).status_code
        == 400
    )


def test_real_import_duplicates_naming_search_no_files(auth):
    client, app, fake, tmp, token = auth
    before = set(tmp.rglob("*"))
    png = image_bytes("PNG")
    book = xlsx(
        [
            ("xl/media/image1.png", png),
            ("xl/media/image2.jpg", png),
            ("xl/media/bad.png", b"bad"),
            ("xl/worksheets/sheet1.xml", b"anchors ignored"),
        ]
    )
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files={"file": ("fixture.xlsx", book)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(fake.files.uploads) == 1 and isinstance(fake.files.uploads[0]["file"], bytes)
    after = set(tmp.rglob("*"))
    assert not [
        p
        for p in after - before
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".xlsx"}
    ]
    with app.state.session_factory() as s:
        images = s.scalars(select(ImportedImage).order_by(ImportedImage.id)).all()
        assert len(images) == 3
        assert images[0].status == "unnamed"
        assert images[1].status == "duplicate"
        assert images[2].status == "invalid_image"
        image_id = images[0].id
        batch_id = images[0].batch_id
    assert (
        client.post(
            f"/imports/images/{image_id}/save",
            data={"csrf_token": token, "name": "  "},
            headers={"X-Requested-With": "fetch"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/imports/images/{image_id}/save",
            data={"csrf_token": token, "name": "حليب كامل الدسم"},
            headers={"X-Requested-With": "fetch"},
        ).status_code
        == 200
    )
    assert len(fake.files.uploads) == 1
    page = client.get("/products?q=حليب كامل")
    assert "حليب كامل الدسم" in page.text
    with app.state.session_factory() as s:
        p = s.scalar(select(Product))
        assert p.imagekit_file_id == images[0].imagekit_file_id
        assert not any(
            c["name"] in {"BLOB", "LargeBinary"}
            for t in inspect(app.state.engine).get_table_names()
            for c in inspect(app.state.engine).get_columns(t)
        )
        pid = p.id
    assert (
        client.post(
            f"/products/{pid}/edit",
            data={"csrf_token": token, "name": "حليب ٢ لتر"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert "حليب ٢ لتر" in client.get("/products?q=2 لتر").text
    assert client.get(f"/imports/{batch_id}").status_code == 200


def test_manual_replace_and_shared_delete(auth):
    client, app, fake, _, token = auth
    img = image_bytes()
    r = client.post(
        "/products/new",
        data={"csrf_token": token, "name": "ماء"},
        files={"image": ("a.png", img, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert len(fake.files.uploads) == 1
    with app.state.session_factory() as s:
        p = s.scalar(select(Product))
        pid = p.id
        old = p.imagekit_file_id
    r = client.post(
        f"/products/{pid}/edit",
        data={"csrf_token": token, "name": "ماء جديد"},
        files={"image": ("b.jpg", image_bytes("JPEG", "blue"), "image/jpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert old in [x["file_id"] for x in fake.files.deleted]


def test_cleanup_idempotent(auth):
    client, app, fake, _, token = auth
    client.post(
        "/imports/new",
        data={"csrf_token": token},
        files={"file": ("x.xlsx", xlsx([("xl/media/a.png", image_bytes())]))},
    )
    with app.state.session_factory() as s:
        i = s.scalar(select(ImportedImage))
        bid = i.batch_id
    client.post(f"/imports/images/{i.id}/ignore", data={"csrf_token": token})
    client.post(f"/imports/{bid}/cleanup", data={"csrf_token": token})
    client.post(f"/imports/{bid}/cleanup", data={"csrf_token": token})
    assert len(fake.files.deleted) == 1
