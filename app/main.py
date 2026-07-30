import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.database import make_engine, make_session_factory
from app.routes.web import router
from app.security.core import Security
from app.services.arabic import ArabicNormalizationService
from app.services.cleanup import ImportCleanupService
from app.services.errors import AppError
from app.services.excel_import import ExcelImportService
from app.services.image_processing import ImageProcessingService
from app.services.imagekit import ImageKitService
from app.services.products import ProductService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
BASE = Path(__file__).parent


def create_app(settings: Settings | None = None, imagekit_client=None):
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.security = Security(settings)
    app.state.templates = Jinja2Templates(directory=BASE / "templates")
    app.state.imagekit = ImageKitService(settings=settings, client=imagekit_client)
    app.state.processor = ImageProcessingService(settings)
    app.state.excel_import = ExcelImportService(settings, app.state.processor, app.state.imagekit)
    app.state.products = ProductService(app.state.imagekit, ArabicNormalizationService())
    app.state.cleanup = ImportCleanupService(app.state.imagekit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    app.include_router(router)

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
                    f"{settings.imagekit_url_endpoint}; style-src 'self'; script-src 'self'; "
                    "frame-ancestors 'none'; form-action 'self'"
                ),
                "X-Request-ID": request.state.request_id,
                "Cache-Control": "no-store",
            }
        )
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
