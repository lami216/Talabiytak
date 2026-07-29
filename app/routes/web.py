import math

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import csrf_ok, get_db, require_admin, session_data
from app.models import ImageStatus, ImportBatch, ImportedImage, Product
from app.services.errors import AppError

router = APIRouter()


def render(r, name, status_code=200, **ctx):
    return r.app.state.templates.TemplateResponse(
        request=r,
        name=name,
        context={"request": r, "session": session_data(r), **ctx},
        status_code=status_code,
    )


def guard(r):
    return require_admin(r)


def check(r, token):
    if not csrf_ok(r, token):
        raise AppError("رمز الحماية غير صالح، أعد تحميل الصفحة")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request):
    try:
        with request.app.state.engine.connect() as c:
            c.exec_driver_sql("SELECT 1")
        return {"status": "ready", "database": "ok", "imagekit": "configured"}
    except Exception:
        return JSONResponse({"status": "not_ready"}, 503)


@router.get("/login", response_class=HTMLResponse)
def login_page(r: Request):
    return render(r, "login.html")


@router.post("/login")
def login(r: Request, username: str = Form(...), password: str = Form(...)):
    client = r.client.host if r.client else "unknown"
    if not r.app.state.security.verify(username, password, client):
        return render(r, "login.html", error="اسم المستخدم أو كلمة المرور غير صحيحة")
    out = RedirectResponse("/", 303)
    out.set_cookie(
        r.app.state.settings.session_cookie_name,
        r.app.state.security.new_session(),
        max_age=r.app.state.settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=r.app.state.settings.secure_cookies,
    )
    return out


@router.post("/logout")
def logout(r: Request, csrf_token: str = Form(...)):
    check(r, csrf_token)
    out = RedirectResponse("/login", 303)
    out.delete_cookie(r.app.state.settings.session_cookie_name)
    return out


@router.get("/", response_class=HTMLResponse)
def dashboard(r: Request, s: Session = Depends(get_db)):
    x = guard(r)
    if isinstance(x, RedirectResponse):
        return x
    stats = {
        "products": s.scalar(select(func.count(Product.id))),
        "unnamed": s.scalar(
            select(func.count(ImportedImage.id)).where(
                ImportedImage.status == ImageStatus.unnamed.value
            )
        ),
        "batches": s.scalar(select(func.count(ImportBatch.id))),
    }
    return render(
        r,
        "dashboard.html",
        stats=stats,
        batches=s.scalars(
            select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(6)
        ).all(),
        products=s.scalars(select(Product).order_by(Product.created_at.desc()).limit(6)).all(),
    )


@router.get("/imports/new", response_class=HTMLResponse)
def import_new(r: Request):
    x = guard(r)
    return x if isinstance(x, RedirectResponse) else render(r, "import_new.html")


@router.post("/imports/new")
def import_create(
    r: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    s: Session = Depends(get_db),
):
    x = guard(r)
    if isinstance(x, RedirectResponse):
        return x
    check(r, csrf_token)
    try:
        batch = r.app.state.excel_import.import_upload(s, file.filename or "", file.file)
    except AppError as exc:
        return render(r, "import_new.html", status_code=400, error=str(exc))
    finally:
        file.file.close()
    return RedirectResponse(f"/imports/{batch.id}", 303)


@router.get("/imports", response_class=HTMLResponse)
def imports(r: Request, s: Session = Depends(get_db)):
    x = guard(r)
    return (
        x
        if isinstance(x, RedirectResponse)
        else render(
            r,
            "imports.html",
            batches=s.scalars(
                select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100)
            ).all(),
        )
    )


@router.get("/imports/{batch_id}", response_class=HTMLResponse)
def batch_page(
    batch_id: int, r: Request, page: int = 1, status: str = "all", s: Session = Depends(get_db)
):
    x = guard(r)
    if isinstance(x, RedirectResponse):
        return x
    batch = s.get(ImportBatch, batch_id)
    if not batch:
        return render(
            r, "error.html", status_code=404, code=404, message="دفعة الاستيراد غير موجودة"
        )
    q = select(ImportedImage).where(ImportedImage.batch_id == batch_id)
    if status != "all":
        q = q.where(ImportedImage.status == status)
    images = s.scalars(
        q.order_by(ImportedImage.sequence_number).offset((page - 1) * 48).limit(48)
    ).all()
    counts = dict(
        s.execute(
            select(ImportedImage.status, func.count())
            .where(ImportedImage.batch_id == batch_id)
            .group_by(ImportedImage.status)
        ).all()
    )
    return render(
        r, "batch.html", batch=batch, images=images, counts=counts, page=page, status=status
    )


