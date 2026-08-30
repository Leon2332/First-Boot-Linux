const STEP_KEYS = ["Shop", "Look", "Recommendations", "Write"];
const HTML_LANG = { "en-us": "en-US", "en-gb": "en-GB", "en-za": "en-ZA", "af": "af" };
const STAGE_MSG = {
  "Starting…": "Starting…",
  "Waiting for permission…": "Waiting for permission…",
  "Stopped.": "Stopped.",
  "Cancelled.": "Cancelled.",
  "Writing to disk": "Writing to disk",
  "done": "Done.",
  "assemble disk": "Building disk image",
  "format FBL-SYS": "Formatting the system partition…",
  "format FBL-DATA": "Formatting the data partition…",
  "format FBL-ESP": "Formatting the boot partition…",
};

let state = null;
let step = 0;
let busy = false;
let barFrac = 0;
let catalog = {};
let uiLang = "en-us";
let lastError = "";
let lastStage = "Ready.";
let lastTasks = [];

const $ = (id) => document.getElementById(id);

function t(msg, vars) {
  let out = (catalog && catalog[msg]) || msg;
  if (vars) {
    Object.keys(vars).forEach((k) => {
      out = out.split("{" + k + "}").join(String(vars[k]));
    });
  }
  return out;
}

function applyI18n() {
  document.documentElement.lang = HTML_LANG[uiLang] || uiLang;
  document.title = t("First Boot — USB creator");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
    const src = el.getAttribute("data-i18n-aria");
    el.setAttribute("aria-label", t(src));
    if (el.hasAttribute("title")) el.setAttribute("title", t(src));
  });
  document.querySelectorAll("[data-i18n-alt]").forEach((el) => {
    el.setAttribute("alt", t(el.getAttribute("data-i18n-alt")));
  });
  const pop = $("ui-lang-pop");
  if (pop) pop.setAttribute("aria-label", t("Language"));
  showError(lastError);
  if ($("status")) $("status").textContent = tStage(lastStage);
  renderLangPopover();
  renderTasks(lastTasks);
}

function tStage(stage) {
  if (!stage) return t("Working…");
  if (STAGE_MSG[stage]) return t(STAGE_MSG[stage]);
  if (catalog[stage]) return catalog[stage];
  const saved = "Done. Disk image saved to ";
  if (stage.startsWith(saved)) {
    return t("Done. Disk image saved to {path}", { path: stage.slice(saved.length) });
  }
  if (stage.startsWith("download ")) {
    return t("Downloading {name}", { name: stage.slice("download ".length) });
  }
  return t(stage);
}

function tLabel(label) {
  if (!label) return "";
  if (catalog[label]) return catalog[label];
  const prefix = "Downloading ";
  if (label.startsWith(prefix) && label.length > prefix.length) {
    return t("Downloading {name}", { name: label.slice(prefix.length) });
  }
  return t(label);
}

