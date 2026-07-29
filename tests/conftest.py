import os

os.environ.update(
    SECRET_KEY="abcdefghijklmnopqrstuvwxyz1234567890",
    ADMIN_USERNAME="admin",
    ADMIN_PASSWORD="strong-password",
    DATABASE_URL="sqlite://",
    IMAGEKIT_PRIVATE_KEY="private-test",
    IMAGEKIT_PUBLIC_KEY="public-test",
    IMAGEKIT_URL_ENDPOINT="https://ik.imagekit.io/test",
    APP_ENV="test",
    TRUSTED_HOSTS="testserver,localhost",
)
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Base
from app.main import create_app


class Result:
    def __init__(self, n):
        self.response_metadata = type(
            "M",
            (),
            {
                "raw": {
                    "fileId": f"file-{n}",
                    "filePath": f"/test/{n}.jpg",
                    "url": f"https://ik.imagekit.io/test/{n}.jpg",
                    "thumbnailUrl": f"https://ik.imagekit.io/test/tr:n-media_library_thumbnail/{n}.jpg",
                }
            },
        )()


class Files:
    def __init__(self):
        self.uploads = []
        self.deleted = []
        self.updates = []

    def upload(self, **kwargs):
        self.uploads.append(kwargs)
        return Result(len(self.uploads))

    def delete(self, **kwargs):
        self.deleted.append(kwargs)

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def get(self, **kwargs):
        return {}


class FakeImageKit:
    def __init__(self):
        self.files = Files()


@pytest.fixture
def setup(tmp_path):
    db = tmp_path / "app.db"
    settings = Settings(
        database_url=f"sqlite:///{db}",
        secret_key="abcdefghijklmnopqrstuvwxyz1234567890",
        admin_username="admin",
        admin_password="strong-password",
        imagekit_private_key="private-test",
        imagekit_public_key="public-test",
        imagekit_url_endpoint="https://ik.imagekit.io/test",
        app_env="test",
        trusted_hosts="testserver,localhost",
    )
    fake = FakeImageKit()
    app = create_app(settings, fake)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        yield client, app, fake, tmp_path


@pytest.fixture
def auth(setup):
    client, app, fake, tmp = setup
    r = client.post("/login", data={"username": "admin", "password": "strong-password"})
    assert r.status_code == 200
    token = app.state.security.load(client.cookies[app.state.settings.session_cookie_name])["csrf"]
    return client, app, fake, tmp, token
