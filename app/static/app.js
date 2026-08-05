let notificationTimer;
let batchAbortController;

function setBusy(form, busy) {
  form.querySelectorAll("button, input[type='submit']").forEach((control) => {
    control.disabled = busy;
  });
  form.setAttribute("aria-busy", String(busy));
}

function showNotification(message, type = "error") {
  let notice = document.querySelector(".app-notification");
  if (!notice) {
    notice = document.createElement("div");
    notice.className = "app-notification";
    notice.setAttribute("role", "status");
    document.body.append(notice);
  }
  window.clearTimeout(notificationTimer);
  notice.hidden = false;
  notice.dataset.type = type;
  notice.textContent = message;
  notificationTimer = window.setTimeout(() => { notice.hidden = true; }, type === "error" ? 5000 : 2500);
}

function scrollChildIntoContainer(container, child) {
  if (!container || !child) return;
  const containerRect = container.getBoundingClientRect();
  const childRect = child.getBoundingClientRect();
  const current = container.scrollLeft;
  const delta = (childRect.left + childRect.width / 2) - (containerRect.left + containerRect.width / 2);
  container.scrollTo({ left: current + delta, behavior: "instant" });
}

function ensureActiveNavigationVisible() {
  scrollChildIntoContainer(document.querySelector("[data-main-nav]"), document.querySelector("[data-main-nav] [data-active-nav], [data-main-nav] .nav-link-active"));
}

function ensureActiveBatchFilterVisible() {
  scrollChildIntoContainer(document.querySelector("[data-batch-filters]"), document.querySelector("[data-batch-filters] [data-active-filter], [data-batch-filters] .filter-button-active"));
}

function preserveDocumentScroll(callback) {
  const previousScrollY = window.scrollY;
  callback();
  window.scrollTo({ top: Math.min(previousScrollY, document.documentElement.scrollHeight - window.innerHeight), behavior: "instant" });
}

function replaceBatchContent(html) {
  const container = document.querySelector("[data-batch-content]");
  if (!container) return;
  const template = document.createElement("template");
  template.innerHTML = html;
  preserveDocumentScroll(() => container.replaceChildren(template.content.cloneNode(true)));
  ensureActiveBatchFilterVisible();
}

async function loadBatchPartial(url, options = {}) {
  const container = document.querySelector("[data-batch-content]");
  if (!container) return;
  if (batchAbortController) batchAbortController.abort();
  batchAbortController = new AbortController();
  container.classList.add("is-loading");
  try {
    const response = await fetch(url, { headers: { "X-Requested-With": "fetch" }, signal: batchAbortController.signal });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.message || "تعذر تحميل الدفعة");
    replaceBatchContent(data.html);
    if (options.push !== false) history.pushState({ batchUrl: data.url }, "", data.url);
    if (options.scrollToGrid) document.querySelector("[data-batch-grid]")?.scrollIntoView({ block: "start", behavior: "instant" });
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotification(error.message || "تعذر تحميل الدفعة", "error");
      if (options.fallbackUrl) window.location.href = options.fallbackUrl;
    }
  } finally {
    container.classList.remove("is-loading");
  }
}

function appendSharedProduct(list, product) {
  if (!list || !product) return;
  const item = document.createElement("li");
  const link = document.createElement("a");
  link.href = product.edit_url;
  link.textContent = product.name;
  item.append(link);
  list.append(item);
}

