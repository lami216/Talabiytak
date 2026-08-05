import zipfile
from copy import deepcopy
from io import BytesIO

from bson import ObjectId
from PIL import Image


def png(color="red"):
    output = BytesIO()
    Image.new("RGB", (12, 12), color).save(output, "PNG")
    return output.getvalue()


def workbook(*images):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for number, image in enumerate(images, 1):
            archive.writestr(f"xl/media/{number}.png", image)
    return output.getvalue()


def upload(client, token, *images):
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files={"file": ("filters.xlsx", workbook(*images))},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].rsplit("/", 1)[-1]


def test_server_side_filters_counts_and_safe_status(auth):
    client, _, _, _, token, database = auth
    import_id = upload(client, token, png())
    original = database.raw.imported_images.find_one({"import_id": ObjectId(import_id)})
    statuses = [
        "unnamed",
        "unnamed",
        "saved_as_product",
        "ignored",
        "ignored",
        "duplicate",
        "duplicate",
        "duplicate",
        "upload_failed",
    ]
    database.raw.imported_images.delete_many({"import_id": ObjectId(import_id)})
    for sequence, status in enumerate(statuses, 1):
        document = deepcopy(original)
        document.update(_id=ObjectId(), sequence_number=sequence, status=status)
        database.raw.imported_images.insert_one(document)

    # A record from another batch must never leak into these results.
    foreign = deepcopy(original)
    foreign.update(_id=ObjectId(), import_id=ObjectId(), status="duplicate")
    database.raw.imported_images.insert_one(foreign)

    expected = {
        "all": 7,
        "unnamed": 2,
        "saved_as_product": 1,
        "duplicate": 3,
        "upload_failed": 1,
    }
    for status, count in expected.items():
        response = client.get(f"/imports/{import_id}?status={status}&page=1")
        assert response.status_code == 200
        assert response.text.count('class="card image-card"') == count
        assert f"?status={status}&amp;page=1" in response.text

    unknown = client.get(f"/imports/{import_id}?status[$ne]=x")
    assert unknown.status_code == 200
    assert unknown.text.count('class="card image-card"') == 7
    unknown = client.get(f"/imports/{import_id}?status=not-a-status")
    assert unknown.text.count('class="card image-card"') == 7


def test_duplicate_creation_cases_are_not_grouped(auth):
    client, _, _, _, token, database = auth
    image = png("blue")

    first_batch = upload(client, token, image, image)
    first_rows = list(
        database.raw.imported_images.find({"import_id": ObjectId(first_batch)}).sort(
            "sequence_number"
        )
    )
    assert [row["status"] for row in first_rows] == ["unnamed", "duplicate"]
    assert (
        client.get(f"/imports/{first_batch}?status=unnamed").text.count('class="card image-card"')
        == 1
    )
    assert (
        client.get(f"/imports/{first_batch}?status=duplicate").text.count('class="card image-card"')
        == 1
    )

    second_batch = upload(client, token, image)
    assert (
        database.raw.imported_images.count_documents(
            {"import_id": ObjectId(second_batch), "status": "duplicate"}
        )
        == 1
    )

    third_batch = upload(client, token, image, image)
    assert (
        database.raw.imported_images.count_documents(
            {"import_id": ObjectId(third_batch), "status": "duplicate"}
        )
        == 2
    )
    assert (
        client.get(f"/imports/{third_batch}?status=duplicate").text.count('class="card image-card"')
        == 2
    )


def test_image_actions_preserve_validated_filter_and_page(auth):
    client, _, _, _, token, database = auth
    import_id = upload(client, token, png("green"), png("green"))
    rows = list(
        database.raw.imported_images.find({"import_id": ObjectId(import_id)}).sort(
            "sequence_number"
        )
    )
    unnamed_id, duplicate_id = map(lambda row: str(row["_id"]), rows)

    deleted = client.post(
        f"/imports/images/{duplicate_id}/delete",
        data={"csrf_token": token, "return_status": "duplicate", "return_page": "1"},
        follow_redirects=False,
    )
    assert deleted.headers["location"] == f"/imports/{import_id}?status=duplicate&page=1"
    assert database.raw.imported_images.find_one({"_id": ObjectId(duplicate_id)}) is None

    saved = client.post(
        f"/imports/images/{unnamed_id}/save",
        data={
            "csrf_token": token,
            "name": "منتج محفوظ",
            "return_status": "unnamed",
            "return_page": "7",
        },
        headers={"X-Requested-With": "fetch"},
    )
    assert saved.json()["new_status"] == "saved_as_product"
    assert saved.json()["redirect_url"] == f"/imports/{import_id}?status=unnamed&page=1"

    # Untrusted values can influence neither the host nor the MongoDB status expression.
    cleanup = client.post(
        f"/imports/{import_id}/cleanup",
        data={
            "csrf_token": token,
            "return_status": "https://evil.example/",
            "return_page": "not-a-number",
        },
        follow_redirects=False,
    )
    assert cleanup.headers["location"] == f"/imports/{import_id}?status=all&page=1"


def test_navigation_and_filter_markup(auth):
    client, _, _, _, token, _ = auth
    import_id = upload(client, token, png("yellow"))
    html = client.get(f"/imports/{import_id}?status=unnamed&page=1").text
    for class_name in (
        "main-nav",
        "nav-link",
        "nav-link-active",
        "batch-filters",
        "filter-button",
        "filter-button-active",
        "filter-count",
    ):
        assert class_name in html
    assert 'aria-current="page"' in html
    assert 'name="return_status" value="unnamed"' in html
    assert 'name="return_page" value="1"' in html
