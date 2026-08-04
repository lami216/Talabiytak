import os
import re
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.dependencies import csrf_ok, require_admin, session_data
from app.services.errors import AppError, ValidationError

router = APIRouter()
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render(request, status_code=200, **context):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="pricing.html",
        context={"request": request, "session": session_data(request), **context},
        status_code=status_code,
    )


def safe_download_name(filename):
    name = os.path.basename((filename or "file.xlsx").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "", name).strip(" .")
    stem = name[:-5] if name.lower().endswith(".xlsx") else "file"
    stem = stem[:120] or "file"
    return f"{stem}-محسوب.xlsx"


@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    result = require_admin(request)
    return result if isinstance(result, RedirectResponse) else render(request)


@router.post("/pricing")
async def pricing_transform(
    request: Request,
    file: UploadFile | None = File(None),
    rmb_rate: str = Form(""),
    shipping_cost_per_cbm: str = Form(""),
    csrf_token: str = Form(""),
):
    if isinstance(result := require_admin(request), RedirectResponse):
        if file is not None:
            await file.close()
        return result
    try:
        if not csrf_ok(request, csrf_token):
            raise AppError("رمز الحماية غير صالح، أعد تحميل الصفحة")
        if file is None or not (file.filename or "").lower().endswith(".xlsx"):
            raise ValidationError("هذه الميزة تدعم ملفات XLSX فقط.")
        limit = request.app.state.settings.max_excel_upload_mb * 1024 * 1024
        source = await file.read(limit + 1)
        if not source or len(source) > limit:
            raise ValidationError("اختر ملف XLSX صالحًا.")
        transformed = await request.app.state.excel_pricing.transform(
            source, rmb_rate, shipping_cost_per_cbm, filename=file.filename
        )
        download = safe_download_name(file.filename)
        ascii_name = "calculated.xlsx"
        disposition = f"attachment; filename={ascii_name}; filename*=UTF-8''{quote(download)}"
        return Response(
            transformed,
            media_type=MIME,
            headers={"Content-Disposition": disposition},
        )
    except AppError as exc:
        return render(
            request,
            status_code=400,
            error=str(exc),
            rmb_rate=rmb_rate,
            shipping_cost_per_cbm=shipping_cost_per_cbm,
        )
    finally:
        if file is not None:
            await file.close()
