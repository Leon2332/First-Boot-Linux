const steps = ["Shop", "Look", "Distros", "Write"];
let state = null;
let step = 0;
let busy = false;

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

function card(d, ready) {
  const el = document.createElement("label");
  el.className = "card" + (ready ? "" : " disabled");
  const src = d.logo ? `/api/logo/${encodeURIComponent(d.id)}` : "";
  el.innerHTML = `
    <input type="checkbox" ${ready && d.suggested_default ? "checked" : ""} ${ready ? "" : "disabled"}>
    ${src ? `<img class="logo" src="${src}" alt="">` : "<span></span>"}
    <div>
      <h3>${escapeHtml(d.name)}</h3>
      <p class="meta">${escapeHtml(d.version)} · ${escapeHtml(d.tagline)}</p>
      <p>${escapeHtml(d.description)}</p>
      <p class="tag">${ready
        ? `${escapeHtml(d.edition)} · ${escapeHtml(d.size)} · on the USB`
        : "Install support is not ready"}</p>
    </div>`;
  el.querySelector("input").dataset.id = d.id;
  return el;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function selected() {
  return [...document.querySelectorAll("#ready input:checked")].map((el) => el.dataset.id);
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
  if (step === 2 && selected().length === 0) return "Tick at least one distro to keep on the USB.";
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
}

function render() {
  renderSteps();
  document.querySelectorAll(".page").forEach((p, i) => {
    p.classList.toggle("hidden", i !== step);
  });
  $("back").disabled = step === 0 || busy;
  $("next").textContent = step === 3 ? "Write" : "Continue";
  $("next").disabled = busy;
  if (step === 3) refreshEstimate();
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
    if (!confirm(`Erase ${body.device} (${label}) and write First Boot?\n\nEverything on that stick will be lost.`)) {
      return;
    }
  }
  busy = true;
  showError("");
  render();
  try {
    await api("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
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
    $("status").textContent = p.stage || "Working…";
    $("bar").style.width = `${Math.round((p.fraction || 0) * 100)}%`;
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
  $("img-path").value = state.default_image;
  $("dark-preview").src = "/api/wallpaper/dark";
  $("light-preview").src = "/api/wallpaper/light";
  const ready = $("ready");
  const later = $("later");
  state.distros.forEach((d) => {
    (d.stageable ? ready : later).appendChild(card(d, d.stageable));
  });
  await refreshDisks();
  render();

  $("back").onclick = () => { if (step > 0 && !busy) { step--; showError(""); render(); } };
  $("next").onclick = async () => {
    if (busy) return;
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
}

init().catch((e) => { showError(e.message); });
