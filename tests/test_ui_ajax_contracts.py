from pathlib import Path


def read(path):
    return Path(path).read_text(encoding="utf-8")


def test_shared_image_ui_is_discoverable_contract():
    product_form = read("app/templates/product_form.html")
    products = read("app/templates/products.html")
    assert 'id="shared-image-product"' in product_form
    assert "إضافة منتج آخر بنفس الصورة" in product_form
    assert "shared-image-product-form" in product_form
    assert "ينشئ منتجًا مستقلًا يستخدم الصورة نفسها دون رفع الصورة مرة أخرى." in product_form
    assert "منتج آخر بنفس الصورة" in products
    assert "#shared-image-product" in products


def test_batch_partial_and_ajax_contracts():
    batch = read("app/templates/batch.html")
    partial = read("app/templates/partials/batch_content.html")
    app_js = read("app/static/app.js")
    assert "data-batch-content" in batch
    assert "partials/batch_content.html" in batch
    assert "data-batch-filters" in partial
    assert "filter-button-active" in partial
    assert "window.location.assign(data.redirect_url)" not in app_js
    assert 'fetch(url, { headers: { "X-Requested-With": "fetch" }' in app_js
    assert "history.pushState" in app_js
    assert "popstate" in app_js
    assert "AbortController" in app_js
    assert "previousScrollY = window.scrollY" in app_js
    assert "delete-image-form" in app_js
    assert "shared-image-product-form" in app_js


def test_navigation_visibility_contracts():
    base = read("app/templates/base.html")
    app_js = read("app/static/app.js")
    assert "data-main-nav" in base
    assert "data-active-nav" in base
    assert "ensureActiveNavigationVisible();" in app_js
    assert "scrollChildIntoContainer" in app_js
    nav_section = app_js[
        app_js.index("function ensureActiveNavigationVisible") : app_js.index(
            "function ensureActiveBatchFilterVisible"
        )
    ]
    assert "window.scrollTo" not in nav_section
    assert "حساب الأسعار" in base
    assert "تسجيل الخروج" in base
    assert "ensureActiveBatchFilterVisible" in app_js