async function api(path, opts) {
  const res = await fetch(path, { ...opts, cache: "no-store" });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showError(msg) {
  lastError = msg || "";
  $("error").textContent = lastError ? t(lastError) : "";
}

function renderSteps() {
  const nav = $("steps");
  nav.innerHTML = "";
  STEP_KEYS.forEach((key, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `<span class="n">${i + 1}</span>${escapeHtml(t(key))}`;
    if (i === step) b.classList.add("current");
    else if (i < step) b.classList.add("done");
    b.disabled = i > step || busy;
    b.onclick = () => { if (i < step && !busy) { step = i; render(); } };
    nav.appendChild(b);
  });
}

const PICKED_SLOTS = 5;
const ticked = [];

function tokens(query) {
  return String(query || "").toLowerCase().trim().split(/\s+/).filter(Boolean);
}

function nameMatches(name, query) {
  const toks = tokens(query);
  if (!toks.length) return true;
  const field = String(name || "").toLowerCase();
  return toks.every((tok) => field.includes(tok));
}

function stagedKey(distroId, editionId) {
  return `${distroId}:${editionId}`;
}

function lookupStaged(key) {
  const cut = String(key || "").indexOf(":");
  if (cut < 1) return null;
  const did = key.slice(0, cut);
  const eid = key.slice(cut + 1);
  const distro = (state?.distros || []).find((d) => d.id === did);
  if (!distro) return null;
  const edition = (distro.editions || []).find((ed) => ed.id === eid);
  if (!edition) return null;
  return { distro, edition };
}

function setTicked(key, on) {
  const i = ticked.indexOf(key);
  if (on) {
    if (i >= 0) return true;
    if (ticked.length >= PICKED_SLOTS) return false;
    ticked.push(key);
    return true;
  }
  if (i >= 0) ticked.splice(i, 1);
  return true;
}

function card(d) {
  const el = document.createElement("article");
  el.className = "card";
  el.dataset.id = d.id;
  const src = d.logo ? `/api/logo/${encodeURIComponent(d.id)}?t=${Date.now()}` : "";
  const full = ticked.length >= PICKED_SLOTS;
  const editions = (d.editions || []).map((ed) => {
    const key = stagedKey(d.id, ed.id);
    const ready = !!ed.stageable;
    const checked = ticked.includes(key);
    const locked = !ready || (full && !checked);
    let meta = ready
      ? t("{size} · on the USB", { size: ed.size })
      : t("Install support is not ready");
    if (d.custom && ed.need_iso) meta = t("This desktop needs an ISO");
    const isoBtn = d.custom
      ? `<button type="button" class="iso-btn" data-iso-key="${escapeHtml(key)}">${escapeHtml(ready ? t("Replace ISO…") : t("Choose ISO…"))}</button>`
      : "";
    return `<div class="edition">
      <label class="ed-check">
        <input type="checkbox" data-key="${escapeHtml(key)}" data-ready="${ready ? "1" : "0"}" ${checked ? "checked" : ""} ${locked ? "disabled" : ""}>
        <span class="ed-name">${escapeHtml(ed.name)}</span>
        <span class="ed-meta">${escapeHtml(meta)}</span>
      </label>
      ${isoBtn}
    </div>`;
  }).join("");
  const packId = /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(d.id || "") ? d.id : "";
  const remove = d.custom && packId
    ? `<button type="button" class="pack-remove" data-pack-id="${packId}">${escapeHtml(t("Remove"))}</button>`
    : "";
  const pills = [];
  if (d.custom) {
    pills.push(`<span class="pill pack-pill">${escapeHtml(t("Retailer pack"))}</span>`);
  }
  if (d.secure_boot) {
    pills.push(`<span class="pill sb-pill">${escapeHtml(t("Secure Boot"))}</span>`);
  }
  el.innerHTML = `
    ${src ? `<img class="logo" src="${src}" alt="">` : "<span></span>"}
    <div>
      <div class="card-head">
        <h3>${escapeHtml(d.name)}</h3>
        ${remove}
      </div>
      <p class="meta">${escapeHtml(d.version)} · ${escapeHtml(t(d.tagline))}</p>
      ${pills.length ? `<div class="pills">${pills.join("")}</div>` : ""}
      <p>${escapeHtml(t(d.description))}</p>
      <div class="editions">${editions}</div>
    </div>`;
  el.querySelectorAll("input[type=checkbox]").forEach((box) => {
    box.addEventListener("change", () => {
      if (!setTicked(box.dataset.key, box.checked)) box.checked = false;
      renderPicked();
      syncEditionLocks();
    });
  });
  return el;
}

function addCard() {
  const el = document.createElement("article");
  el.className = "card add";
  el.innerHTML = `
    <span></span>
    <div>
      <h3>${escapeHtml(t("Add your own"))}</h3>
      <p>${escapeHtml(t("Choose a retailer pack (.zip) with a manifest, driver, and logo. Then choose an ISO for each desktop."))}</p>
      <div class="add-actions">
        <button type="button" class="iso-btn" id="choose-pack">${escapeHtml(t("Choose pack…"))}</button>
      </div>
    </div>`;
  el.querySelector("#choose-pack").addEventListener("click", choosePack);
  return el;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function selected() {
  return ticked.slice();
}

function renderPicked() {
  const grid = $("picked");
  if (!grid) return;
  grid.innerHTML = "";
  for (let i = 0; i < PICKED_SLOTS; i++) {
    const slot = document.createElement("div");
    slot.className = "picked-slot";
    const item = lookupStaged(ticked[i]);
    if (!item) {
      grid.appendChild(slot);
      continue;
    }
    slot.classList.add("filled");
    if (item.distro.logo) {
      const img = document.createElement("img");
      img.src = `/api/logo/${encodeURIComponent(item.distro.id)}`;
      img.alt = "";
      slot.appendChild(img);
    }
    const de = document.createElement("span");
    de.className = "de";
    de.textContent = item.edition.name;
    slot.appendChild(de);
    grid.appendChild(slot);
  }
}

function syncEditionLocks() {
  const full = ticked.length >= PICKED_SLOTS;
  document.querySelectorAll("#ready input[type=checkbox]").forEach((box) => {
    const ready = box.dataset.ready === "1";
    box.disabled = !ready || (full && !box.checked);
  });
}

function renderDistros() {
  const ready = $("ready");
  const empty = $("distro-empty");
  const query = $("distro-search")?.value || "";
  ready.innerHTML = "";
  const distros = (state?.distros || [])
    .filter((d) => nameMatches(d.name, query))
    .slice()
    .sort((a, b) => {
      const byName = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
      if (byName) return byName;
      return a.id.localeCompare(b.id);
    });
  distros.forEach((d) => ready.appendChild(card(d)));
  ready.appendChild(addCard());
  empty.hidden = distros.length > 0;
  renderPicked();
}

async function reloadDistros() {
  const data = await api("/api/state");
  if (state) {
    state.distros = data.distros || [];
    state.seed_ok = data.seed_ok;
    state.seed_error = data.seed_error;
  } else {
    state = data;
  }
  if (data.catalog) catalog = data.catalog;
  applyI18n();
  renderDistros();
}

async function choosePack() {
  const msg = t("This pack is not from First Boot Linux. A broken driver can wipe the disk. Continue?");
  if (!confirm(msg)) return;
  let path = "";
  try {
    const picked = await api("/api/pick-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "zip", title: t("Choose pack…") }),
    });
    path = picked.path || "";
  } catch (e) {
    const err = String(e.message || e);
    if (err === "cancelled") return;
    $("pack-file").value = "";
    $("pack-file").click();
    return;
  }
  if (!path) return;
  try {
    await api("/api/custom-pack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    await reloadDistros();
  } catch (e) {
    showError(e.message);
  }
}

async function uploadPackFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    await api("/api/custom-pack-upload", { method: "POST", body: fd });
    await reloadDistros();
  } catch (e) {
    showError(e.message);
  }
}

