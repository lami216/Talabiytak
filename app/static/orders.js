(() => {
  const editor = document.querySelector("[data-order-editor]");
  if (!editor) return;

  const selected = editor.querySelector("[data-selected-products]");
  const empty = editor.querySelector("[data-empty-selection]");
  const notification = document.querySelector("[data-order-notification]");
  let notificationTimer;

  const notify = (message, type = "error") => {
    notification.textContent = message;
    notification.dataset.type = type;
    notification.hidden = false;
    clearTimeout(notificationTimer);
    notificationTimer = setTimeout(() => {
      notification.hidden = true;
    }, 3000);
  };

  const refresh = () => {
    empty.hidden = selected.children.length > 0;
  };

  const wire = (card) => {
    card.querySelector("[data-remove]").addEventListener("click", () => {
      card.remove();
      refresh();
    });
    card.querySelector("[data-move-up]").addEventListener("click", () => {
      const next = card.nextElementSibling;
      if (next) selected.insertBefore(next, card);
    });
    card.querySelector("[data-move-down]").addEventListener("click", () => {
      const previous = card.previousElementSibling;
      if (previous) selected.insertBefore(card, previous);
    });
  };

  const validQuantity = (rawQuantity) => {
    const quantityValue = Number(rawQuantity);
    return /^\d+$/.test(rawQuantity) && Number.isSafeInteger(quantityValue) &&
      quantityValue >= 1 && quantityValue <= 1000000;
  };

  selected.querySelectorAll("[data-product-id]").forEach(wire);
  refresh();

  editor.querySelector("[data-product-search]").addEventListener("click", async () => {
    const q = editor.querySelector("[data-product-query]").value;
    const box = editor.querySelector("[data-search-results]");
    box.textContent = "جارٍ البحث...";
    const response = await fetch(`/orders/product-search?q=${encodeURIComponent(q)}`);
    if (!response.ok) {
      box.textContent = "تعذر البحث.";
      return;
    }
    const data = await response.json();
    box.textContent = "";
    data.items.forEach((product) => {
      const card = document.createElement("article");
      card.className = "card product-search-card";
      const image = document.createElement("img");
      image.className = "product-search-image";
      image.src = product.image_url;
      image.alt = "";
      const name = document.createElement("strong");
      name.className = "product-search-name";
      name.textContent = product.name;

      const addControls = document.createElement("div");
      addControls.className = "product-add-controls";
      const quantityInput = document.createElement("input");
      quantityInput.className = "product-quantity-input";
      quantityInput.type = "number";
      quantityInput.min = "1";
      quantityInput.max = "1000000";
      quantityInput.step = "1";
      quantityInput.inputMode = "numeric";
      quantityInput.placeholder = "الكمية";
      quantityInput.dataset.addQuantity = "";
      quantityInput.setAttribute("aria-label", `كمية المنتج ${product.name}`);

      const error = document.createElement("p");
      const errorId = `quantity-error-${product.id}`;
      error.className = "field-error";
      error.id = errorId;
      error.dataset.quantityError = "";
      error.hidden = true;
      quantityInput.setAttribute("aria-describedby", errorId);

      const clearError = () => {
        quantityInput.classList.remove("is-invalid");
        quantityInput.removeAttribute("aria-invalid");
        error.hidden = true;
        error.textContent = "";
      };
      const showError = (message) => {
        quantityInput.classList.add("is-invalid");
        quantityInput.setAttribute("aria-invalid", "true");
        error.textContent = message;
        error.hidden = false;
        quantityInput.focus();
        notify(message);
      };

      const add = document.createElement("button");
      add.className = "product-add-button";
      add.type = "button";
      add.dataset.addProduct = "";
      add.textContent = "إضافة";
      const addProduct = () => {
        const rawQuantity = quantityInput.value.trim();
        if (!rawQuantity) {
          showError("رجاءً ضع الكمية المطلوبة.");
          return;
        }
        if (!validQuantity(rawQuantity)) {
          showError("أدخل كمية صحيحة أكبر من صفر.");
          return;
        }
        clearError();
        const existing = selected.querySelector(`[data-product-id="${product.id}"]`);
        if (existing) {
          notify("هذا المنتج مضاف بالفعل.", "info");
          existing.scrollIntoView({ behavior: "smooth", block: "center" });
          existing.querySelector('[name="quantity"]').focus();
          return;
        }

        const quantityValue = Number(rawQuantity);
        const item = document.createElement("article");
        item.className = "selected-product card";
        item.dataset.productId = product.id;
        const id = document.createElement("input");
        id.type = "hidden";
        id.name = "product_id";
        id.value = product.id;
        const title = document.createElement("strong");
        title.textContent = product.name;
        const quantity = document.createElement("input");
        quantity.type = "number";
        quantity.name = "quantity";
        quantity.min = "1";
        quantity.max = "1000000";
        quantity.required = true;
        quantity.value = String(quantityValue);
        const controls = document.createElement("div");
        controls.className = "actions";
        [["↑", "moveUp"], ["↓", "moveDown"], ["إزالة", "remove"]].forEach(
          ([text, key]) => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = text;
            button.dataset[key] = "";
            controls.append(button);
          },
        );
        item.append(id, title, quantity, controls);
        selected.append(item);
        wire(item);
        refresh();
        quantityInput.value = "";
        notify("تمت إضافة المنتج.", "success");
      };

      quantityInput.addEventListener("input", () => {
        if (validQuantity(quantityInput.value.trim())) clearError();
      });
      quantityInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          addProduct();
        }
      });
      add.addEventListener("click", addProduct);
      addControls.append(quantityInput, add);
      card.append(image, name, addControls, error);
      box.append(card);
    });
    if (!data.items.length) box.textContent = "لا توجد نتائج.";
  });

  editor.addEventListener("submit", (event) => {
    if (!selected.children.length) {
      event.preventDefault();
      empty.hidden = false;
    }
  });
})();
