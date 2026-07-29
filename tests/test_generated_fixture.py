from io import BytesIO
from zipfile import ZipFile

from PIL import Image
from sqlalchemy import func, select

from app.models import ImportedImage
from tests.fixture_factory import embedded_images_xlsx


def test_generated_xlsx_fixture_imports_real_decodable_images(auth):
    """The generated XLSX is genuine and imports through the complete HTTP workflow."""
    client, app, fake_imagekit, _, csrf_token = auth
    workbook = embedded_images_xlsx()

    with ZipFile(BytesIO(workbook)) as archive:
        media_names = sorted(name for name in archive.namelist() if name.startswith("xl/media/"))
        assert media_names == [
            "xl/media/image1.png",
            "xl/media/image2.jpg",
            "xl/media/image3.webp",
        ]
        for media_name in media_names:
            with Image.open(BytesIO(archive.read(media_name))) as image:
                image.verify()

    response = client.post(
        "/imports/new",
        data={"csrf_token": csrf_token},
        files={
            "file": (
                "embedded-images.xlsx",
                workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(fake_imagekit.files.uploads) == 3
    assert all(isinstance(upload["file"], bytes) for upload in fake_imagekit.files.uploads)
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count(ImportedImage.id))) == 3
