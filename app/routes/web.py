import math

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.dependencies import csrf_ok, require_admin, session_data
from app.services.errors import AppError, ValidationError

router = APIRouter()


def render(request, name, status_code=200, **context):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name=name,
        context={"request": request, "session": session_data(request), **context},
        status_code=status_code,
    )


def guard(request):
    return require_admin(request)


def check(request, token):
    if not csrf_ok(request, token):
        raise AppError("رمز الحماية غير صالح، أعد تحميل الصفحة")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request):
    try:
        return await request.app.state.catalog.readiness()
    except Exception:
        return JSONResponse({"status": "not_ready"}, 503)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render(request, "login.html")


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    client = request.client.host if request.client else "unknown"
    if not request.app.state.security.verify(username, password, client):
        return render(request, "login.html", error="اسم المستخدم أو كلمة المرور غير صحيحة")
    response = RedirectResponse("/", 303)
    response.set_cookie(
        request.app.state.settings.session_cookie_name,
        request.app.state.security.new_session(),
        max_age=request.app.state.settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.secure_cookies,
    )
    return response


@router.post("/logout")
async def logout(request: Request, csrf_token: str = Form(...)):
    check(request, csrf_token)
    response = RedirectResponse("/login", 303)
    response.delete_cookie(request.app.state.settings.session_cookie_name)
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    stats, batches, products, orders = await request.app.state.catalog.dashboard()
    return render(
        request, "dashboard.html", stats=stats, batches=batches, products=products, orders=orders
    )


@router.get("/imports/new", response_class=HTMLResponse)
async def import_new(request: Request):
    result = guard(request)
    return result if isinstance(result, RedirectResponse) else render(request, "import_new.html")


@router.post("/imports/new")
async def import_create(
    request: Request, file: UploadFile = File(...), csrf_token: str = Form(...)
):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    check(request, csrf_token)
    try:
        item = await request.app.state.imports.import_upload(file.filename or "", file.file)
    except AppError as exc:
        return render(request, "import_new.html", status_code=400, error=str(exc))
    finally:
        await file.close()
    return RedirectResponse(f"/imports/{item.id}", 303)


@router.get("/imports", response_class=HTMLResponse)
async def imports(request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    return render(request, "imports.html", batches=await request.app.state.imports.list_imports())


@router.get("/imports/{import_id}", response_class=HTMLResponse)
async def batch_page(import_id: str, request: Request, page: int = 1, status: str = "all"):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    try:
        result = await request.app.state.imports.get_batch(import_id, max(page, 1), status)
    except ValidationError:
        result = None
    if not result:
        return render(
            request, "error.html", status_code=404, code=404, message="دفعة الاستيراد غير موجودة"
        )
    batch, images, counts = result
    return render(
        request, "batch.html", batch=batch, images=images, counts=counts, page=page, status=status
    )


@router.post("/imports/images/{image_id}/save")
async def save_image(
    image_id: str, request: Request, name: str = Form(...), csrf_token: str = Form(...)
):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    check(request, csrf_token)
    try:
        product = await request.app.state.products.create_from_import(image_id, name)
        image = await request.app.state.imports.get_image(image_id)
        return (
            JSONResponse({"ok": True, "message": "تم حفظ المنتج", "product_id": product.id})
            if request.headers.get("x-requested-with")
            else RedirectResponse(f"/imports/{image.import_id}", 303)
        )
    except AppError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, 400)


@router.post("/imports/images/{image_id}/ignore")
async def ignore_image(image_id: str, request: Request, csrf_token: str = Form(...)):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    check(request, csrf_token)
    try:
        image = await request.app.state.imports.ignore_image(image_id)
    except ValidationError:
        image = None
    return RedirectResponse(f"/imports/{image.import_id}" if image else "/imports", 303)


@router.post("/imports/{import_id}/cleanup")
async def cleanup_batch(import_id: str, request: Request, csrf_token: str = Form(...)):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    check(request, csrf_token)
    await request.app.state.cleanup.cleanup_import(import_id)
    return RedirectResponse(f"/imports/{import_id}", 303)


@router.get("/products", response_class=HTMLResponse)
async def products(request: Request, q: str = "", page: int = 1):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    items, total = await request.app.state.products.search(q, max(page, 1))
    return render(
        request,
        "products.html",
        products=items,
        q=q,
        page=page,
        pages=max(1, math.ceil(total / 24)),
    )


@router.get("/products/new", response_class=HTMLResponse)
async def product_new(request: Request):
    result = guard(request)
    return (
        result
        if isinstance(result, RedirectResponse)
        else render(request, "product_form.html", product=None)
    )


@router.post("/products/new")
async def product_create(
    request: Request,
    name: str = Form(...),
    image: UploadFile = File(...),
    csrf_token: str = Form(...),
):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    check(request, csrf_token)
    try:
        processed = request.app.state.processor.process(await image.read())
        product = await request.app.state.products.create_manual(name, processed)
        return RedirectResponse(f"/products/{product.id}/edit", 303)
    except AppError as exc:
        return render(request, "product_form.html", status_code=400, product=None, error=str(exc))
    finally:
        await image.close()


@router.get("/products/{product_id}/edit", response_class=HTMLResponse)
async def product_edit(product_id: str, request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    try:
        product = await request.app.state.products.get(product_id)
    except ValidationError:
        product = None
    return (
        render(request, "product_form.html", product=product)
        if product
        else render(request, "error.html", status_code=404, code=404, message="المنتج غير موجود")
    )


@router.post("/products/{product_id}/edit")
async def product_update(
    product_id: str,
    request: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    image: UploadFile | None = File(None),
):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    check(request, csrf_token)
    try:
        product = await request.app.state.products.rename(product_id, name)
        if image and image.filename:
            product = await request.app.state.products.replace(
                product_id, request.app.state.processor.process(await image.read())
            )
        return RedirectResponse("/products", 303)
    except AppError as exc:
        return render(
            request,
            "product_form.html",
            status_code=400,
            product=locals().get("product"),
            error=str(exc),
        )
    finally:
        if image:
            await image.close()


@router.post("/products/{product_id}/delete")
async def product_delete(
    product_id: str, request: Request, csrf_token: str = Form(...), confirm: str = Form("")
):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    check(request, csrf_token)
    if confirm == "delete":
        try:
            await request.app.state.products.delete(product_id)
        except ValidationError:
            pass
    return RedirectResponse("/products", 303)