async function attachISO(key) {
  const item = lookupStaged(key);
  if (!item) return;
  let path = "";
  try {
    const picked = await api("/api/pick-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: "iso",
        title: t("Choose an ISO for {name}", { name: item.edition.name }),
      }),
    });
    path = picked.path || "";
  } catch (e) {
    if (String(e.message || e) === "cancelled") return;
    path = window.prompt(t("Choose an ISO for {name}", { name: item.edition.name }), "") || "";
  }
  if (!path) return;
  try {
    await api("/api/custom-iso", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: item.distro.id, edition: item.edition.id, path }),
    });
    await reloadDistros();
  } catch (e) {
    showError(e.message);
  }
}

async function removePack(id) {
  if (id && typeof id === "object" && id instanceof Event) {
    const btn = id.target && id.target.closest && id.target.closest(".pack-remove");
    const card = btn && btn.closest("article.card");
    id = (btn && btn.getAttribute("data-pack-id")) || (card && card.dataset.id) || "";
  }
  id = String(id || "").trim();
  if (!id) {
    showError("Could not remove that pack.");
    return;
  }
  const prev = (state?.distros || []).slice();
  for (let i = ticked.length - 1; i >= 0; i--) {
    if (ticked[i] === id || ticked[i].startsWith(id + ":")) ticked.splice(i, 1);
  }
  if (state) {
    state.distros = prev.filter((d) => d.id !== id);
  }
  renderDistros();
  try {
    await api("/api/custom-remove?id=" + encodeURIComponent(id), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
  } catch (e) {
    if (state) state.distros = prev;
    renderDistros();
    showError(e.message);
  }
}

function validate() {
  if (step === 0) {
    if (!$("name").value.trim()) return "Enter the shop name.";
    if (!$("support").value.trim()) return "Enter a support contact.";
    if (!$("empty-pw").checked) {
      if (!$("pass").value) return "Set a support password, or tick the VM option.";
      if ($("pass").value !== $("pass2").value) return "Passwords do not match.";
      if ($("pass").value.length < 6) return "Use at least 6 characters.";
    }
  }
  if (step === 2 && selected().length === 0) return "Tick at least one desktop to keep on the USB.";
  if (step === 3) {
    if (!state.seed_ok) return state.seed_error || "No First Boot seed on this computer.";
    const target = document.querySelector("input[name=target]:checked").value;
    if (target === "usb" && !$("device").value) return "Choose a USB stick.";
    if (target === "image" && !$("img-path").value.trim()) return "Choose where to save the disk image.";
  }
  return "";
}

async function refreshEstimate() {
  try {
    const est = await api("/api/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ staged: selected() }),
    });
    $("size").textContent = t(
      "This set needs {size} on the stick. Use a {stick} GB USB. The PC you install onto should have at least {disk} GB so the chosen OS can unpack.",
      {
        size: est.need || "",
        stick: String(est.stick_gb ?? ""),
        disk: String(est.disk_gb ?? ""),
      }
    );
    const names = (est.names || []).join(", ");
    $("hint").textContent = names ? t("On this stick: {names}.", { names }) : "";
  } catch (e) {
    $("size").textContent = t(e.message);
    $("hint").textContent = "";
  }
}

