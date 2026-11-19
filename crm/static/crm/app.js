/* TBT CRM — سلوك الواجهة */
(function () {
  "use strict";

  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const pad = (n) => String(n).padStart(2, "0");
  const toLocalInput = (d) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  /* --- نسخ رقم الهاتف ---------------------------------------------------- */
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy") ? resolve() : reject();
      } catch (e) {
        reject(e);
      } finally {
        area.remove();
      }
    });
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    event.preventDefault();
    copyText(button.dataset.copy).then(() => {
      button.classList.add("copy-done");
      const icon = button.querySelector("i");
      const oldClass = icon ? icon.className : "";
      if (icon) icon.className = "bi bi-check2";
      setTimeout(() => {
        button.classList.remove("copy-done");
        if (icon) icon.className = oldClass;
      }, 1400);
    });
  });

  /* --- تأكيد قبل الإجراءات الحساسة ------------------------------------------ */
  document.addEventListener("submit", (event) => {
    const form = event.target;
    const message = form.dataset.confirm || event.submitter?.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  /* --- إرسال الفلاتر تلقائياً ---------------------------------------------- */
  document.querySelectorAll("[data-autosubmit]").forEach((el) => {
    el.addEventListener("change", () => el.form && el.form.submit());
  });

  /* --- اختيارات سريعة لموعد المتابعة -------------------------------------- */
  function quickDate(code) {
    const now = new Date();
    const at = (daysAhead, hour) => {
      const d = new Date(now);
      d.setDate(d.getDate() + daysAhead);
      d.setHours(hour, 0, 0, 0);
      return d;
    };
    switch (code) {
      case "1h": { const d = new Date(now.getTime() + 60 * 60000); d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5, 0, 0); return d; }
      case "2h": { const d = new Date(now.getTime() + 120 * 60000); d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5, 0, 0); return d; }
      case "today17": return at(0, 17);
      case "tomorrow10": return at(1, 10);
      case "tomorrow15": return at(1, 15);
      case "2d": return at(2, 10);
      case "week": return at(7, 10);
      case "month": return at(30, 10);
      case "3months": return at(90, 10);
      default: return null;
    }
  }

  document.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-quick]");
    if (!chip) return;
    event.preventDefault();
    const input = document.getElementById(chip.dataset.target);
    const value = quickDate(chip.dataset.quick);
    if (input && value) {
      input.value = toLocalInput(value);
      input.dispatchEvent(new Event("change", { bubbles: true }));
      chip.parentElement.querySelectorAll("[data-quick]").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
    }
  });

  /* --- إظهار الحقول حسب الاختيار ------------------------------------------ */
  function setupConditional(root) {
    const radios = root.querySelectorAll('input[name="outcome"]');
    if (!radios.length) return;
    const sections = root.querySelectorAll("[data-show-for]");
    const requiredMarks = root.querySelectorAll("[data-required-for]");
    const reasonSelect = root.querySelector("#id_rejection_reason");
    const detailWrap = root.querySelector("#detail-wrap");
    const contractWrap = root.querySelector("#contract-wrap");
    const detailLabel = root.querySelector("label[for='id_rejection_detail']");

    function current() {
      const checked = root.querySelector('input[name="outcome"]:checked');
      return checked ? checked.value : "";
    }

    function updateReason() {
      if (!reasonSelect) return;
      const option = reasonSelect.selectedOptions[0];
      const needsDetail = option && option.dataset.detail === "1";
      const asksContract = option && option.dataset.contract === "1";
      if (detailWrap) detailWrap.classList.toggle("show", !!(needsDetail || asksContract));
      if (contractWrap) contractWrap.classList.toggle("show", !!asksContract);
      if (detailLabel) detailLabel.textContent = asksContract ? "اسم البرنامج الذي يستخدمه" : "اكتب التفاصيل";
    }

    function update() {
      const value = current();
      sections.forEach((section) => {
        const list = section.dataset.showFor.split(" ");
        section.classList.toggle("show", list.includes(value));
      });
      requiredMarks.forEach((mark) => {
        mark.hidden = !mark.dataset.requiredFor.split(" ").includes(value);
      });
      const submit = root.querySelector("[data-submit-label]");
      if (submit) submit.disabled = !value;
      updateReason();
    }

    radios.forEach((radio) => radio.addEventListener("change", update));
    if (reasonSelect) reasonSelect.addEventListener("change", updateReason);
    update();

    // اختصارات لوحة المفاتيح: الأرقام 1-9 لاختيار النتيجة
    document.addEventListener("keydown", (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const tag = (event.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag) || event.target.isContentEditable) return;
      const index = parseInt(event.key, 10);
      if (index >= 1 && index <= radios.length) {
        radios[index - 1].checked = true;
        radios[index - 1].dispatchEvent(new Event("change", { bubbles: true }));
        radios[index - 1].focus();
      }
    });
  }
  document.querySelectorAll("[data-call-form]").forEach(setupConditional);

  /* --- نص المكالمة حسب التطبيق ---------------------------------------------- */
  function setupScriptSwitch() {
    const select = document.querySelector("[data-script-switch]");
    if (!select) return;
    const update = () => {
      document.querySelectorAll("[data-script-for]").forEach((panel) => {
        panel.hidden = panel.dataset.scriptFor !== (select.value || "none");
      });
    };
    select.addEventListener("change", update);
    update();
  }
  setupScriptSwitch();

  /* --- الباقة والسعر -------------------------------------------------------- */
  function setupPricing(root) {
    const product = root.querySelector("[data-price-product]");
    const plan = root.querySelector("[data-price-plan]");
    const price = root.querySelector("[data-price-input]");
    if (!product || !plan || !price) return;
    const filterPlans = () => {
      const pid = product.value;
      plan.querySelectorAll("option[data-product]").forEach((opt) => {
        opt.hidden = pid && opt.dataset.product !== pid;
      });
      const selected = plan.selectedOptions[0];
      if (selected && selected.hidden) plan.value = "";
    };
    product.addEventListener("change", () => {
      filterPlans();
      const opt = product.selectedOptions[0];
      if (opt && opt.dataset.price && !plan.value) price.value = opt.dataset.price;
    });
    plan.addEventListener("change", () => {
      const opt = plan.selectedOptions[0];
      if (opt && opt.dataset.price) price.value = opt.dataset.price;
    });
    filterPlans();
    if (!price.value) {
      const opt = product.selectedOptions[0];
      if (opt && opt.dataset.price) price.value = opt.dataset.price;
    }
  }
  document.querySelectorAll("[data-pricing]").forEach(setupPricing);

  /* --- تحديد عدة عملاء ------------------------------------------------------- */
  function setupBulk() {
    const master = document.querySelector("[data-select-all]");
    const boxes = Array.from(document.querySelectorAll("[data-select-row]"));
    const bar = document.querySelector("[data-bulk-bar]");
    if (!bar || !boxes.length) return;
    const counter = bar.querySelector("[data-bulk-count]");
    const update = () => {
      const count = boxes.filter((b) => b.checked).length;
      bar.classList.toggle("show", count > 0);
      if (counter) counter.textContent = count;
      if (master) master.checked = count === boxes.length;
    };
    boxes.forEach((b) => b.addEventListener("change", update));
    if (master) master.addEventListener("change", () => { boxes.forEach((b) => (b.checked = master.checked)); update(); });
    const action = bar.querySelector("[name='action']");
    const toggleFields = () => {
      bar.querySelectorAll("[data-for-action]").forEach((el) => {
        el.hidden = el.dataset.forAction !== action.value;
      });
    };
    if (action) { action.addEventListener("change", toggleFields); toggleFields(); }
  }
  setupBulk();

  /* --- لوحة المراحل: السحب والإفلات --------------------------------------- */
  function setupKanban() {
    const board = document.querySelector("[data-kanban]");
    if (!board) return;
    const dialog = document.getElementById("lost-dialog");
    let dragged = null;
    let source = null;

    const adjust = (column, delta) => {
      column.dataset.total = String(parseInt(column.dataset.total || "0", 10) + delta);
      const count = column.querySelector("[data-count]");
      if (count) count.textContent = column.dataset.total;
    };

    const toast = (html, ok = true) => {
      const box = document.getElementById("kanban-toast");
      if (!box) return;
      box.className = `alert ${ok ? "alert-success" : "alert-danger"} py-2 mb-3`;
      box.replaceChildren();
      if (typeof html === "string") box.textContent = html; else box.appendChild(html);
      box.hidden = false;
      clearTimeout(box._timer);
      box._timer = setTimeout(() => { box.hidden = true; }, 6000);
    };

    async function moveCard(card, column, reasonId) {
      const body = { stage: column.dataset.stage };
      if (reasonId) body.lost_reason = reasonId;
      const response = await fetch(card.dataset.stageUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify(body),
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("failed");
      return response.json();
    }

    function askReason() {
      return new Promise((resolve) => {
        if (!dialog || typeof dialog.showModal !== "function") return resolve("");
        const select = dialog.querySelector("select");
        select.value = "";
        dialog.returnValue = "";
        dialog.showModal();
        dialog.addEventListener("close", function onClose() {
          dialog.removeEventListener("close", onClose);
          resolve(dialog.returnValue === "ok" ? (select.value || "") : null);
        });
      });
    }

    board.addEventListener("dragstart", (event) => {
      const card = event.target.closest(".kanban-card");
      if (!card) return;
      dragged = card;
      source = card.closest(".kanban-col");
      card.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.id);
    });
    board.addEventListener("dragend", () => {
      if (dragged) dragged.classList.remove("dragging");
      board.querySelectorAll(".drag-over").forEach((c) => c.classList.remove("drag-over"));
    });
    board.addEventListener("dragover", (event) => {
      const column = event.target.closest(".kanban-col");
      if (!column || !dragged) return;
      event.preventDefault();
      board.querySelectorAll(".drag-over").forEach((c) => c !== column && c.classList.remove("drag-over"));
      column.classList.add("drag-over");
    });
    board.addEventListener("drop", async (event) => {
      const column = event.target.closest(".kanban-col");
      if (!column || !dragged) return;
      event.preventDefault();
      column.classList.remove("drag-over");
      if (column === source) return;
      const card = dragged;
      const from = source;
      let reason = "";
      if (column.dataset.stage === "lost") {
        reason = await askReason();
        if (reason === null) return;
      }
      column.querySelector(".kanban-col-body").prepend(card);
      adjust(from, -1);
      adjust(column, 1);
      try {
        const data = await moveCard(card, column, reason);
        if (data.subscription_url) {
          const wrap = document.createElement("span");
          wrap.append(`${card.dataset.name}: أصبح «${data.label}». `);
          const link = document.createElement("a");
          link.href = data.subscription_url;
          link.className = "alert-link";
          link.textContent = "أضف الاشتراك الآن ←";
          wrap.append(link);
          toast(wrap);
        } else {
          toast(`${card.dataset.name}: أصبح «${data.label}»`);
        }
      } catch (e) {
        from.querySelector(".kanban-col-body").prepend(card);
        adjust(column, -1);
        adjust(from, 1);
        toast("لم يتم الحفظ. حاول مرة أخرى.", false);
      }
    });
  }
  setupKanban();

  /* --- تلميحات الرسوم البيانية ---------------------------------------------- */
  function setupChartTips() {
    const targets = document.querySelectorAll("[data-tip-value]");
    if (!targets.length) return;
    const tip = document.createElement("div");
    tip.className = "chart-tip";
    tip.setAttribute("role", "tooltip");
    const strong = document.createElement("strong");
    const label = document.createElement("span");
    tip.append(strong, label);
    document.body.appendChild(tip);
    const show = (el, x, y) => {
      strong.textContent = el.dataset.tipValue;
      label.textContent = el.dataset.tipLabel || "";
      tip.style.display = "block";
      const rect = tip.getBoundingClientRect();
      let left = x - rect.width / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - rect.width - 8));
      tip.style.left = `${left}px`;
      tip.style.top = `${Math.max(8, y - rect.height - 12)}px`;
    };
    const hide = () => { tip.style.display = "none"; };
    targets.forEach((el) => {
      el.addEventListener("pointermove", (e) => show(el, e.clientX, e.clientY));
      el.addEventListener("pointerleave", hide);
      el.addEventListener("focus", () => {
        const r = el.getBoundingClientRect();
        show(el, r.left + r.width / 2, r.top);
      });
      el.addEventListener("blur", hide);
    });
  }
  setupChartTips();

  /* --- إدراج متغيرات القوالب بالنقر ------------------------------------------- */
  document.addEventListener("click", (event) => {
    const code = event.target.closest("[data-insert]");
    if (!code) return;
    const area = document.getElementById(code.dataset.target);
    if (!area) return;
    const start = area.selectionStart ?? area.value.length;
    const end = area.selectionEnd ?? area.value.length;
    area.value = area.value.slice(0, start) + code.dataset.insert + area.value.slice(end);
    area.focus();
    area.selectionStart = area.selectionEnd = start + code.dataset.insert.length;
  });
})();
