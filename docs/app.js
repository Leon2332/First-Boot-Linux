(function () {
  "use strict";

  const LOGO = (id) => `assets/distros/${id}.png`;

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
      id: "bazzite",
      name: "Bazzite",
      desktop: "KDE Plasma",
      tagline: "Gaming-ready desktop",
      desc: "A Fedora Atomic image built for gaming PCs and handhelds, with Steam, drivers, and gaming tools ready to go.",
      version: "43",
      recommended: true,
      local: true,
      logo: LOGO("bazzite"),
      desktops: [
        { id: "plasma", name: "KDE Plasma", size: "~3.5 GB", local: true },
        { id: "gnome", name: "GNOME", size: "~3.2 GB", local: false },
      ],
    },
    {
      id: "ms-windows",
      name: "MS Windows",
      desktop: "Windows",
      tagline: "Familiar and widely used",
      desc: "The desktop most people already know. Broad software and hardware support, with a familiar Start menu and settings.",
      version: "11",
      recommended: true,
      local: false,
      logo: LOGO("ms-windows"),
      desktops: [{ id: "windows-11", name: "Windows 11", size: "~6.5 GB", local: false }],
    },
  ];

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
    {
      id: "free-bsd",
      name: "FreeBSD",
      desktop: "KDE Plasma",
      tagline: "The other free Unix",
      desc: "A reliable Unix-like system with a strong networking stack, ports collection, and optional desktop environments.",
      version: "15.0",
      local: false,
      logo: LOGO("free-bsd"),
      desktops: [
        { id: "plasma", name: "KDE Plasma", size: "~3.2 GB", local: false },
        { id: "gnome", name: "GNOME", size: "~3.0 GB", local: false },
        { id: "xfce", name: "Xfce", size: "~2.4 GB", local: false },
      ],
    },
  ];

  const CATALOG = RECOMMENDED.concat(CATALOG_EXTRA);

  const WIFI_NETWORKS = [
    { ssid: "Home-5G", secure: true, saved: true },
    { ssid: "Home-2.4", secure: true, saved: true },
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

  const STEPS_FETCH = [
    { pct: 8, label: "Connecting…" },
    { pct: 28, label: "Downloading…" },
    { pct: 52, label: "Downloading…" },
    { pct: 74, label: "Downloading…" },
    { pct: 90, label: "Verifying…" },
    { pct: 100, label: "Ready" },
  ];

  const STEPS_SHOP = [
    { pct: 12, label: "Preparing the disk…" },
    { pct: 34, label: "Copying boot files…" },
    { pct: 58, label: "Copying First Boot…" },
    { pct: 82, label: "Copying recommended systems…" },
    { pct: 100, label: "Complete" },
  ];

  const SHOP_LOGO = "Logo/First%20Boot%20Linux.png";

  const state = {
    network: {
      connected: false,
      type: null,
      name: null,
      ethernetPlugged: false,
    },
    wifiExpanded: null,
    wifiSaved: new Set(
      WIFI_NETWORKS.filter((n) => n.saved).map((n) => n.ssid)
    ),
    wifiSecrets: {},
    wifiReveal: {},
    wifiConnecting: null,
    darkStyle: true,
    detailMode: "recommended",
    selected: null,
    selectedDesktop: null,
    installTimer: null,
    downloads: {},
    pendingPower: null,
    volume: 70,
    muted: false,
    brightness: 100,
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
    volStatusIcon: $("vol-status-icon"),
    qsVolume: $("qs-volume"),
    qsVolumeIcon: $("qs-volume-icon"),
    qsVolumeMute: $("qs-volume-mute"),
    qsBrightness: $("qs-brightness"),
    qsBrightnessImg: $("qs-brightness-img"),
    ethernetDetail: $("ethernet-detail"),
    ethernetToggle: $("ethernet-toggle"),
    wifiList: $("wifi-list"),
    backdrop: $("backdrop"),
    recommendedGrid: $("recommended-grid"),
    catalogScroll: $("catalog-scroll"),
    catalogList: $("catalog-list"),
    catalogBack: $("catalog-back"),
    catalogPopover: $("catalog-popover"),
    detailPopover: $("detail-popover"),
    popoverStage: $("popover-stage"),
    popoverTrack: $("popover-track"),
    screenChooser: $("screen-chooser"),
    screenOverlay: $("screen-overlay"),
    screenDetail: $("screen-overlay"),
    screenInstall: $("screen-install"),
    screenDone: $("screen-done"),
    detailBack: $("detail-back"),
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
    detailProgress: $("detail-progress"),
    detailProgressFill: $("detail-progress-fill"),
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
    startOverlay: $("start-overlay"),
    startFullscreenBtn: $("start-fullscreen-btn"),
    startSkipBtn: $("start-skip-btn"),
    appMenuBtn: $("app-menu-btn"),
    appMenu: $("app-menu"),
    appMenuInstallDevice: $("app-menu-install-device"),
    appMenuEpiphany: $("app-menu-epiphany"),
    appMenuSysinfo: $("app-menu-sysinfo"),
    appMenuTerminal: $("app-menu-terminal"),
    epiWindow: $("epi-window"),
    epiHeaderbar: $("epi-headerbar"),
    epiTitle: $("epi-title"),
    epiMax: $("epi-max"),
    epiClose: $("epi-close"),
    epiUrl: $("epi-url"),
    epiPage: $("epi-page"),
    infoWindow: $("info-window"),
    infoHeaderbar: $("info-headerbar"),
    infoMax: $("info-max"),
    infoClose: $("info-close"),
    infoHw: $("info-hw"),
    infoSw: $("info-sw"),
    termWindow: $("term-window"),
    termHeaderbar: $("term-headerbar"),
    termTitle: $("term-title"),
    termMax: $("term-max"),
    termClose: $("term-close"),
    termBody: $("term-body"),
    termScroll: $("term-scroll"),
    termTyped: $("term-typed"),
    termCwd: $("term-cwd"),
  };

  const TERM = {
    user: "user",
    host: "firstboot",
    cwd: "~",
    history: [],
    histIndex: -1,
    draft: "",
    line: "",
    open: false,
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
    els.appMenu.hidden = true;
    els.systemMenuBtn.setAttribute("aria-expanded", "false");
    els.appMenuBtn.setAttribute("aria-expanded", "false");
    els.backdrop.hidden = true;
    if (state.wifiExpanded) {
      setWifiExpanded(null);
      renderWifi();
    }
  }

  function startOverlayOpen() {
    return els.startOverlay && !els.startOverlay.hidden;
  }

  function dismissStartOverlay() {
    if (els.startOverlay) els.startOverlay.hidden = true;
  }

  async function enterFullscreenPreview() {
    const target = document.documentElement;
    try {
      if (target.requestFullscreen) await target.requestFullscreen();
      else if (target.webkitRequestFullscreen) await target.webkitRequestFullscreen();
      else if (target.msRequestFullscreen) await target.msRequestFullscreen();
    } catch {
    }
    dismissStartOverlay();
  }

  function termPromptHtml() {
    return (
      `<span class="term-prompt-user">${TERM.user}@${TERM.host}</span>` +
      `<span class="term-prompt-colon">:</span>` +
      `<span class="term-prompt-path">${escapeHtml(TERM.cwd)}</span>` +
      `<span class="term-prompt-dollar">$</span> `
    );
  }

  function termUpdateTitle() {
    const title = `${TERM.user}@${TERM.host}: ${TERM.cwd}`;
    if (els.termTitle) els.termTitle.textContent = title;
    if (els.termCwd) els.termCwd.textContent = TERM.cwd;
  }

  function termAppendLine(html, className) {
    const div = document.createElement("div");
    div.className = "term-line" + (className ? " " + className : "");
    div.innerHTML = html;
    els.termScroll.appendChild(div);
  }

  function termScrollBottom() {
    if (els.termBody) els.termBody.scrollTop = els.termBody.scrollHeight;
  }

  function termSetLine(text) {
    TERM.line = text;
    if (els.termTyped) els.termTyped.textContent = text;
  }

  function termWelcome() {
    els.termScroll.innerHTML = "";
    termAppendLine(
      "Welcome to First Boot Linux — Terminal (mockup).\n" +
        "Type <span class=\"term-cmd\">help</span> for available commands."
    );
    termAppendLine("");
    termUpdateTitle();
    termSetLine("");
    termScrollBottom();
  }

  function termRunCommand(raw) {
    const input = raw.trim();
    termAppendLine(termPromptHtml() + escapeHtml(raw));

    if (!input) {
      termScrollBottom();
      return;
    }

    TERM.history.push(raw);
    TERM.histIndex = TERM.history.length;

    const parts = input.split(/\s+/);
    const cmd = parts[0];
    const args = parts.slice(1);

    const net = state.network;
    const netLabel = !net.connected
      ? "offline"
      : net.type === "wifi"
        ? `wifi (${net.name})`
        : "ethernet";

    if (cmd === "help" || cmd === "?") {
      termAppendLine(
        [
          "Available commands:",
          "  help              Show this help",
          "  clear             Clear the terminal",
          "  uname [-a]        System information",
          "  whoami            Current user",
          "  hostname          Machine hostname",
          "  pwd               Print working directory",
          "  ls                List directory",
          "  cat /etc/os-release",
          "  date              Current date and time",
          "  echo [text]       Print text",
          "  fastfetch         System summary",
          "  network           Network status",
          "  exit              Close the terminal",
        ].join("\n"),
        "term-out"
      );
    } else if (cmd === "clear") {
      els.termScroll.innerHTML = "";
    } else if (cmd === "uname") {
      if (args[0] === "-a" || args.includes("-a")) {
        termAppendLine(
          "Linux firstboot 7.1.8-generic #1 SMP PREEMPT_DYNAMIC x86_64 GNU/Linux",
          "term-out"
        );
      } else {
        termAppendLine("Linux", "term-out");
      }
    } else if (cmd === "whoami") {
      termAppendLine(TERM.user, "term-out");
    } else if (cmd === "hostname") {
      termAppendLine(TERM.host, "term-out");
    } else if (cmd === "pwd") {
      termAppendLine(
        TERM.cwd === "~" ? `/home/${TERM.user}` : TERM.cwd,
        "term-out"
      );
    } else if (cmd === "ls" || cmd === "ll") {
      termAppendLine(
        "Desktop  Documents  Downloads  Music  Pictures  Public  Templates  Videos",
        "term-out"
      );
    } else if (cmd === "cat" && args[0] === "/etc/os-release") {
      termAppendLine(
        [
          'NAME="First Boot Linux"',
          'PRETTY_NAME="First Boot Linux 0.1.1"',
          'ID=firstboot',
          'VERSION_ID="0.1.1"',
          "HOME_URL=\"https://example.com/first-boot-linux\"",
        ].join("\n"),
        "term-out"
      );
    } else if (cmd === "cat") {
      termAppendLine(
        `cat: ${args[0] || ""}: No such file or directory`,
        "term-err"
      );
    } else if (cmd === "date") {
      termAppendLine(new Date().toString(), "term-out");
    } else if (cmd === "echo") {
      termAppendLine(args.join(" "), "term-out");
    } else if (cmd === "fastfetch") {
      termAppendLine(
        [
          `${TERM.user}@${TERM.host}`,
          "-----------------",
          "OS: First Boot Linux 0.1.1 x86_64",
          "Host: Micro-Star International Co., Ltd. MS-7D14",
          "Kernel: Linux 7.1.8-generic",
          "Firmware: 1.G0",
          "Shell: bash 5.2.37",
          "Display: 1920x1080 in 27\", 100 Hz",
          "WM: cage (Wayland)",
          "Terminal: gnome-terminal",
          "CPU: AMD Ryzen™ 7 5700G with Radeon™ Graphics (16)",
          "GPU: AMD Radeon™ RX 7800 XT",
          "GPU 1: AMD Radeon™ Graphics",
          "Memory: 16.0 GiB DDR4-3200",
          "Disk (/): PCIe 3.0 - 456.35 GiB (ext4)",
          "Disk (/mnt/): SATA 3.0 - 915.82 GiB (ext4)",
          "Disk (/mnt/): SATA 3.0 - 915.82 GiB (ext4)",
          `Network: ${netLabel}`,
        ].join("\n"),
        "term-out"
      );
    } else if (cmd === "network" || cmd === "nmcli") {
      if (net.connected) {
        termAppendLine(
          `Connected via ${net.type}${net.name ? ` (${net.name})` : ""}`,
          "term-out"
        );
      } else {
        termAppendLine("Not connected", "term-out");
      }
    } else if (cmd === "exit" || cmd === "logout") {
      closeTerminal();
      return;
    } else {
      termAppendLine(`bash: ${escapeHtml(cmd)}: command not found`, "term-err");
    }

    termScrollBottom();
  }

  function openTerminal() {
    closeMenus();
    if (!els.termWindow) return;
    const wasHidden = els.termWindow.hidden;
    els.termWindow.hidden = false;
    els.termWindow.classList.remove("minimized");
    TERM.open = true;
    raiseWindow(els.termWindow);
    termUpdateTitle();
    if (wasHidden && !els.termScroll.childElementCount) {
      termWelcome();
    }
    els.termBody.focus();
  }

  function closeTerminal() {
    if (!els.termWindow) return;
    els.termWindow.hidden = true;
    els.termWindow.classList.remove("maximized");
    TERM.open = false;
    termSetLine("");
  }

  let winZ = 80;

  function appWindows() {
    return [els.termWindow, els.epiWindow, els.infoWindow].filter(Boolean);
  }

  function raiseWindow(win) {
    if (!win) return;
    winZ += 1;
    win.style.zIndex = String(winZ);
  }

  function topAppWindow() {
    return appWindows()
      .filter((w) => !w.hidden)
      .sort((a, b) => (parseInt(b.style.zIndex || "80", 10) - parseInt(a.style.zIndex || "80", 10)))[0];
  }

  function toggleWindowMaximize(win, maxBtn) {
    if (!win || win.hidden) return;
    win.classList.toggle("maximized");
    const maxed = win.classList.contains("maximized");
    if (maxBtn) {
      maxBtn.setAttribute("aria-label", maxed ? "Restore" : "Maximize");
      maxBtn.title = maxed ? "Restore" : "Maximize";
    }
  }

  function closeAppWindow(win) {
    if (!win) return;
    if (win === els.termWindow) {
      closeTerminal();
      return;
    }
    win.hidden = true;
    win.classList.remove("maximized");
  }

  function enableWindowChrome(win, header, maxBtn, closeBtn) {
    if (!win || !header) return;

    win.addEventListener("pointerdown", () => raiseWindow(win));

    maxBtn?.addEventListener("click", () => toggleWindowMaximize(win, maxBtn));
    closeBtn?.addEventListener("click", () => closeAppWindow(win));
    header.addEventListener("dblclick", (e) => {
      if (e.target.closest(".term-wc")) return;
      toggleWindowMaximize(win, maxBtn);
    });

    let dragging = false;
    let startX = 0;
    let startY = 0;
    let origLeft = 0;
    let origTop = 0;

    header.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest(".term-wc")) return;
      if (win.classList.contains("maximized")) return;

      const rect = win.getBoundingClientRect();
      win.style.left = rect.left + "px";
      win.style.top = rect.top + "px";
      win.style.transform = "none";
      win.style.right = "auto";

      dragging = true;
      startX = e.clientX;
      startY = e.clientY;
      origLeft = rect.left;
      origTop = rect.top;
      header.setPointerCapture(e.pointerId);
    });

    header.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      let left = origLeft + dx;
      let top = origTop + dy;
      top = Math.max(32, top);
      left = Math.min(Math.max(-rectWidth(win) + 80, left), window.innerWidth - 80);
      win.style.left = left + "px";
      win.style.top = top + "px";
    });

    header.addEventListener("pointerup", () => {
      dragging = false;
    });
    header.addEventListener("pointercancel", () => {
      dragging = false;
    });
  }

  function renderEpiPage() {
    const online = state.network.connected;
    if (els.epiUrl) {
      els.epiUrl.value = online ? "https://firstboot.local/" : "about:offline";
    }
    if (els.epiTitle) {
      els.epiTitle.textContent = online ? "First Boot Linux" : "Offline";
    }
    if (!els.epiPage) return;
    els.epiPage.innerHTML = online
      ? `<div class="epi-start">
          <h1>First Boot Linux</h1>
          <p>Pick a distribution on the desktop. This browser is a preview for first boot only.</p>
        </div>`
      : `<div class="epi-start">
          <h1>You’re offline</h1>
          <p>Connect from the system menu to use the network. This preview has no remote pages.</p>
        </div>`;
  }

  function openEpiphany() {
    closeMenus();
    if (!els.epiWindow) return;
    renderEpiPage();
    els.epiWindow.hidden = false;
    raiseWindow(els.epiWindow);
    applyVolume();
  }

  function infoFields(rows) {
    return rows
      .map(
        ([k, v]) =>
          `<div class="info-field"><div class="info-field-label">${k}</div><div class="info-field-value">${escapeHtml(v).replace(/\n/g, "<br>")}</div></div>`
      )
      .join("");
  }

  function renderSysInfo() {
    if (els.infoHw) {
      els.infoHw.innerHTML = infoFields([
        ["Model", "Micro-Star International Co., Ltd. MS-7D14"],
        ["Memory", "16.0 GiB DDR4-3200"],
        ["Processor", "AMD Ryzen™ 7 5700G with Radeon™"],
        ["Graphics", "AMD Radeon™ RX 7800 XT"],
        ["Graphics 1", "AMD Radeon™ Graphics"],
        ["Display", "1920x1080 in 27\", 100 Hz"],
        ["Disk (/)", "PCIe 3.0 - 456.35 GiB (ext4)"],
        ["Disk (/mnt/)", "SATA 3.0 - 915.82 GiB (ext4)"],
        ["Disk (/mnt/)", "SATA 3.0 - 915.82 GiB (ext4)"],
      ]);
    }
    if (els.infoSw) {
      els.infoSw.innerHTML = infoFields([
        ["Operating System", "First Boot Linux 0.1.1"],
        ["OS Type", "x86_64"],
        ["Windowing System", "Wayland"],
        ["Kernel Version", "Linux 7.1.8-generic"],
        ["Firmware Version", "1.G0"],
      ]);
    }
  }

  function openSysInfo() {
    closeMenus();
    if (!els.infoWindow) return;
    renderSysInfo();
    els.infoWindow.hidden = false;
    raiseWindow(els.infoWindow);
  }

  function rectWidth(el) {
    return el.getBoundingClientRect().width;
  }

  function onTermKeydown(e) {
    if (!TERM.open || els.termWindow.hidden) return;
    const tag = (e.target && e.target.tagName) || "";
    if (
      e.target !== els.termBody &&
      (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable)
    ) {
      return;
    }

    if (e.key === "Escape") {
      if (
        !els.quickSettings.hidden ||
        !els.networkMenu.hidden ||
        !els.powerMenu.hidden ||
        !els.appMenu.hidden ||
        !els.powerModal.hidden
      ) {
        return;
      }
      closeTerminal();
      e.preventDefault();
      return;
    }

    if (e.key === "l" && (e.ctrlKey || e.metaKey)) {
      els.termScroll.innerHTML = "";
      e.preventDefault();
      return;
    }

    if (e.key === "c" && (e.ctrlKey || e.metaKey)) {
      termAppendLine(termPromptHtml() + escapeHtml(TERM.line) + "^C");
      termSetLine("");
      termScrollBottom();
      e.preventDefault();
      return;
    }

    if (e.key === "Enter") {
      const line = TERM.line;
      termSetLine("");
      termRunCommand(line);
      e.preventDefault();
      return;
    }

    if (e.key === "Backspace") {
      if (TERM.line.length) termSetLine(TERM.line.slice(0, -1));
      e.preventDefault();
      return;
    }

    if (e.key === "ArrowUp") {
      if (!TERM.history.length) return;
      if (TERM.histIndex === TERM.history.length) TERM.draft = TERM.line;
      TERM.histIndex = Math.max(0, TERM.histIndex - 1);
      termSetLine(TERM.history[TERM.histIndex] || "");
      e.preventDefault();
      return;
    }

    if (e.key === "ArrowDown") {
      if (TERM.histIndex >= TERM.history.length) return;
      TERM.histIndex = Math.min(TERM.history.length, TERM.histIndex + 1);
      if (TERM.histIndex === TERM.history.length) {
        termSetLine(TERM.draft);
      } else {
        termSetLine(TERM.history[TERM.histIndex] || "");
      }
      e.preventDefault();
      return;
    }

    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      termSetLine(TERM.line + e.key);
      e.preventDefault();
    }
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

  function openAppMenu() {
    const wasOpen = !els.appMenu.hidden;
    closeMenus();
    if (wasOpen) return;
    els.appMenu.hidden = false;
    els.appMenuBtn.setAttribute("aria-expanded", "true");
    els.backdrop.hidden = false;
  }

  function openNetworkMenu() {
    closeMenus();
    els.networkMenu.hidden = false;
    els.systemMenuBtn.setAttribute("aria-expanded", "true");
    els.backdrop.hidden = false;
  }

  function showScreen(name) {
    const showChooser =
      name === "chooser" ||
      name === "catalog" ||
      name === "detail" ||
      name === "install" ||
      name === "done";
    els.screenChooser.hidden = !showChooser;
    els.screenInstall.hidden = name !== "install";
    els.screenDone.hidden = name !== "done";
    document.body.classList.toggle(
      "detail-open",
      name === "detail" || name === "catalog"
    );
    document.body.classList.toggle("install-open", name === "install");
    document.body.classList.toggle("done-open", name === "done");
    if (name === "catalog" || name === "detail") {
      openOverlay(name);
    } else if (els.screenOverlay) {
      els.screenOverlay.hidden = true;
      els.screenOverlay.classList.remove("is-opening");
      if (els.popoverTrack) els.popoverTrack.classList.remove("is-detail");
    }
    if (name === "chooser") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function syncPopoverHeight() {
    const track = els.popoverTrack;
    const stage = els.popoverStage;
    if (!track || !stage) return;
    const panel = track.classList.contains("is-detail")
      ? els.detailPopover
      : els.catalogPopover;
    if (!panel) return;
    stage.style.height = panel.offsetHeight + "px";
  }

  function openOverlay(panel) {
    const overlay = els.screenOverlay;
    const track = els.popoverTrack;
    const stage = els.popoverStage;
    if (!overlay || !track) return;

    const wasOpen = !overlay.hidden;
    const slide =
      wasOpen &&
      ((panel === "detail" && state.detailMode === "catalog") ||
        panel === "catalog");

    overlay.hidden = false;

    if (!slide) {
      track.classList.add("no-slide");
      if (stage) stage.classList.add("no-slide");
      track.classList.toggle("is-detail", panel === "detail");
      overlay.classList.remove("is-opening");
      void overlay.offsetWidth;
      overlay.classList.add("is-opening");
      requestAnimationFrame(() => {
        syncPopoverHeight();
        requestAnimationFrame(() => {
          track.classList.remove("no-slide");
          if (stage) stage.classList.remove("no-slide");
        });
      });
    } else {
      overlay.classList.remove("is-opening");
      const nextPanel =
        panel === "detail" ? els.detailPopover : els.catalogPopover;
      const nextH = nextPanel ? nextPanel.offsetHeight : 0;
      const curH = stage ? stage.getBoundingClientRect().height : 0;
      track.classList.toggle("is-detail", panel === "detail");
      if (nextH >= curH) syncPopoverHeight();
    }

    if (els.catalogPopover) {
      els.catalogPopover.setAttribute(
        "aria-hidden",
        panel === "detail" ? "true" : "false"
      );
    }
    if (els.detailPopover) {
      els.detailPopover.setAttribute(
        "aria-hidden",
        panel === "detail" ? "false" : "true"
      );
    }
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

    if (state.selected && els.screenDetail && !els.screenDetail.hidden) {
      if (state.detailMode === "catalog") renderDeOptions(state.selected);
      else renderRecommendedActions(state.selected);
    }
  }

  function wifiIsActive(ssid) {
    return (
      state.network.connected &&
      state.network.type === "wifi" &&
      state.network.name === ssid
    );
  }

  function setWifiExpanded(ssid) {
    const prev = state.wifiExpanded;
    if (prev && prev !== ssid) delete state.wifiReveal[prev];
    state.wifiExpanded = ssid;
  }

  function toggleWifiExpand(ssid) {
    setWifiExpanded(state.wifiExpanded === ssid ? null : ssid);
    renderWifi();
    if (state.wifiExpanded !== ssid) return;
    const input = els.wifiList.querySelector(".wifi-password");
    if (input) input.focus();
  }

  function buildWifiExpand(net, isActive, saved) {
    const box = document.createElement("div");
    box.className = "wifi-expand";

    if (net.secure && !isActive) {
      const wrap = document.createElement("div");
      wrap.className = "wifi-password-field";

      const revealed = !!state.wifiReveal[net.ssid];
      const input = document.createElement("input");
      input.className = "wifi-password";
      input.type = revealed ? "text" : "password";
      input.dataset.ssid = net.ssid;
      input.placeholder = "Password";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.setAttribute("aria-label", `Password for ${net.ssid}`);
      input.value = state.wifiSecrets[net.ssid] || "";
      input.addEventListener("input", () => {
        state.wifiSecrets[net.ssid] = input.value;
      });
      input.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        connectWifi(net.ssid);
      });

      const unhide = document.createElement("button");
      unhide.type = "button";
      unhide.className = "wifi-unhide";
      unhide.textContent = revealed ? "Hide" : "Unhide";
      unhide.setAttribute("aria-pressed", String(revealed));
      unhide.setAttribute(
        "aria-label",
        revealed ? "Hide password" : "Show password"
      );
      unhide.addEventListener("mousedown", (e) => e.preventDefault());
      unhide.addEventListener("click", () => {
        state.wifiReveal[net.ssid] = !revealed;
        renderWifi();
        const next = els.wifiList.querySelector(
          `.wifi-password[data-ssid="${CSS.escape(net.ssid)}"]`
        );
        if (next) next.focus();
      });

      wrap.appendChild(input);
      wrap.appendChild(unhide);
      box.appendChild(wrap);
    }

    const actions = document.createElement("div");
    actions.className = "wifi-expand-actions";
    if (saved) {
      const forget = document.createElement("button");
      forget.type = "button";
      forget.className = "btn-pill wifi-forget";
      forget.textContent = "Forget";
      forget.addEventListener("click", () => forgetWifi(net.ssid));
      actions.appendChild(forget);
    }
    if (!isActive) {
      const connect = document.createElement("button");
      connect.type = "button";
      connect.className = "btn-pill wifi-connect";
      const busy = state.wifiConnecting === net.ssid;
      connect.textContent = busy ? "Connecting…" : "Connect";
      connect.disabled = busy;
      connect.addEventListener("click", () => connectWifi(net.ssid));
      actions.appendChild(connect);
    }
    if (actions.childNodes.length) box.appendChild(actions);
    return box;
  }

  function renderWifi() {
    const keep = document.activeElement;
    const keepSsid =
      keep && keep.classList && keep.classList.contains("wifi-password")
        ? keep.dataset.ssid
        : "";
    const selStart = keepSsid ? keep.selectionStart : null;
    const selEnd = keepSsid ? keep.selectionEnd : null;

    els.wifiList.innerHTML = "";

    WIFI_NETWORKS.forEach((net) => {
      const li = document.createElement("li");
      li.className = "wifi-row";
      const isActive = wifiIsActive(net.ssid);
      const expanded = state.wifiExpanded === net.ssid;
      const saved = state.wifiSaved.has(net.ssid);
      if (isActive) li.classList.add("active");
      if (expanded) li.classList.add("expanded");

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wifi-item";
      btn.setAttribute("aria-expanded", String(expanded));
      btn.innerHTML = `
        <span class="wifi-item-left">
          <img class="sym" src="assets/status/network-wireless-signal-excellent-symbolic.svg" alt="" draggable="false" />
          <span>${escapeHtml(net.ssid)}</span>
        </span>
        <span class="wifi-item-meta">${isActive ? "Connected" : ""}</span>
      `;
      btn.addEventListener("click", () => toggleWifiExpand(net.ssid));
      li.appendChild(btn);
      if (expanded) li.appendChild(buildWifiExpand(net, isActive, saved));
      els.wifiList.appendChild(li);
    });

    if (!keepSsid) return;
    const input = els.wifiList.querySelector(
      `.wifi-password[data-ssid="${CSS.escape(keepSsid)}"]`
    );
    if (!input) return;
    input.focus();
    if (selStart != null) input.setSelectionRange(selStart, selEnd);
  }

  function outputVolume() {
    return state.muted ? 0 : state.volume;
  }

  function applyVolume() {
    const level = outputVolume();
    const icon =
      level === 0
        ? "assets/status/audio-volume-muted-symbolic.svg"
        : "assets/status/audio-volume-medium-symbolic.svg";
    if (els.qsVolumeIcon) els.qsVolumeIcon.src = icon;
    if (els.volStatusIcon) els.volStatusIcon.src = icon;
    if (els.qsVolume) {
      els.qsVolume.value = String(level);
      els.qsVolume.style.setProperty("--qs-vol", level + "%");
    }
    if (els.qsVolumeMute) {
      const muted = level === 0;
      els.qsVolumeMute.setAttribute("aria-pressed", String(muted));
      els.qsVolumeMute.title = muted ? "Unmute" : "Mute";
      els.qsVolumeMute.setAttribute("aria-label", muted ? "Unmute" : "Mute");
    }
    document.querySelectorAll("audio, video").forEach((el) => {
      el.volume = level / 100;
      el.muted = level === 0;
    });
  }

  function setVolumeFromSlider(raw) {
    const v = Number(raw);
    if (!Number.isFinite(v) || v <= 0) {
      state.muted = true;
    } else {
      state.muted = false;
      state.volume = Math.min(100, v);
    }
    applyVolume();
  }

  function applyBrightness() {
    const level = Math.max(0, Math.min(100, Number(state.brightness) || 0));
    state.brightness = level;
    if (els.qsBrightness) {
      els.qsBrightness.value = String(level);
      els.qsBrightness.style.setProperty("--qs-vol", level + "%");
    }
  }

  function toggleMute() {
    if (outputVolume() === 0) {
      state.muted = false;
      if (state.volume <= 0) state.volume = 70;
    } else {
      state.muted = true;
    }
    applyVolume();
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function connectWifi(ssid) {
    const net = WIFI_NETWORKS.find((n) => n.ssid === ssid);
    if (!net || state.wifiConnecting) return;
    if (wifiIsActive(ssid)) return;
    const secret = (state.wifiSecrets[ssid] || "").trim();
    if (net.secure && !state.wifiSaved.has(ssid) && !secret) {
      showToast("Password required");
      return;
    }
    state.wifiConnecting = ssid;
    els.qsNetSub.textContent = "Connecting…";
    renderWifi();
    setTimeout(() => {
      state.wifiConnecting = null;
      state.wifiSaved.add(ssid);
      setWifiExpanded(null);
      state.network.connected = true;
      state.network.type = "wifi";
      state.network.name = ssid;
      updateNetworkUI();
      showToast(`Connected to ${ssid}`);
    }, 700);
  }

  function forgetWifi(ssid) {
    state.wifiSaved.delete(ssid);
    delete state.wifiSecrets[ssid];
    delete state.wifiReveal[ssid];
    if (wifiIsActive(ssid)) {
      state.network.connected = false;
      state.network.type = null;
      state.network.name = null;
    }
    if (state.wifiExpanded === ssid) setWifiExpanded(null);
    updateNetworkUI();
    showToast(`Forgot ${ssid}`);
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

    const other = document.createElement("button");
    other.type = "button";
    other.className = "distro-card other-option-card";
    other.setAttribute("role", "listitem");
    other.setAttribute("aria-haspopup", "dialog");
    other.innerHTML = `
      <img class="distro-logo logo-dark" src="assets/apps/other-option-dark.png" alt="" draggable="false" />
      <img class="distro-logo logo-light" src="assets/apps/other-option-light.png" alt="" draggable="false" />
      <div class="card-text">
        <h3>Other options</h3>
        <p class="card-desktop">...</p>
        <p class="card-version">&nbsp;</p>
      </div>
    `;
    other.addEventListener("click", openCatalog);
    els.recommendedGrid.appendChild(other);
  }

  function catalogName(d) {
    return d.id === "ms-windows" ? "Microsoft Windows" : d.name;
  }

  function openCatalog() {
    closeMenus();
    renderCatalog();
    showScreen("catalog");
  }

  function closeDetail() {
    showScreen(state.detailMode === "catalog" ? "catalog" : "chooser");
  }

  function renderCatalog() {
    els.catalogList.innerHTML = "";
    const sorted = CATALOG.slice().sort((a, b) =>
      catalogName(a).localeCompare(catalogName(b), undefined, { sensitivity: "base" })
    );
    sorted.forEach((d) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "catalog-row";
      btn.setAttribute("role", "listitem");
      btn.innerHTML = `
        <img class="distro-logo" src="${d.logo}" alt="" draggable="false" />
        <h3>${escapeHtml(catalogName(d))}</h3>
        <span class="meta">${escapeHtml(d.version)}</span>
      `;
      btn.addEventListener("click", () => openDetail(d.id, "catalog"));
      els.catalogList.appendChild(btn);
    });
  }

  function recommendedEdition(d) {
    if (d.desktops && d.desktops.length) return d.desktops[0];
    return { id: "default", name: d.desktop, local: !!d.local };
  }

  function editionKey(d, de) {
    return `${d.id}:${de.id}`;
  }

  function editionDownload(d, de) {
    return state.downloads[editionKey(d, de)] || null;
  }

  function isEditionOnDisk(d, de) {
    return !!(de.local || editionDownload(d, de)?.status === "done");
  }

  function renderDeOptions(d) {
    els.deOptionsList.innerHTML = "";

    if (state.detailMode !== "catalog" || !d.desktops || !d.desktops.length) {
      els.deOptions.hidden = true;
      return;
    }

    els.deOptions.hidden = false;
    const offline = !state.network.connected;
    const needsDownload = d.desktops.some((de) => !isEditionOnDisk(d, de));

    d.desktops.forEach((de) => {
      const row = document.createElement("div");
      const onDisk = isEditionOnDisk(d, de);
      const dl = editionDownload(d, de);
      const downloading = dl?.status === "downloading";

      row.className = "de-option" + (downloading ? " downloading" : "");
      row.setAttribute("role", "listitem");
      row.dataset.edition = editionKey(d, de);

      const sizeBits = [de.size || ""];
      if (onDisk) sizeBits.push("On disk");
      else if (downloading) sizeBits.push(`${dl.label} ${dl.pct}%`);

      const actionLabel = onDisk ? "Install" : "Download";
      const actionDisabled = !onDisk && (offline || downloading);

      row.innerHTML = `
        <span class="de-option-meta">
          <span class="de-option-name">${escapeHtml(de.name)}</span>
          <span class="de-option-size">${escapeHtml(sizeBits.filter(Boolean).join(" · "))}</span>
        </span>
        <button type="button" class="de-option-action${onDisk ? " local" : ""}"${
          actionDisabled ? " disabled" : ""
        }>${actionLabel}</button>
        <div class="de-option-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${
          downloading ? dl.pct : 0
        }" aria-label="Download ${escapeHtml(de.name)}"${downloading ? "" : " hidden"}>
          <div class="de-option-progress-fill" style="width: ${
            downloading ? dl.pct : 0
          }%"></div>
        </div>
      `;

      const actionBtn = row.querySelector(".de-option-action");
      actionBtn.addEventListener("click", () => {
        if (isEditionOnDisk(d, de)) startInstall(de);
        else startDownload(de);
      });

      els.deOptionsList.appendChild(row);
    });

    if (needsDownload && offline) {
      els.detailWarn.hidden = false;
      els.detailWarnText.textContent =
        "Connect to a network to download editions that are not on disk.";
    } else if (els.detailWarnText.textContent.indexOf("download editions") !== -1) {
      els.detailWarn.hidden = true;
    }
  }

  function updateDeOptionProgress(d, de) {
    const dl = editionDownload(d, de);
    const row = els.deOptionsList.querySelector(
      `[data-edition="${editionKey(d, de)}"]`
    );
    if (!row || !dl) return;

    const fill = row.querySelector(".de-option-progress-fill");
    const bar = row.querySelector(".de-option-progress");
    const size = row.querySelector(".de-option-size");
    if (fill) fill.style.width = dl.pct + "%";
    if (bar) {
      bar.hidden = false;
      bar.setAttribute("aria-valuenow", String(dl.pct));
    }
    if (size) size.textContent = `${de.size || ""} · ${dl.label} ${dl.pct}%`.replace(/^ · /, "");
  }

  function setDetailProgress(dl) {
    if (!els.detailProgress) return;
    const downloading = dl?.status === "downloading";
    els.detailProgress.hidden = !downloading;
    if (!downloading) return;
    const pct = dl.pct || 0;
    if (els.detailProgressFill) els.detailProgressFill.style.width = pct + "%";
    els.detailProgress.setAttribute("aria-valuenow", String(pct));
  }

  function renderRecommendedActions(d) {
    const de = recommendedEdition(d);
    const onDisk = isEditionOnDisk(d, de);
    const dl = editionDownload(d, de);
    const downloading = dl?.status === "downloading";
    const offline = !state.network.connected;

    els.detailDesktop.hidden = false;
    els.detailDesktop.textContent = d.desktop || "";
    els.deOptions.hidden = true;
    els.deOptionsList.innerHTML = "";
    els.detailActions.classList.remove("catalog-mode");
    els.installBtn.hidden = false;

    if (onDisk) {
      els.installBtn.textContent = "Install";
      els.installBtn.disabled = false;
      els.detailWarn.hidden = true;
      setDetailProgress(null);
      return;
    }

    els.installBtn.textContent = downloading
      ? `${dl.label} ${dl.pct}%`
      : "Download";
    els.installBtn.disabled = offline || downloading;
    if (offline) {
      els.detailWarn.hidden = false;
      els.detailWarnText.textContent =
        "Connect to a network to download editions that are not on disk.";
    } else {
      els.detailWarn.hidden = true;
    }
    setDetailProgress(dl);
  }

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
    setDetailProgress(null);

    if (state.detailMode === "recommended") {
      renderRecommendedActions(d);
    } else {
      els.detailDesktop.hidden = true;
      els.detailDesktop.textContent = "";
      els.detailActions.classList.add("catalog-mode");
      renderDeOptions(d);
    }

    showScreen("detail");
  }

  function startDownload(de) {
    const d = state.selected;
    if (!d || !de) return;

    if (isEditionOnDisk(d, de)) {
      startInstall(de);
      return;
    }

    if (!state.network.connected) {
      showToast("Connect to a network first");
      openQuickSettings();
      return;
    }

    const key = editionKey(d, de);
    if (state.downloads[key]?.status === "downloading") return;

    const rec = { status: "downloading", pct: 0, label: "Connecting…", timer: null };
    state.downloads[key] = rec;
    if (state.detailMode === "catalog") renderDeOptions(d);
    else renderRecommendedActions(d);

    let i = 0;
    function tick() {
      const cur = state.downloads[key];
      if (!cur || cur.status !== "downloading") return;

      if (i >= STEPS_FETCH.length) {
        if (cur.timer) clearInterval(cur.timer);
        state.downloads[key] = { status: "done", pct: 100, label: "Ready", timer: null };
        if (state.selected === d) {
          if (state.detailMode === "catalog") renderDeOptions(d);
          else renderRecommendedActions(d);
        }
        return;
      }

      const step = STEPS_FETCH[i];
      cur.pct = step.pct;
      cur.label = step.label;
      i += 1;

      if (state.selected === d) {
        if (state.detailMode === "catalog") updateDeOptionProgress(d, de);
        else renderRecommendedActions(d);
      }
    }

    tick();
    rec.timer = setInterval(tick, 450);
  }

  function startInstall(de) {
    const d = state.selected;
    if (!d) return;

    if (state.detailMode === "recommended") {
      de = recommendedEdition(d);
    }

    if (!de) return;

    if (!isEditionOnDisk(d, de)) {
      startDownload(de);
      return;
    }

    state.selectedDesktop = de;
    closeMenus();
    showScreen("install");

    const deLabel = de.name || d.desktop;

    els.installLogo.classList.remove("install-brand-logo");
    els.installLogo.src = d.logo;
    els.installLogo.alt = d.name;
    els.installTitle.textContent = deLabel
      ? `Installing ${d.name} (${deLabel})`
      : `Installing ${d.name}`;
    els.installSubtitle.textContent = "";
    els.progressFill.style.width = "0%";
    els.progressLabel.textContent = "0%";
    els.progressStep.textContent = "";
    els.progressBar.setAttribute("aria-valuenow", "0");

    let i = 0;
    if (state.installTimer) clearInterval(state.installTimer);

    function tick() {
      if (i >= STEPS_LOCAL.length) {
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
      const step = STEPS_LOCAL[i];
      els.progressFill.style.width = step.pct + "%";
      els.progressLabel.textContent = step.pct + "%";
      els.progressStep.textContent = step.label;
      els.installSubtitle.textContent = step.label;
      els.progressBar.setAttribute("aria-valuenow", String(step.pct));
      i += 1;
    }

    tick();
    state.installTimer = setInterval(tick, 500);
  }

  function resetChooser() {
    if (state.installTimer) {
      clearInterval(state.installTimer);
      state.installTimer = null;
    }
    Object.keys(state.downloads).forEach((key) => {
      const rec = state.downloads[key];
      if (rec && rec.timer) clearInterval(rec.timer);
    });
    state.downloads = {};
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

  function requestShopInstall() {
    closeMenus();
    state.pendingPower = "shop-install";
    els.powerModalTitle.textContent = "Install to this device?";
    els.powerModalBody.textContent =
      "This will erase the internal disk and copy First Boot Linux onto it.";
    els.powerModalConfirm.textContent = "Install";
    els.powerModal.hidden = false;
  }

  function startShopInstall() {
    closeMenus();
    showScreen("install");

    els.installLogo.classList.add("install-brand-logo");
    els.installLogo.src = SHOP_LOGO;
    els.installLogo.alt = "First Boot Linux";
    els.installTitle.textContent = "Installing First Boot Linux";
    els.installSubtitle.textContent = "";
    els.progressFill.style.width = "0%";
    els.progressLabel.textContent = "0%";
    els.progressStep.textContent = "";
    els.progressBar.setAttribute("aria-valuenow", "0");

    let i = 0;
    if (state.installTimer) clearInterval(state.installTimer);

    function tick() {
      if (i >= STEPS_SHOP.length) {
        clearInterval(state.installTimer);
        state.installTimer = null;
        setTimeout(() => {
          els.doneMessage.textContent =
            "First Boot Linux is on this computer. Remove the USB stick and restart.";
          showScreen("done");
        }, 350);
        return;
      }
      const step = STEPS_SHOP[i];
      els.progressFill.style.width = step.pct + "%";
      els.progressLabel.textContent = step.pct + "%";
      els.progressStep.textContent = step.label;
      els.installSubtitle.textContent = step.label;
      els.progressBar.setAttribute("aria-valuenow", String(step.pct));
      i += 1;
    }

    tick();
    state.installTimer = setInterval(tick, 500);
  }

  function confirmPower() {
    els.powerModal.hidden = true;
    const action = state.pendingPower;
    state.pendingPower = null;
    if (action === "shop-install") {
      startShopInstall();
      return;
    }
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

    els.qsVolume.addEventListener("input", () => {
      setVolumeFromSlider(els.qsVolume.value);
    });
    els.qsVolumeMute.addEventListener("click", toggleMute);
    if (els.qsBrightness) {
      els.qsBrightness.addEventListener("input", () => {
        state.brightness = Number(els.qsBrightness.value);
        applyBrightness();
      });
    }

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

    els.detailBack.addEventListener("click", closeDetail);
    els.installBtn.addEventListener("click", () => startInstall(null));
    els.rebootBtn.addEventListener("click", resetChooser);

    if (els.screenOverlay) {
      els.screenOverlay.addEventListener("click", (e) => {
        if (e.target !== els.screenOverlay) return;
        if (
          els.popoverTrack &&
          els.popoverTrack.classList.contains("is-detail")
        ) {
          closeDetail();
        } else {
          showScreen("chooser");
        }
      });
    }
    if (els.catalogBack) {
      els.catalogBack.addEventListener("click", () => showScreen("chooser"));
    }
    if (els.popoverTrack) {
      els.popoverTrack.addEventListener("transitionend", (e) => {
        if (e.propertyName !== "transform") return;
        syncPopoverHeight();
      });
    }

    if (els.startFullscreenBtn) {
      els.startFullscreenBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        enterFullscreenPreview();
      });
    }
    if (els.startSkipBtn) {
      els.startSkipBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        dismissStartOverlay();
      });
    }
    if (els.startOverlay) {
      els.startOverlay.addEventListener("click", (e) => e.stopPropagation());
      els.startOverlay.querySelector(".start-overlay-card")?.addEventListener("click", (e) => e.stopPropagation());
    }

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (startOverlayOpen()) return;
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
        if (
          !els.quickSettings.hidden ||
          !els.powerMenu.hidden ||
          !els.appMenu.hidden
        ) {
          closeMenus();
          return;
        }
        const topWin = topAppWindow();
        if (topWin) {
          closeAppWindow(topWin);
          return;
        }
        closeMenus();
        if (els.screenOverlay && !els.screenOverlay.hidden) {
          if (
            els.popoverTrack &&
            els.popoverTrack.classList.contains("is-detail") &&
            state.detailMode === "catalog"
          ) {
            closeDetail();
          } else {
            showScreen("chooser");
          }
          return;
        }
        return;
      }
      onTermKeydown(e);
    });

    els.quickSettings.addEventListener("click", (e) => e.stopPropagation());
    els.networkMenu.addEventListener("click", (e) => e.stopPropagation());
    els.powerMenu.addEventListener("click", (e) => e.stopPropagation());
    els.appMenu.addEventListener("click", (e) => e.stopPropagation());

    els.appMenuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openAppMenu();
    });
    if (els.appMenuInstallDevice) {
      els.appMenuInstallDevice.addEventListener("click", requestShopInstall);
    }
    els.appMenuEpiphany.addEventListener("click", () => {
      if (els.epiWindow && !els.epiWindow.hidden) {
        closeMenus();
        raiseWindow(els.epiWindow);
      } else {
        openEpiphany();
      }
    });
    els.appMenuSysinfo.addEventListener("click", () => {
      if (els.infoWindow && !els.infoWindow.hidden) {
        closeMenus();
        raiseWindow(els.infoWindow);
      } else {
        openSysInfo();
      }
    });
    els.appMenuTerminal.addEventListener("click", () => {
      if (TERM.open && !els.termWindow.hidden) {
        closeMenus();
        raiseWindow(els.termWindow);
        els.termBody.focus();
      } else {
        openTerminal();
      }
    });
    if (els.termBody) {
      els.termBody.addEventListener("click", () => els.termBody.focus());
    }
    enableWindowChrome(els.termWindow, els.termHeaderbar, els.termMax, els.termClose);
    enableWindowChrome(els.epiWindow, els.epiHeaderbar, els.epiMax, els.epiClose);
    enableWindowChrome(els.infoWindow, els.infoHeaderbar, els.infoMax, els.infoClose);
  }

  function init() {
    updateClock();
    setInterval(updateClock, 15000);
    applyTheme();
    renderRecommended();
    renderCatalog();
    updateNetworkUI();
    applyVolume();
    applyBrightness();
    bind();
    applyPreviewQuery();
  }

  function applyPreviewQuery() {
    const q = new URLSearchParams(window.location.search);
    const shop = q.get("shop");
    const menu = q.get("menu");
    if (q.get("theme") === "light") {
      state.darkStyle = false;
      applyTheme();
    }
    if (q.has("skip-start") || menu || shop || q.get("catalog") === "open") {
      dismissStartOverlay();
    }
    if (q.get("catalog") === "open") openCatalog();
    if (menu === "apps") openAppMenu();
    if (menu === "qs") openQuickSettings();
    if (menu === "network") {
      openNetworkMenu();
      const wifi = q.get("wifi");
      if (wifi && WIFI_NETWORKS.some((n) => n.ssid === wifi)) {
        setWifiExpanded(wifi);
        renderWifi();
      }
    }
    if (menu === "terminal") openTerminal();
    if (shop === "confirm") requestShopInstall();
    if (shop === "install") startShopInstall();
    if (shop === "progress") {
      showScreen("install");
      els.installLogo.classList.add("install-brand-logo");
      els.installLogo.src = SHOP_LOGO;
      els.installLogo.alt = "First Boot Linux";
      els.installTitle.textContent = "Installing First Boot Linux";
      els.installSubtitle.textContent = "Copying First Boot…";
      els.progressFill.style.width = "58%";
      els.progressLabel.textContent = "58%";
      els.progressStep.textContent = "Copying First Boot…";
      els.progressBar.setAttribute("aria-valuenow", "58");
    }
    if (shop === "done") {
      els.doneMessage.textContent =
        "First Boot Linux is on this computer. Remove the USB stick and restart.";
      showScreen("done");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