async function refreshDisks() {
  const data = await api("/api/devices");
  const sel = $("device");
  const prev = sel.value;
  sel.innerHTML = "";
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = t("Choose a USB stick");
  sel.appendChild(opt0);
  (data.disks || []).forEach((d) => {
    const o = document.createElement("option");
    o.value = d.path;
    o.textContent = `${d.path}  ${d.label}`;
    if (d.system) o.disabled = true;
    sel.appendChild(o);
  });
  if (prev) sel.value = prev;
  updateDiskWarn();
}

function updateDiskWarn() {
  const usb = document.querySelector("input[name=target]:checked")?.value === "usb";
  const hasDisk = !!$("device").value;
  $("disk-warn").hidden = !(usb && hasDisk);
}

function renderTasks(tasks) {
  lastTasks = tasks || [];
  const list = $("task-list");
  if (!tasks || !tasks.length) {
    list.hidden = true;
    list.innerHTML = "";
    return;
  }
  list.hidden = false;
  list.innerHTML = tasks.map((tk) => {
    const st = tk.status === "done" || tk.status === "active" || tk.status === "error" ? tk.status : "pending";
    return `<li class="${st}"><span class="task-mark" aria-hidden="true"></span><span>${escapeHtml(tLabel(tk.label))}</span></li>`;
  }).join("");
}

function render() {
  renderSteps();
  document.querySelectorAll(".page").forEach((p, i) => {
    p.classList.toggle("hidden", i !== step);
  });
  $("back").disabled = step === 0 || busy;
  const next = $("next");
  if (busy) {
    next.textContent = t("Cancel");
    next.classList.remove("primary");
    next.classList.add("danger");
    next.disabled = false;
  } else {
    next.textContent = step === 3 ? t("Write") : t("Continue");
    next.classList.add("primary");
    next.classList.remove("danger");
    next.disabled = false;
  }
  if (step === 3 && !busy) refreshEstimate();
}

function setBar(frac) {
  frac = Math.max(0, Math.min(1, Number(frac) || 0));
  const el = $("bar");
  if (frac + 0.002 < barFrac) {
    el.style.transition = "none";
  } else {
    el.style.transition = "transform 160ms linear";
  }
  el.style.transform = `scaleX(${frac})`;
  barFrac = frac;
}

