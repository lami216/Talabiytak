import logging
import uuid
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.database import close_mongo, create_mongo
from app.repositories import (
    ImportedImagesRepository,
    ImportsRepository,
    OrdersRepository,
    ProductsRepository,
)
from app.repositories.orphans import OrphanCleanupRepository
from app.routes.orders import router as orders_router
from app.routes.pricing import router as pricing_router
from app.routes.web import router
from app.security.core import Security
from app.services.catalog import CatalogQueryService
from app.services.cleanup import ImportCleanupService
from app.services.errors import AppError
from app.services.excel_export import ExcelExportService
from app.services.excel_pricing import ExcelPricingService
from app.services.image_processing import ImageProcessingService
from app.services.imports import ImportService
from app.services.orders import OrderService
from app.services.products import ProductService
from app.services.storage import ImageKitStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
BASE = Path(__file__).parent

BRANDING = BASE / "static" / "branding"
BRANDING_SOURCE = BRANDING / "talabiytak-logo-source.png"
BRANDING_OUTPUTS = {
    "talabiytak-logo-48.png": 48,
    "talabiytak-favicon-32.png": 32,
    "talabiytak-apple-touch-180.png": 180,
    "talabiytak-icon-192.png": 192,
    "talabiytak-icon-512.png": 512,
}
BRANDING_MASKABLE = BRANDING / "talabiytak-maskable-512.png"


def _contain_branding_icon(image: Image.Image, size: int) -> Image.Image:
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    copy = image.copy()
    copy.thumbnail((size, size), Image.Resampling.LANCZOS)
    result.alpha_composite(copy, ((size - copy.width) // 2, (size - copy.height) // 2))
    return result


def _build_maskable_branding_icon(image: Image.Image) -> Image.Image:
    result = Image.new("RGBA", (512, 512), "#0b5d4b")
    safe = image.copy()
    safe.thumbnail((328, 328), Image.Resampling.LANCZOS)
    result.alpha_composite(safe, ((512 - safe.width) // 2, (512 - safe.height) // 2))
    return result


def ensure_branding_assets() -> None:
    """Build required web branding PNGs from the tracked source logo when absent."""
    if not BRANDING_SOURCE.exists():
        return
    missing_assets = [
        BRANDING / filename for filename in BRANDING_OUTPUTS if not (BRANDING / filename).is_file()
    ]
    if not BRANDING_MASKABLE.is_file():
        missing_assets.append(BRANDING_MASKABLE)
    if not missing_assets:
        return
    source = Image.open(BRANDING_SOURCE).convert("RGBA")
    if source.width != source.height:
        raise RuntimeError("talabiytak-logo-source.png must be square")
    BRANDING.mkdir(parents=True, exist_ok=True)
    for filename, size in BRANDING_OUTPUTS.items():
        output = BRANDING / filename
        if output in missing_assets:
            _contain_branding_icon(source, size).save(output, "PNG", optimize=True)
    if BRANDING_MASKABLE in missing_assets:
        _build_maskable_branding_icon(source).save(BRANDING_MASKABLE, "PNG", optimize=True)


ensure_branding_assets()
VERSIONED_ASSETS = (
    "style.css",
    "orders.js",
    "app.js",
    "manifest.webmanifest",
    "service-worker.js",
    "branding/talabiytak-logo-48.png",
    "branding/talabiytak-favicon-32.png",
    "branding/talabiytak-apple-touch-180.png",
    "branding/talabiytak-icon-192.png",
    "branding/talabiytak-icon-512.png",
    "branding/talabiytak-maskable-512.png",
)


def _asset_version(path: Path) -> str:
    """Return a stable version that changes only when the asset contents change."""
    if not path.exists():
        return "missing"
    return sha256(path.read_bytes()).hexdigest()[:12]


ASSET_VERSIONS = {
    filename: _asset_version(BASE / "static" / filename) for filename in VERSIONED_ASSETS
}


def asset_version(filename: str) -> str:
    """Look up an allow-listed, startup-cached static asset version for templates."""
    return ASSET_VERSIONS[filename]


def configure_services(app, database, storage):
    imports = ImportsRepository(database)
    images = ImportedImagesRepository(database)
    products = ProductsRepository(database)
    orders = OrdersRepository(database)
    orphans = OrphanCleanupRepository(database)
    processor = ImageProcessingService(app.state.settings)
    app.state.imports = ImportService(
        app.state.settings, processor, storage, imports, images, products, orphans
    )
    app.state.products = ProductService(storage, products, images, orphans, orders=orders)
    app.state.orders = OrderService(app.state.settings, orders, products)
    app.state.excel_export = ExcelExportService(app.state.settings, products)
    app.state.excel_pricing = ExcelPricingService(app.state.settings)
    app.state.cleanup = ImportCleanupService(storage, products, images)
    app.state.catalog = CatalogQueryService(database, imports, images, products, orders)
    app.state.processor = processor
    app.state.repositories = type(
        "Repositories",
        (),
        {
            "imports": imports,
            "images": images,
            "products": products,
            "orders": orders,
            "orphans": orphans,
        },
    )()
    app.state.storage = storage


def create_app(
    settings: Settings | None = None,
    *,
    database=None,
    imagekit_client=None,
    imagekit_upload_transport=None,
):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        client = None
        db = database
        if db is None:
            client, db = create_mongo(settings)
            await db.command("ping")
        app.state.mongo_client, app.state.database = client, db
        configure_services(
            app, db, ImageKitStorage(settings, imagekit_client, imagekit_upload_transport)
        )
        try:
            yield
        finally:
            if client is not None:
                await close_mongo(client)

    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    app.state.security = Security(settings)
    app.state.templates = Jinja2Templates(directory=BASE / "templates")
    app.state.templates.env.globals["asset_version"] = asset_version
    app.state.templates.env.globals["imagekit_url"] = lambda asset: (
        settings.imagekit_delivery_url(asset.file_path) if asset else None
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    app.include_router(router)
    app.include_router(orders_router)
    app.include_router(pricing_router)

    @app.get("/service-worker.js", include_in_schema=False)
    async def service_worker():
        response = FileResponse(BASE / "static" / "service-worker.js", media_type="text/javascript")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.middleware("http")
    async def headers(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id", uuid.uuid4().hex)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "Content-Security-Policy": (
                    f"default-src 'self'; img-src 'self' data: "
                    f"{settings.imagekit_origin}; style-src 'self'; script-src 'self'; "
                    "frame-ancestors 'none'; form-action 'self'"
                ),
                "X-Request-ID": request.state.request_id,
                "Cache-Control": "no-store",
            }
        )
        if request.url.path == "/service-worker.js":
            response.headers["Cache-Control"] = "no-cache"
            response.headers["Service-Worker-Allowed"] = "/"
        if request.url.path == "/static/manifest.webmanifest":
            response.headers["Content-Type"] = "application/manifest+json"
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"request": request, "code": 400, "message": str(exc), "session": None},
            status_code=400,
        )

    @app.exception_handler(404)
    async def not_found(request, exc):
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "request": request,
                "code": 404,
                "message": "الصفحة المطلوبة غير موجودة",
                "session": None,
            },
            status_code=404,
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logging.getLogger(__name__).exception(
            "unexpected request error", extra={"request_id": request.state.request_id}
        )
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "request": request,
                "code": 500,
                "message": f"حدث خطأ غير متوقع. رقم الطلب: {request.state.request_id}",
                "session": None,
            },
            status_code=500,
        )

    return app


app = create_app()
