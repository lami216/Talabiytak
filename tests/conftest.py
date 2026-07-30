import os

os.environ.update(
    SECRET_KEY="abcdefghijklmnopqrstuvwxyz1234567890",
    ADMIN_USERNAME="admin",
    ADMIN_PASSWORD="strong-password",
    MONGODB_URI="mongodb://localhost:27017",
    MONGODB_DATABASE="test",
    IMAGEKIT_PRIVATE_KEY="private-test",
    IMAGEKIT_PUBLIC_KEY="public-test",
    IMAGEKIT_URL_ENDPOINT="https://ik.imagekit.io/test",
    APP_ENV="test",
    TRUSTED_HOSTS="testserver,localhost",
)

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import ensure_indexes
from app.main import create_app


class AsyncCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def sort(self, *args, **kwargs):
        self.cursor = self.cursor.sort(*args, **kwargs)
        return self

    def skip(self, *args):
        self.cursor = self.cursor.skip(*args)
        return self

    def limit(self, *args):
        self.cursor = self.cursor.limit(*args)
        return self

    async def to_list(self, *args, **kwargs):
        return list(self.cursor)


class AsyncCollection:
    def __init__(self, collection):
        self.raw = collection

    def find(self, *args, **kwargs):
        return AsyncCursor(self.raw.find(*args, **kwargs))

    def aggregate(self, *args, **kwargs):
        return AsyncCursor(self.raw.aggregate(*args, **kwargs))

    async def find_one(self, *args, **kwargs):
        return self.raw.find_one(*args, **kwargs)

    async def insert_one(self, *args, **kwargs):
        return self.raw.insert_one(*args, **kwargs)

    async def update_one(self, *args, **kwargs):
        return self.raw.update_one(*args, **kwargs)

    async def delete_one(self, *args, **kwargs):
        return self.raw.delete_one(*args, **kwargs)

    async def count_documents(self, *args, **kwargs):
        return self.raw.count_documents(*args, **kwargs)

    async def create_index(self, *args, **kwargs):
        return self.raw.create_index(*args, **kwargs)

    async def index_information(self):
        return self.raw.index_information()


class AsyncDatabase:
    def __init__(self):
        self.raw = mongomock.MongoClient().db

    def __getattr__(self, name):
        return AsyncCollection(self.raw[name])

    def __getitem__(self, name):
        return AsyncCollection(self.raw[name])

    async def command(self, name):
        return {"ok": 1}

    async def list_collection_names(self):
        return self.raw.list_collection_names()


class Result:
    def __init__(self, number):
        self.file_id = f"file-{number}"
        self.file_path = f"/test/{number}.jpg"
        self.url = f"https://ik.imagekit.io/test/{number}.jpg"
        self.thumbnail_url = self.url


class Files:
    def __init__(self):
        self.uploads, self.deleted, self.updates = [], [], []
        self.fail_delete = False

    def upload(self, **kwargs):
        self.uploads.append(kwargs)
        return Result(len(self.uploads))

    def delete(self, **kwargs):
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.deleted.append(kwargs)

    def update_file_details(self, **kwargs):
        self.updates.append(kwargs)

    def details(self, **kwargs):
        return {}


class FakeImageKit:
    def __init__(self):
        self.files = Files()


@pytest.fixture
def database():
    return AsyncDatabase()


@pytest.fixture
def setup(database, tmp_path):
    settings = Settings(
        _env_file=None,
        mongodb_uri="mongodb://localhost",
        mongodb_database="test",
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
    app = create_app(settings, database=database, imagekit_client=fake)
    with TestClient(app) as client:
        yield client, app, fake, tmp_path, database


@pytest.fixture
def auth(setup):
    client, app, fake, tmp, database = setup
    response = client.post("/login", data={"username": "admin", "password": "strong-password"})
    assert response.status_code == 200
    token = app.state.security.load(client.cookies[app.state.settings.session_cookie_name])["csrf"]
    return client, app, fake, tmp, token, database


@pytest.fixture
async def indexed_database(database):
    await ensure_indexes(database)
    return database