async function uploadWallpaper(which, file) {
  const fd = new FormData();
  fd.append("which", which);
  fd.append("file", file);
  await api("/api/wallpaper", { method: "POST", body: fd });
  $(`${which}-preview`).src = `/api/wallpaper/${which}?t=${Date.now()}`;
}

async function startWrite() {
  const target = document.querySelector("input[name=target]:checked").value;
  const body = {
    name: $("name").value.trim(),
    support: $("support").value.trim(),
    language: $("language").value || "en-us",
    keyboard: $("keyboard").value || "us",
    timezone: $("timezone").value || "UTC+0000",
    password: $("empty-pw").checked ? "" : $("pass").value,
    empty_password: $("empty-pw").checked,
    staged: selected(),
    target,
    image: $("img-path").value.trim(),
    device: $("device").value,
  };
  if (target === "usb") {
    const disk = (await api("/api/devices")).disks.find((d) => d.path === body.device);
    const label = disk ? disk.label : body.device;
    const msg = t("Your disk will be formatted. All data will be permanently erased.")
      + "\n\n"
      + t("Erase {device} ({label}) and write First Boot?", { device: body.device, label });
    if (!confirm(msg)) {
      return;
    }
  }
  busy = true;
  showError("");
  setBar(0);
  render();
  try {
    await api("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const first = await api("/api/progress");
    lastStage = first.stage || "Starting…";
    renderTasks(first.tasks);
    $("status").textContent = tStage(lastStage);
    poll();
  } catch (e) {
    busy = false;
    showError(e.message);
    render();
  }
}

async function poll() {
  try {
    const p = await api("/api/progress");
    renderTasks(p.tasks);
    setBar(p.fraction || 0);
    lastStage = p.stage || "Working…";
    $("status").textContent = tStage(lastStage);
    if (p.done) {
      busy = false;
      if (p.error) showError(p.error);
      else {
        lastStage = p.stage || "Done.";
        $("status").textContent = tStage(lastStage);
      }
      render();
      return;
    }
  } catch (e) {
    busy = false;
    showError(e.message);
    render();
    return;
  }
  setTimeout(poll, 250);
}

function closeLangPop() {
  const pop = $("ui-lang-pop");
  const btn = $("ui-lang-btn");
  if (!pop || pop.hidden) return;
  pop.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function toggleLangPop() {
  const pop = $("ui-lang-pop");
  const btn = $("ui-lang-btn");
  if (!pop) return;
  const open = pop.hidden;
  pop.hidden = !open;
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) renderLangPopover();
}

function renderLangPopover() {
  const list = $("ui-lang-list");
  if (!list) return;
  list.innerHTML = "";
  const langs = state?.languages && state.languages.length
    ? state.languages
    : [{ id: "en-us", name: "English (US)" }, { id: "af", name: "Afrikaans" }];
  langs.forEach((lang) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "lang-item";
    b.setAttribute("role", "option");
    b.setAttribute("aria-selected", lang.id === uiLang ? "true" : "false");
    b.dataset.id = lang.id;
    const name = document.createElement("span");
    name.textContent = lang.name;
    b.appendChild(name);
    if (lang.id === uiLang) {
      const check = document.createElement("span");
      check.className = "lang-check";
      check.setAttribute("aria-hidden", "true");
      b.appendChild(check);
    }
    b.onclick = () => { setUILanguage(lang.id); };
    list.appendChild(b);
  });
}

async function setUILanguage(id) {
  if (!id) return;
  try {
    const data = await api("/api/ui-language", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: id }),
    });
    uiLang = data.language || id;
    catalog = data.catalog || {};
    applyI18n();
    render();
    renderDistros();
    if (step === 3) {
      refreshEstimate().catch(() => {});
      refreshDisks().catch(() => {});
    }
    closeLangPop();
  } catch (e) {
    showError(e.message);
  }
}