@router.post("/imports/images/{image_id}/save")
def save_image(
    image_id: int,
    r: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    s: Session = Depends(get_db),
):
    x = guard(r)
    if isinstance(x, RedirectResponse):
        return x
    check(r, csrf_token)
    try:
        p = r.app.state.products.create_from_import(s, image_id, name)
        return (
            JSONResponse({"ok": True, "message": "تم حفظ المنتج", "product_id": p.id})
            if r.headers.get("x-requested-with")
            else RedirectResponse(f"/imports/{s.get(ImportedImage, image_id).batch_id}", 303)
        )
    except AppError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, 400)


@router.post("/imports/images/{image_id}/ignore")
def ignore_image(
    image_id: int, r: Request, csrf_token: str = Form(...), s: Session = Depends(get_db)
):
    check(r, csrf_token)
    image = s.get(ImportedImage, image_id)
    if image and not image.linked_product_id:
        image.status = ImageStatus.ignored.value
        s.commit()
    return RedirectResponse(f"/imports/{image.batch_id}", 303)


@router.post("/imports/{batch_id}/cleanup")
def cleanup_batch(
    batch_id: int, r: Request, csrf_token: str = Form(...), s: Session = Depends(get_db)
):
    check(r, csrf_token)
    images = s.scalars(select(ImportedImage).where(ImportedImage.batch_id == batch_id)).all()
    r.app.state.cleanup.cleanup(s, images)
    return RedirectResponse(f"/imports/{batch_id}", 303)


@router.get("/products", response_class=HTMLResponse)
def products(r: Request, q: str = "", page: int = 1, s: Session = Depends(get_db)):
    x = guard(r)
    if isinstance(x, RedirectResponse):
        return x
    items, total = r.app.state.products.search(s, q, page)
    return render(
        r, "products.html", products=items, q=q, page=page, pages=max(1, math.ceil(total / 24))
    )


@router.get("/products/new", response_class=HTMLResponse)
def product_new(r: Request):
    x = guard(r)
    return x if isinstance(x, RedirectResponse) else render(r, "product_form.html", product=None)


@router.post("/products/new")
def product_create(
    r: Request,
    name: str = Form(...),
    image: UploadFile = File(...),
    csrf_token: str = Form(...),
    s: Session = Depends(get_db),
):
    check(r, csrf_token)
    try:
        processed = r.app.state.processor.process(image.file.read())
        p = r.app.state.products.create_manual(s, name, processed)
        return RedirectResponse(f"/products/{p.id}/edit", 303)
    except AppError as exc:
        return render(r, "product_form.html", status_code=400, product=None, error=str(exc))
    finally:
        image.file.close()


@router.get("/products/{product_id}/edit", response_class=HTMLResponse)
def product_edit(product_id: int, r: Request, s: Session = Depends(get_db)):
    x = guard(r)
    p = s.get(Product, product_id)
    return (
        x
        if isinstance(x, RedirectResponse)
        else (
            render(r, "product_form.html", product=p)
            if p
            else (render(r, "error.html", code=404, message="المنتج غير موجود"), 404)
        )
    )


@router.post("/products/{product_id}/edit")
def product_update(
    product_id: int,
    r: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    image: UploadFile | None = File(None),
    s: Session = Depends(get_db),
):
    check(r, csrf_token)
    p = s.get(Product, product_id)
    if not p:
        return render(r, "error.html", code=404, message="المنتج غير موجود"), 404
    try:
        r.app.state.products.rename(s, p, name)
        if image and image.filename:
            r.app.state.products.replace(s, p, r.app.state.processor.process(image.file.read()))
        return RedirectResponse("/products", 303)
    except AppError as exc:
        return render(r, "product_form.html", status_code=400, product=p, error=str(exc))
    finally:
        if image:
            image.file.close()


@router.post("/products/{product_id}/delete")
def product_delete(
    product_id: int,
    r: Request,
    csrf_token: str = Form(...),
    confirm: str = Form(""),
    s: Session = Depends(get_db),
):
    check(r, csrf_token)
    p = s.get(Product, product_id)
    if p and confirm == "delete":
        r.app.state.products.delete(s, p)
    return RedirectResponse("/products", 303)
