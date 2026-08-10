/**
 * First Boot Linux — interactive mockup
 * GNOME-style top bar; beginner-friendly distros only.
 */

(function () {
  "use strict";

  const LOGO = (id) => `assets/distros/${id}.png`;

  /**
   * Seller recommended — pre-loaded on disk for the listed desktop.
   * `desktops` is used only when opened from Other distros (per-DE Install/Download).
   */
  const RECOMMENDED = [
    {
      id: "ubuntu",
      name: "Ubuntu",
      desktop: "GNOME",
      tagline: "Popular and well-supported",
      desc: "A polished desktop with excellent hardware support and a large software library. A safe default for most laptops.",
      version: "26.04 LTS",
      recommended: true,
      local: true,
      logo: LOGO("ubuntu"),
      desktops: [{ id: "gnome", name: "GNOME", size: "~5.9 GB", local: true }],
    },
    {
      id: "linux-mint",
      name: "Linux Mint",
      desktop: "Cinnamon",
      tagline: "Familiar and easy",
      desc: "A stable desktop that feels at home for people coming from Windows. Multimedia and drivers work out of the box.",
      version: "22.3",
      recommended: true,
      local: true,
      logo: LOGO("linux-mint"),
      desktops: [
        { id: "cinnamon", name: "Cinnamon", size: "~2.8 GB", local: true },
        { id: "mate", name: "MATE", size: "~2.6 GB", local: false },
        { id: "xfce", name: "Xfce", size: "~2.5 GB", local: false },
      ],
    },
    {
      id: "fedora",
      name: "Fedora",
      desktop: "KDE Plasma",
      tagline: "Modern Plasma desktop",
      desc: "Current free software with a polished KDE Plasma experience. Good choice if you want recent packages and solid defaults.",
      version: "44",
      recommended: true,
      local: true,
      logo: LOGO("fedora"),
      desktops: [
        { id: "plasma", name: "KDE Plasma", size: "~2.8 GB", local: true },
        { id: "gnome", name: "GNOME", size: "~2.4 GB", local: false },
      ],
    },
    {
      id: "zorin-os",
      name: "Zorin OS",
      desktop: "GNOME",
      tagline: "Designed for newcomers",
      desc: "Layouts that can look like Windows or macOS, plus tools that ease the switch from those systems.",
      version: "18.1",
      recommended: true,
      local: true,
      logo: LOGO("zorin-os"),
      desktops: [{ id: "gnome", name: "GNOME", size: "~3.6 GB", local: true }],
    },
    {
      id: "pop-os",
      name: "Pop!_OS",
      desktop: "COSMIC",
      tagline: "Built for productivity",
      desc: "A focused desktop with strong NVIDIA support and window tiling. Popular for creators and developers.",
      version: "24.04 LTS",
      recommended: true,
      local: true,
      logo: LOGO("pop-os"),
      desktops: [{ id: "cosmic", name: "COSMIC", size: "~2.9 GB", local: true }],
    },
  ];

  /** Additional distros (always download; each DE is a row with Download) */
  const CATALOG_EXTRA = [
    {
      id: "elementary-os",
      name: "elementary OS",
      desktop: "Pantheon",
      tagline: "Carefully designed",
      desc: "A thoughtfully crafted desktop with a curated app store and a calm, consistent interface.",
      version: "8",
      local: false,
      logo: LOGO("elementary-os"),
      desktops: [{ id: "pantheon", name: "Pantheon", size: "~3 GB", local: false }],
    },
    {
      id: "kubuntu",
      name: "Kubuntu",
      desktop: "KDE Plasma",
      tagline: "Ubuntu with KDE Plasma",
      desc: "The power of Ubuntu with the highly customizable KDE Plasma desktop.",
      version: "26.04 LTS",
      local: false,
      logo: LOGO("kubuntu"),
      desktops: [{ id: "plasma", name: "KDE Plasma", size: "~4 GB", local: false }],
    },
    {
      id: "xubuntu",
      name: "Xubuntu",
      desktop: "Xfce",
      tagline: "Lightweight and fast",
      desc: "Ubuntu with the Xfce desktop — lower resource use, still fully featured.",
      version: "26.04 LTS",
      local: false,
      logo: LOGO("xubuntu"),
      desktops: [{ id: "xfce", name: "Xfce", size: "~2.5 GB", local: false }],
    },
    {
      id: "lubuntu",
      name: "Lubuntu",
      desktop: "LXQt",
      tagline: "Very lightweight",
      desc: "Ubuntu with LXQt. Ideal for older machines or when you want maximum free memory.",
      version: "26.04 LTS",
      local: false,
      logo: LOGO("lubuntu"),
      desktops: [{ id: "lxqt", name: "LXQt", size: "~2 GB", local: false }],
    },
    {
      id: "ubuntu-mate",
      name: "Ubuntu MATE",
      desktop: "MATE",
      tagline: "Classic desktop layout",
      desc: "Traditional menus and panels with the stability of Ubuntu LTS.",
      version: "26.04 LTS",
      local: false,
      logo: LOGO("ubuntu-mate"),
      desktops: [{ id: "mate", name: "MATE", size: "~3.5 GB", local: false }],
    },
    {
      id: "ubuntu-budgie",
      name: "Ubuntu Budgie",
      desktop: "Budgie",
      tagline: "Elegant and efficient",
      desc: "The Budgie desktop on Ubuntu — modern, clean, and approachable.",
      version: "26.04 LTS",
      local: false,
      logo: LOGO("ubuntu-budgie"),
      desktops: [{ id: "budgie", name: "Budgie", size: "~3 GB", local: false }],
    },
    {
      id: "mx-linux",
      name: "MX Linux",
      desktop: "Xfce",
      tagline: "Stable midweight desktop",
      desc: "Debian-based with helpful tools, good hardware support, and a friendly community.",
      version: "25.2",
      local: false,
      logo: LOGO("mx-linux"),
      desktops: [
        { id: "xfce", name: "Xfce", size: "~2.5 GB", local: false },
        { id: "plasma", name: "KDE Plasma", size: "~3.2 GB", local: false },
        { id: "fluxbox", name: "Fluxbox", size: "~1.8 GB", local: false },
      ],
    },
    {
      id: "debian",
      name: "Debian",
      desktop: "GNOME",
      tagline: "Rock-solid base",
      desc: "The universal operating system. Extremely stable and free-software focused.",
      version: "13",
      local: false,
      logo: LOGO("debian"),
      desktops: [
        { id: "gnome", name: "GNOME", size: "~3.5 GB", local: false },
        { id: "plasma", name: "KDE Plasma", size: "~3.7 GB", local: false },
        { id: "xfce", name: "Xfce", size: "~3.0 GB", local: false },
        { id: "cinnamon", name: "Cinnamon", size: "~3.4 GB", local: false },
        { id: "mate", name: "MATE", size: "~3.2 GB", local: false },
        { id: "lxqt", name: "LXQt", size: "~2.8 GB", local: false },
      ],
    },
    {
      id: "opensuse",
      name: "openSUSE Leap",
      desktop: "GNOME",
      tagline: "Reliable and polished",
      desc: "A carefully tested desktop with strong tools for system management.",
      version: "16.0",
      local: false,
      logo: LOGO("opensuse"),
      desktops: [
        { id: "gnome", name: "GNOME", size: "~4.0 GB", local: false },
        { id: "plasma", name: "KDE Plasma", size: "~4.2 GB", local: false },
      ],
    },
    {
      id: "deepin",
      name: "Deepin",
      desktop: "DDE",
      tagline: "Beautiful desktop",
      desc: "A visually refined desktop environment with its own design language.",
      version: "25",
      local: false,
      logo: LOGO("deepin"),
      desktops: [{ id: "dde", name: "Deepin Desktop (DDE)", size: "~4 GB", local: false }],
    },
    {
      id: "peppermint-os",
      name: "Peppermint OS",
      desktop: "Xfce",
      tagline: "Cloud-friendly lightweight",
      desc: "A light desktop that works well for web-centric and everyday use.",
      version: "2024",
      local: false,
      logo: LOGO("peppermint-os"),
      desktops: [{ id: "xfce", name: "Xfce", size: "~1.5 GB", local: false }],
    },
    {
      id: "bodhi-linux",
      name: "Bodhi Linux",
      desktop: "Moksha",
      tagline: "Minimal and elegant",
      desc: "A light Ubuntu-based system with the Moksha desktop.",
      version: "7.0",
      local: false,
      logo: LOGO("bodhi-linux"),
      desktops: [{ id: "moksha", name: "Moksha", size: "~1.5 GB", local: false }],
    },
    {
      id: "q4os",
      name: "Q4OS",
      desktop: "Trinity",
      tagline: "Classic Windows-like",
      desc: "A Debian-based system with a Trinity desktop option that feels familiar.",
      version: "5.8",
      local: false,
      logo: LOGO("q4os"),
      desktops: [
        { id: "trinity", name: "Trinity", size: "~1.5 GB", local: false },
        { id: "plasma", name: "KDE Plasma", size: "~2.5 GB", local: false },
      ],
    },
  ];

  /** Full “other distros” list: recommended first, then the rest */
  const CATALOG = RECOMMENDED.concat(CATALOG_EXTRA);

  const WIFI_NETWORKS = [
    { ssid: "Home-5G", secure: true },
    { ssid: "Home-2.4", secure: true },
    { ssid: "CoffeeShop_Guest", secure: false },
    { ssid: "Office-Secure", secure: true },
  ];

  const STEPS_LOCAL = [
    { pct: 10, label: "Verifying image…" },
    { pct: 30, label: "Writing partitions…" },
    { pct: 55, label: "Installing bootloader…" },
    { pct: 80, label: "Finishing setup…" },
    { pct: 100, label: "Complete" },
  ];

  const STEPS_DOWNLOAD = [
    { pct: 8, label: "Connecting to mirror…" },
    { pct: 25, label: "Downloading…" },
    { pct: 50, label: "Downloading…" },
    { pct: 65, label: "Verifying download…" },
    { pct: 80, label: "Installing…" },
    { pct: 100, label: "Complete" },
  ];

  const state = {
    network: {
      connected: false,
      type: null,
      name: null,
      ethernetPlugged: false,
    },
    darkStyle: true,
    catalogOpen: false,
    /** 'recommended' | 'catalog' — which popover style to use */
    detailMode: "recommended",
    selected: null,
    selectedDesktop: null,
    installTimer: null,
    pendingPower: null,
  };

  const $ = (id) => document.getElementById(id);

  const els = {
    clockText: $("clock-text"),
    systemMenuBtn: $("system-menu-btn"),
    quickSettings: $("quick-settings"),
    networkMenu: $("network-menu"),
    powerMenu: $("power-menu"),
    powerMenuBtn: $("power-menu-btn"),
    networkToggle: $("network-toggle"),
    darkModeToggle: $("dark-mode-toggle"),
    networkBack: $("network-back"),
    netStatusIcon: $("net-status-icon"),
    qsNetIcon: $("qs-net-icon"),
    qsNetLabel: $("qs-net-label"),
    qsNetSub: $("qs-net-sub"),
    ethernetDetail: $("ethernet-detail"),
    ethernetToggle: $("ethernet-toggle"),
    wifiList: $("wifi-list"),
    backdrop: $("backdrop"),
    recommendedGrid: $("recommended-grid"),
    viewOtherBtn: $("view-other-btn"),
    viewOtherLabel: $("view-other-label"),
    catalog: $("catalog"),
    catalogList: $("catalog-list"),
    screenChooser: $("screen-chooser"),
    screenDetail: $("screen-detail"),
    screenInstall: $("screen-install"),
    screenDone: $("screen-done"),
    detailBack: $("detail-back"),
    cancelDetailBtn: $("cancel-detail-btn"),
    detailLogo: $("detail-logo"),
    detailTitle: $("detail-title"),
    detailDesktop: $("detail-desktop"),
    detailVersion: $("detail-version"),
    detailTagline: $("detail-tagline"),
    detailDesc: $("detail-desc"),
    deOptions: $("de-options"),
    deOptionsList: $("de-options-list"),
    detailWarn: $("detail-warn"),
    detailWarnText: $("detail-warn-text"),
    detailActions: $("detail-actions"),
    installBtn: $("install-btn"),
    installLogo: $("install-logo"),
    installTitle: $("install-title"),
    installSubtitle: $("install-subtitle"),
    progressFill: $("progress-fill"),
    progressLabel: $("progress-label"),
    progressStep: $("progress-step"),
    progressBar: $("progress-bar"),
    doneMessage: $("done-message"),
    rebootBtn: $("reboot-btn"),
    powerModal: $("power-modal"),
    powerModalTitle: $("power-modal-title"),
    powerModalBody: $("power-modal-body"),
    powerModalCancel: $("power-modal-cancel"),
    powerModalConfirm: $("power-modal-confirm"),
    toast: $("toast"),
  };

  function allDistros() {
    return CATALOG;
  }

  function findDistro(id) {
    return allDistros().find((d) => d.id === id);
  }

  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      els.toast.hidden = true;
    }, 2800);
  }

  function closeMenus() {
    els.quickSettings.hidden = true;
    els.networkMenu.hidden = true;
    els.powerMenu.hidden = true;
    els.systemMenuBtn.setAttribute("aria-expanded", "false");
    els.backdrop.hidden = true;
  }

  function openQuickSettings() {
    const wasOpen =
      !els.quickSettings.hidden ||
      !els.networkMenu.hidden ||
      !els.powerMenu.hidden;
    closeMenus();
    if (wasOpen) return;
    els.quickSettings.hidden = false;
    els.systemMenuBtn.setAttribute("aria-expanded", "true");
    els.backdrop.hidden = false;
  }

  function showScreen(name) {
    els.screenChooser.hidden = name !== "chooser";
    els.screenDetail.hidden = name !== "detail";
    els.screenInstall.hidden = name !== "install";
    els.screenDone.hidden = name !== "done";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateClock() {
    const now = new Date();
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    const day = now.getDate();
    const mon = months[now.getMonth()];
    const h = String(now.getHours()).padStart(2, "0");
    const m = String(now.getMinutes()).padStart(2, "0");
    els.clockText.textContent = `${day} ${mon} ${h}:${m}`;
  }

  function applyTheme() {
    document.documentElement.setAttribute(
      "data-theme",
      state.darkStyle ? "dark" : "light"
    );
    els.darkModeToggle.classList.toggle("active", state.darkStyle);
    els.darkModeToggle.setAttribute("aria-pressed", String(state.darkStyle));
  }

  function updateNetworkUI() {
    const n = state.network;
    let icon = "assets/status/network-offline-symbolic.svg";
    let label = "Network";
    let sub = "Off";
    let active = false;

    if (n.connected && n.type === "ethernet") {
      icon = "assets/status/network-wired-symbolic.svg";
      label = "Wired";
      sub = "Connected";
      active = true;
    } else if (n.connected && n.type === "wifi") {
      icon = "assets/status/network-wireless-symbolic.svg";
      label = n.name;
      sub = "Connected";
      active = true;
    } else {
      icon = "assets/status/network-offline-symbolic.svg";
      label = "Network";
      sub = "Not connected";
      active = false;
    }

    els.netStatusIcon.src = icon;
    els.qsNetIcon.src = icon;
    els.qsNetLabel.textContent = label;
    els.qsNetSub.textContent = sub;
    els.networkToggle.classList.toggle("active", active);
    els.networkToggle.setAttribute("aria-pressed", String(active));

    if (n.ethernetPlugged && n.connected && n.type === "ethernet") {
      els.ethernetDetail.textContent = "Connected";
      els.ethernetToggle.textContent = "Disconnect";
    } else if (n.ethernetPlugged) {
      els.ethernetDetail.textContent = "Cable detected";
      els.ethernetToggle.textContent = "Connect";
    } else {
      els.ethernetDetail.textContent = "Cable unplugged";
      els.ethernetToggle.textContent = "Plug in";
    }

    renderWifi();
  }

  function renderWifi() {
    els.wifiList.innerHTML = "";

    WIFI_NETWORKS.forEach((net) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wifi-item";
      const isActive =
        state.network.connected &&
        state.network.type === "wifi" &&
        state.network.name === net.ssid;
      if (isActive) btn.classList.add("active");

      btn.innerHTML = `
        <span class="wifi-item-left">
          <img class="sym" src="assets/status/network-wireless-signal-excellent-symbolic.svg" alt="" draggable="false" />
          <span>${escapeHtml(net.ssid)}</span>
        </span>
        <span style="font-size:12px;opacity:0.7">${isActive ? "Connected" : ""}</span>
      `;
      btn.addEventListener("click", () => connectWifi(net.ssid));
      li.appendChild(btn);
      els.wifiList.appendChild(li);
    });
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function connectWifi(ssid) {
    els.qsNetSub.textContent = "Connecting…";
    setTimeout(() => {
      state.network.connected = true;
      state.network.type = "wifi";
      state.network.name = ssid;
      updateNetworkUI();
      showToast(`Connected to ${ssid}`);
    }, 700);
  }

  function toggleEthernet() {
    if (!state.network.ethernetPlugged) {
      state.network.ethernetPlugged = true;
      updateNetworkUI();
      return;
    }
    if (state.network.connected && state.network.type === "ethernet") {
      state.network.connected = false;
      state.network.type = null;
      state.network.name = null;
      updateNetworkUI();
    } else {
      setTimeout(() => {
        state.network.connected = true;
        state.network.type = "ethernet";
        state.network.name = "Ethernet";
        updateNetworkUI();
        showToast("Connected via Ethernet");
      }, 400);
    }
  }

  function renderRecommended() {
    els.recommendedGrid.innerHTML = "";
    RECOMMENDED.forEach((d) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "distro-card";
      btn.setAttribute("role", "listitem");
      btn.innerHTML = `
        <img class="distro-logo" src="${d.logo}" alt="" draggable="false" />
        <div class="card-text">
          <h3>${escapeHtml(d.name)}</h3>
          <p class="card-desktop">${escapeHtml(d.desktop)}</p>
          <p class="card-version">${escapeHtml(d.version)}</p>
        </div>
      `;
      btn.addEventListener("click", () => openDetail(d.id, "recommended"));
      els.recommendedGrid.appendChild(btn);
    });
  }

  function renderCatalog() {
    els.catalogList.innerHTML = "";
    CATALOG.forEach((d) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "catalog-row";
      btn.setAttribute("role", "listitem");
      btn.innerHTML = `
        <img class="distro-logo" src="${d.logo}" alt="" draggable="false" />
        <h3>${escapeHtml(d.name)}</h3>
        <span class="meta">${escapeHtml(d.version)}</span>
      `;
      btn.addEventListener("click", () => openDetail(d.id, "catalog"));
      els.catalogList.appendChild(btn);
    });
  }

  function toggleCatalog() {
    state.catalogOpen = !state.catalogOpen;
    els.catalog.hidden = !state.catalogOpen;
    els.viewOtherBtn.setAttribute("aria-expanded", String(state.catalogOpen));
    els.viewOtherLabel.textContent = state.catalogOpen
      ? "Hide other distros"
      : "View other distros";
    if (state.catalogOpen) {
      renderCatalog();
    }
  }

  /** Other-distros popover: DE rows with per-edition Install / Download */
  function renderDeOptions(d) {
    els.deOptionsList.innerHTML = "";
    state.selectedDesktop = null;

    if (state.detailMode !== "catalog" || !d.desktops || !d.desktops.length) {
      els.deOptions.hidden = true;
      return;
    }

    els.deOptions.hidden = false;
    const offline = !state.network.connected;
    const needsDownload = d.desktops.some((de) => !de.local);

    d.desktops.forEach((de) => {
      const row = document.createElement("div");
      row.className = "de-option";
      row.setAttribute("role", "listitem");

      const actionLabel = de.local ? "Install" : "Download";
      const actionDisabled = !de.local && offline;

      row.innerHTML = `
        <span class="de-option-meta">
          <span class="de-option-name">${escapeHtml(de.name)}</span>
          <span class="de-option-size">${escapeHtml(de.size || "")}${
            de.local ? " · On disk" : ""
          }</span>
        </span>
        <button type="button" class="de-option-action${de.local ? " local" : ""}"${
          actionDisabled ? " disabled" : ""
        }>${actionLabel}</button>
      `;

      const actionBtn = row.querySelector(".de-option-action");
      actionBtn.addEventListener("click", () => {
        startInstall(de);
      });

      els.deOptionsList.appendChild(row);
    });

    if (needsDownload && offline) {
      els.detailWarn.hidden = false;
      els.detailWarnText.textContent =
        "Connect to a network to download editions that are not on disk.";
    }
  }

  /**
   * @param {string} id
   * @param {'recommended'|'catalog'} mode
   */
  function openDetail(id, mode) {
    const d = findDistro(id);
    if (!d) return;
    state.selected = d;
    state.detailMode = mode === "catalog" ? "catalog" : "recommended";
    state.selectedDesktop = null;
    closeMenus();

    els.detailLogo.src = d.logo;
    els.detailLogo.alt = d.name;
    els.detailTitle.textContent = d.name;
    els.detailVersion.textContent = d.version;
    els.detailTagline.textContent = d.tagline;
    els.detailDesc.textContent = d.desc;
    els.detailWarn.hidden = true;

    if (state.detailMode === "recommended") {
      // Simple popover: fixed DE + single Install
      els.detailDesktop.hidden = false;
      els.detailDesktop.textContent = d.desktop || "";
      els.deOptions.hidden = true;
      els.deOptionsList.innerHTML = "";
      els.detailActions.classList.remove("catalog-mode");
      els.installBtn.hidden = false;
      els.installBtn.disabled = false;
      els.installBtn.textContent = "Install";
    } else {
      // Other distros: DE list with per-row Install / Download
      els.detailDesktop.hidden = true;
      els.detailDesktop.textContent = "";
      els.detailActions.classList.add("catalog-mode");
      renderDeOptions(d);
    }

    showScreen("detail");
  }

  /**
   * @param {{ id: string, name: string, local?: boolean }|null} de
   */
  function startInstall(de) {
    const d = state.selected;
    if (!d) return;

    // Recommended popover: install the pre-loaded desktop
    if (state.detailMode === "recommended") {
      de = {
        id: "default",
        name: d.desktop,
        local: true,
      };
    }

    if (!de) return;

    if (!de.local && !state.network.connected) {
      showToast("Connect to a network first");
      openQuickSettings();
      return;
    }

    state.selectedDesktop = de;
    closeMenus();
    showScreen("install");

    const deLabel = de.name || d.desktop;
    const isLocal = !!de.local;

    els.installLogo.src = d.logo;
    els.installLogo.alt = d.name;
    els.installTitle.textContent = deLabel
      ? `Installing ${d.name} (${deLabel})`
      : `Installing ${d.name}`;
    els.installSubtitle.textContent = isLocal ? "" : "Downloading…";
    els.progressFill.style.width = "0%";
    els.progressLabel.textContent = "0%";
    els.progressStep.textContent = "";
    els.progressBar.setAttribute("aria-valuenow", "0");

    const steps = isLocal ? STEPS_LOCAL : STEPS_DOWNLOAD;
    let i = 0;
    if (state.installTimer) clearInterval(state.installTimer);

    function tick() {
      if (i >= steps.length) {
        clearInterval(state.installTimer);
        state.installTimer = null;
        setTimeout(() => {
          els.doneMessage.textContent = deLabel
            ? `${d.name} (${deLabel}) is ready. Restart to begin using it.`
            : `${d.name} is ready. Restart to begin using it.`;
          showScreen("done");
        }, 350);
        return;
      }
      const step = steps[i];
      els.progressFill.style.width = step.pct + "%";
      els.progressLabel.textContent = step.pct + "%";
      els.progressStep.textContent = step.label;
      els.installSubtitle.textContent = step.label;
      els.progressBar.setAttribute("aria-valuenow", String(step.pct));
      i += 1;
    }

    tick();
    state.installTimer = setInterval(tick, isLocal ? 500 : 650);
  }

  function resetChooser() {
    if (state.installTimer) {
      clearInterval(state.installTimer);
      state.installTimer = null;
    }
    state.selected = null;
    showScreen("chooser");
  }

  function requestPower(action) {
    closeMenus();
    state.pendingPower = action;
    if (action === "shutdown") {
      els.powerModalTitle.textContent = "Power Off?";
      els.powerModalBody.textContent = "The computer will shut down.";
      els.powerModalConfirm.textContent = "Power Off";
    } else {
      els.powerModalTitle.textContent = "Restart?";
      els.powerModalBody.textContent = "The computer will restart.";
      els.powerModalConfirm.textContent = "Restart";
    }
    els.powerModal.hidden = false;
  }

  function confirmPower() {
    els.powerModal.hidden = true;
    const action = state.pendingPower;
    state.pendingPower = null;
    if (action === "shutdown") {
      document.body.style.transition = "opacity 0.5s";
      document.body.style.opacity = "0";
      setTimeout(() => {
        document.body.style.opacity = "1";
        document.body.style.transition = "";
        showToast("Click to power on");
        const wake = () => document.removeEventListener("click", wake);
        setTimeout(() => document.addEventListener("click", wake, { once: true }), 50);
      }, 600);
    } else {
      document.body.style.transition = "opacity 0.35s";
      document.body.style.opacity = "0";
      setTimeout(() => {
        document.body.style.opacity = "1";
        document.body.style.transition = "";
        resetChooser();
      }, 400);
    }
  }

  function bind() {
    els.systemMenuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openQuickSettings();
    });

    els.backdrop.addEventListener("click", closeMenus);

    els.networkToggle.addEventListener("click", () => {
      els.quickSettings.hidden = true;
      els.networkMenu.hidden = false;
    });

    els.networkBack.addEventListener("click", () => {
      els.networkMenu.hidden = true;
      els.quickSettings.hidden = false;
    });

    els.darkModeToggle.addEventListener("click", () => {
      state.darkStyle = !state.darkStyle;
      applyTheme();
    });

    els.ethernetToggle.addEventListener("click", toggleEthernet);

    els.powerMenuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      els.quickSettings.hidden = true;
      els.powerMenu.hidden = false;
      els.backdrop.hidden = false;
    });

    els.powerMenu.querySelectorAll("[data-power]").forEach((btn) => {
      btn.addEventListener("click", () => requestPower(btn.dataset.power));
    });

    els.powerModalCancel.addEventListener("click", () => {
      els.powerModal.hidden = true;
      state.pendingPower = null;
    });
    els.powerModalConfirm.addEventListener("click", confirmPower);

    els.viewOtherBtn.addEventListener("click", toggleCatalog);
    els.detailBack.addEventListener("click", () => showScreen("chooser"));
    els.cancelDetailBtn.addEventListener("click", () => showScreen("chooser"));
    els.installBtn.addEventListener("click", () => startInstall(null));
    els.rebootBtn.addEventListener("click", resetChooser);

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (!els.powerModal.hidden) {
          els.powerModal.hidden = true;
          state.pendingPower = null;
          return;
        }
        if (!els.networkMenu.hidden) {
          els.networkMenu.hidden = true;
          els.quickSettings.hidden = false;
          return;
        }
        closeMenus();
        if (!els.screenDetail.hidden) showScreen("chooser");
      }
    });

    els.quickSettings.addEventListener("click", (e) => e.stopPropagation());
    els.networkMenu.addEventListener("click", (e) => e.stopPropagation());
    els.powerMenu.addEventListener("click", (e) => e.stopPropagation());
  }

  function init() {
    updateClock();
    setInterval(updateClock, 15000);
    applyTheme();
    renderRecommended();
    updateNetworkUI();
    bind();

    const epiphanyBtn = $("epiphany-btn");
    if (epiphanyBtn) {
      epiphanyBtn.addEventListener("click", () => {
        showToast("Web browser (mockup)");
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