function initializeSharedImagePanel(card, product, finishUrl = window.location.href) {
  card.dataset.sourceProductId = product.id;
  card.dataset.finishUrl = finishUrl;
  card.classList.add("image-card-saved");
  card.querySelectorAll(".save-product, .delete-image-form").forEach((node) => node.remove());
  const status = card.querySelector("[data-image-status]");
  if (status) status.textContent = "saved_as_product";
  const panel = document.createElement("section");
  panel.className = "shared-image-product batch-shared-image";
  panel.dataset.sharedImagePanel = "";
  const title = document.createElement("h3");
  title.textContent = "تم إنشاء المنتج";
  const created = document.createElement("p");
  created.textContent = product.name;
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "secondary";
  toggle.textContent = "إضافة منتج آخر بنفس الصورة";
  const finish = document.createElement("button");
  finish.type = "button";
  finish.dataset.finishSharedImage = "";
  finish.textContent = "إنهاء";
  const form = document.createElement("form");
  form.className = "shared-image-product-form";
  form.action = `/products/${product.id}/create-with-same-image`;
  form.method = "post";
  form.hidden = true;
  const token = document.querySelector("input[name='csrf_token']")?.value || "";
  const csrf = document.createElement("input"); csrf.type = "hidden"; csrf.name = "csrf_token"; csrf.value = token;
  const input = document.createElement("input"); input.name = "name"; input.required = true; input.maxLength = 300; input.placeholder = "اسم المنتج الجديد";
  const submit = document.createElement("button"); submit.textContent = "إنشاء بنفس الصورة";
  form.append(csrf, input, submit);
  const listTitle = document.createElement("strong"); listTitle.textContent = "المنتجات التي تستخدم هذه الصورة";
  const list = document.createElement("ul"); list.dataset.sharedProductsList = "";
  appendSharedProduct(list, product);
  toggle.addEventListener("click", () => { form.hidden = false; input.focus(); });
  panel.append(title, created, toggle, form, finish, listTitle, list);
  card.append(panel);
}

async function submitSharedImageForm(form) {
  setBusy(form, true);
  try {
    const response = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" } });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.message || "تعذر إنشاء المنتج");
    appendSharedProduct(form.closest("[data-shared-image-panel]")?.querySelector("[data-shared-products-list]"), data.product);
    form.querySelector("[name='name']").value = "";
    form.querySelector("[name='name']").focus();
    const message = form.closest("[data-shared-image-panel]")?.querySelector("[data-shared-image-message]");
    if (message) message.textContent = data.message;
    showNotification(data.message, "success");
    setBusy(form, false);
  } catch (error) {
    showNotification(error.message || "تعذر إنشاء المنتج", "error");
    setBusy(form, false);
  }
}

async function submitBatchForm(form) {
  setBusy(form, true);
  try {
    const response = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" } });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.message || "تعذر تنفيذ الإجراء");
    showNotification(data.message, "success");
    if (form.classList.contains("save-product")) initializeSharedImagePanel(form.closest("[data-image-card]"), data.product, data.redirect_url);
    if (form.classList.contains("delete-image-form")) await loadBatchPartial(data.redirect_url || window.location.href, { push: false });
  } catch (error) {
    showNotification(error.message || "تعذر تنفيذ الإجراء", "error");
    setBusy(form, false);
  }
}

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { event.preventDefault(); return; }
  if (form.classList.contains("upload-form")) { setBusy(form, true); const loading = form.querySelector(".loading"); if (loading) loading.hidden = false; }
  if (form.classList.contains("save-product") || form.classList.contains("delete-image-form")) { event.preventDefault(); submitBatchForm(form); }
  if (form.classList.contains("shared-image-product-form")) { event.preventDefault(); submitSharedImageForm(form); }
});

document.addEventListener("click", (event) => {
  const batchLink = event.target.closest("[data-batch-content] .filter-button, [data-batch-pagination] a");
  if (batchLink) {
    event.preventDefault();
    loadBatchPartial(batchLink.href, { fallbackUrl: batchLink.href, scrollToGrid: Boolean(batchLink.closest("[data-batch-pagination]")) });
  }
  const finish = event.target.closest("[data-finish-shared-image]");
  if (finish) {
    const card = finish.closest("[data-image-card]");
    loadBatchPartial(card?.dataset.finishUrl || window.location.href, { push: false }).then(() => document.querySelector(".save-product input[name='name']")?.focus());
  }
});

window.addEventListener("popstate", () => { if (document.querySelector("[data-batch-content]")) loadBatchPartial(window.location.href, { push: false }); });
document.addEventListener("DOMContentLoaded", () => { ensureActiveNavigationVisible(); ensureActiveBatchFilterVisible(); });