async function init() {
  state = await api("/api/state");
  uiLang = state.ui_language || "en-us";
  catalog = state.catalog || {};
  const langSel = $("language");
  langSel.innerHTML = "";
  const langs = state.languages && state.languages.length
    ? state.languages
    : [{ id: "en-us", name: "English (US)" }, { id: "en-gb", name: "English (UK)" }, { id: "en-za", name: "English (South Africa)" }, { id: "af", name: "Afrikaans" }];
  langs.forEach((lang) => {
    const o = document.createElement("option");
    o.value = lang.id;
    o.textContent = lang.name;
    if (lang.id === "en-us") o.selected = true;
    langSel.appendChild(o);
  });
  const kbdSel = $("keyboard");
  kbdSel.innerHTML = "";
  const boards = state.keyboards && state.keyboards.length
    ? state.keyboards
    : [{ id: "us", name: "English (US)" }, { id: "gb", name: "English (UK)" }];
  boards.forEach((kb) => {
    const o = document.createElement("option");
    o.value = kb.id;
    o.textContent = kb.name;
    if (kb.id === "us") o.selected = true;
    kbdSel.appendChild(o);
  });
  const tzSel = $("timezone");
  tzSel.innerHTML = "";
  for (let m = -12 * 60; m <= 14 * 60; m += 30) {
    const sign = m < 0 ? "-" : "+";
    const abs = Math.abs(m);
    const label = `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}${String(abs % 60).padStart(2, "0")}`;
    const o = document.createElement("option");
    o.value = label;
    o.textContent = label;
    if (label === "UTC+0000") o.selected = true;
    tzSel.appendChild(o);
  }
  $("img-path").value = state.default_image;
  $("dark-preview").src = "/api/wallpaper/dark";
  $("light-preview").src = "/api/wallpaper/light";
  applyI18n();
  lastStage = "Ready.";
  $("status").textContent = t("Ready.");
  renderDistros();
  $("distro-search").addEventListener("input", renderDistros);
  $("distro-search").addEventListener("search", renderDistros);
  $("pack-file").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) uploadPackFile(file);
  });
  $("ready").addEventListener("click", (e) => {
    const iso = e.target.closest("[data-iso-key]");
    if (iso) {
      e.preventDefault();
      e.stopPropagation();
      attachISO(iso.getAttribute("data-iso-key"));
      return;
    }
    const rm = e.target.closest(".pack-remove");
    if (rm) {
      e.preventDefault();
      e.stopPropagation();
      const card = rm.closest("article.card");
      removePack(rm.getAttribute("data-pack-id") || (card && card.dataset.id) || "");
    }
  }, true);
  await refreshDisks();
  render();

  $("ui-lang-btn").onclick = (e) => {
    e.stopPropagation();
    toggleLangPop();
  };
  $("ui-lang-pop").addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => closeLangPop());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLangPop();
  });

  $("back").onclick = () => { if (step > 0 && !busy) { step--; showError(""); render(); } };
  $("next").onclick = async () => {
    if (busy) {
      try { await api("/api/cancel", { method: "POST" }); } catch (e) { showError(e.message); }
      return;
    }
    const err = validate();
    if (err) { showError(err); return; }
    showError("");
    if (step < 3) { step++; render(); return; }
    await startWrite();
  };
  $("empty-pw").onchange = () => {
    const off = $("empty-pw").checked;
    $("pass").disabled = off;
    $("pass2").disabled = off;
  };
  $("dark-file").onchange = (e) => { if (e.target.files[0]) uploadWallpaper("dark", e.target.files[0]); };
  $("light-file").onchange = (e) => { if (e.target.files[0]) uploadWallpaper("light", e.target.files[0]); };
  $("reset-walls").onclick = async () => {
    await api("/api/wallpaper/reset", { method: "POST" });
    $("dark-preview").src = `/api/wallpaper/dark?t=${Date.now()}`;
    $("light-preview").src = `/api/wallpaper/light?t=${Date.now()}`;
  };
  $("refresh-disks").onclick = () => refreshDisks().catch((e) => showError(e.message));
  $("device").onchange = updateDiskWarn;
  document.querySelectorAll("input[name=target]").forEach((el) => {
    el.onchange = updateDiskWarn;
  });
}

init().catch((e) => { showError(e.message); });
