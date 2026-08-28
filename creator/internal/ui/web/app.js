const steps = ["Shop", "Look", "Recommendations", "Write"];
let state = null;
let step = 0;
let busy = false;
let barFrac = 0;

const $ = (id) => document.getElementById(id);

async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showError(msg) {
  $("error").textContent = msg || "";
}

function renderSteps() {
  const nav = $("steps");
  nav.innerHTML = "";
  steps.forEach((name, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `<span class="n">${i + 1}</span>${name}`;
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
  const src = d.logo ? `/api/logo/${encodeURIComponent(d.id)}` : "";
  const full = ticked.length >= PICKED_SLOTS;
  const editions = (d.editions || []).map((ed) => {
    const key = stagedKey(d.id, ed.id);
    const ready = !!ed.stageable;
    const checked = ticked.includes(key);
    const locked = !ready || (full && !checked);
    const meta = ready
      ? `${escapeHtml(ed.size)} · on the USB`
      : "Install support is not ready";
    return `<label class="edition">
      <input type="checkbox" data-key="${escapeHtml(key)}" data-ready="${ready ? "1" : "0"}" ${checked ? "checked" : ""} ${locked ? "disabled" : ""}>
      <span class="ed-name">${escapeHtml(ed.name)}</span>
      <span class="ed-meta">${meta}</span>
    </label>`;
  }).join("");
  el.innerHTML = `
    ${src ? `<img class="logo" src="${src}" alt="">` : "<span></span>"}
    <div>
      <h3>${escapeHtml(d.name)}</h3>
      <p class="meta">${escapeHtml(d.version)} · ${escapeHtml(d.tagline)}</p>
      <p>${escapeHtml(d.description)}</p>
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
  empty.hidden = distros.length > 0;
  renderPicked();
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
    $("size").textContent = est.summary;
    $("hint").textContent = est.hint || "";
  } catch (e) {
    $("size").textContent = e.message;
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
  opt0.textContent = "Choose a USB stick";
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
  const list = $("task-list");
  if (!tasks || !tasks.length) {
    list.hidden = true;
    list.innerHTML = "";
    return;
  }
  list.hidden = false;
  list.innerHTML = tasks.map((t) => {
    const st = t.status === "done" || t.status === "active" || t.status === "error" ? t.status : "pending";
    return `<li class="${st}"><span class="task-mark" aria-hidden="true"></span><span>${escapeHtml(t.label)}</span></li>`;
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
    next.textContent = "Cancel";
    next.classList.remove("primary");
    next.classList.add("danger");
    next.disabled = false;
  } else {
    next.textContent = step === 3 ? "Write" : "Continue";
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
    if (!confirm(`Your disk will be formatted. All data will be permanently erased.\n\nErase ${body.device} (${label}) and write First Boot?`)) {
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
    renderTasks(first.tasks);
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
    $("status").textContent = p.stage || "Working…";
    if (p.done) {
      busy = false;
      if (p.error) showError(p.error);
      else $("status").textContent = p.stage || "Done.";
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

async function init() {
  state = await api("/api/state");
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
  renderDistros();
  $("distro-search").addEventListener("input", renderDistros);
  $("distro-search").addEventListener("search", renderDistros);
  await refreshDisks();
  render();

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
