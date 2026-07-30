from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_name: str = "Product Image Manager"
    app_env: str = "production"
    debug: bool = False
    secret_key: str
    admin_username: str
    admin_password: str
    mongodb_uri: str
    mongodb_database: str = "talabiytak"
    imagekit_private_key: str
    imagekit_public_key: str
    imagekit_url_endpoint: str
    imagekit_folder: str = "/product-image-manager"
    max_excel_upload_mb: int = 100
    max_images_per_import: int = 2000
    max_single_image_mb: int = 25
    max_uncompressed_import_mb: int = 300
    max_zip_entries: int = 10000
    image_max_width: int = 10000
    image_max_height: int = 10000
    image_max_pixels: int = 50_000_000
    session_cookie_name: str = "product_image_session"
    session_max_age_seconds: int = 43200
    trusted_hosts: str = "localhost,127.0.0.1"
    abandoned_import_retention_days: int = 30

    @field_validator("secret_key")
    @classmethod
    def strong_secret(cls, value: str) -> str:
        if len(value) < 32 or value.startswith("replace-"):
            raise ValueError("SECRET_KEY must be a random value of at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_imagekit(self):
        missing = [
            k
            for k in ("imagekit_private_key", "imagekit_public_key", "imagekit_url_endpoint")
            if not getattr(self, k)
        ]
        if missing:
            raise ValueError(
                "ImageKit configuration is required: " + ", ".join(x.upper() for x in missing)
            )
        parsed = urlparse(self.imagekit_url_endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("IMAGEKIT_URL_ENDPOINT must be a valid HTTPS URL")
        return self

    @property
    def trusted_host_list(self):
        return [x.strip() for x in self.trusted_hosts.split(",") if x.strip()]

    @property
    def imagekit_origin(self) -> str:
        """Return the CSP-safe origin without ImageKit's account path."""
        parsed = urlparse(self.imagekit_url_endpoint)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def secure_cookies(self):
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
