(() => {
  const editor = document.querySelector("[data-order-editor]"); if (!editor) return;
  const selected = editor.querySelector("[data-selected-products]");
  const empty = editor.querySelector("[data-empty-selection]");
  const refresh = () => { empty.hidden = selected.children.length > 0; };
  const wire = (card) => {
    card.querySelector("[data-remove]").addEventListener("click", () => { card.remove(); refresh(); });
    card.querySelector("[data-move-up]").addEventListener("click", () => { if (card.previousElementSibling) selected.insertBefore(card, card.previousElementSibling); });
    card.querySelector("[data-move-down]").addEventListener("click", () => { if (card.nextElementSibling) selected.insertBefore(card.nextElementSibling, card); });
  };
  selected.querySelectorAll("[data-product-id]").forEach(wire); refresh();
  editor.querySelector("[data-product-search]").addEventListener("click", async () => {
    const q = editor.querySelector("[data-product-query]").value;
    const box = editor.querySelector("[data-search-results]"); box.textContent = "جارٍ البحث...";
    const response = await fetch(`/orders/product-search?q=${encodeURIComponent(q)}`);
    if (!response.ok) { box.textContent = "تعذر البحث."; return; }
    const data = await response.json(); box.textContent = "";
    data.items.forEach((product) => {
      const card = document.createElement("article"); card.className = "card";
      const image = document.createElement("img"); image.src = product.image_url; image.alt = "";
      const name = document.createElement("strong"); name.textContent = product.name;
      const add = document.createElement("button"); add.type = "button"; add.textContent = "إضافة";
      add.addEventListener("click", () => {
        if (selected.querySelector(`[data-product-id="${product.id}"]`)) return;
        const item = document.createElement("article"); item.className = "selected-product card"; item.dataset.productId = product.id;
        const id = document.createElement("input"); id.type = "hidden"; id.name = "product_id"; id.value = product.id;
        const title = document.createElement("strong"); title.textContent = product.name;
        const quantity = document.createElement("input"); quantity.type = "number"; quantity.name = "quantity"; quantity.min = "1"; quantity.max = "1000000"; quantity.required = true; quantity.value = "1";
        const controls = document.createElement("div"); controls.className = "actions";
        [["↑", "moveUp"], ["↓", "moveDown"], ["إزالة", "remove"]].forEach(([text, key]) => { const b=document.createElement("button"); b.type="button"; b.textContent=text; b.dataset[key]=""; controls.append(b); });
        item.append(id, title, quantity, controls); selected.append(item); wire(item); refresh();
      }); card.append(image, name, add); box.append(card);
    }); if (!data.items.length) box.textContent = "لا توجد نتائج.";
  });
  editor.addEventListener("submit", (event) => { if (!selected.children.length) { event.preventDefault(); empty.hidden=false; } });
})();
