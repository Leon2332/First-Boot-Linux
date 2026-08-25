"""GTK CSS aimed at docs/styles.css (dark / light)."""

from __future__ import annotations

CSS = """
window.firstboot {
  background-color: #0e1014;
  color: #eef1f6;
  font-family: Cantarell, "Inter", "Segoe UI", sans-serif;
}

window.firstboot.light {
  background-color: #f0f2f5;
  color: #1c1c1c;
}

window.firstboot-panel,
window.firstboot-panel.background,
window.firstboot-panel.light,
window.firstboot-panel.light.background {
  background-color: #1c1c1c;
}

window.firstboot-panel popover,
window.firstboot-panel popover.background,
window.firstboot-panel popover contents,
window.firstboot-panel popover > contents,
window.firstboot-panel .shell-popover,
window.firstboot-panel .shell-popover contents,
window.firstboot-panel .shell-popover > contents {
  background-color: transparent;
  background-image: none;
  border: none;
  box-shadow: none;
  padding: 0;
  min-width: 0;
  min-height: 0;
}

window.firstboot button {
  box-shadow: none;
  outline: none;
}

.wallpaper {
  background-color: #0e1014;
}

/* ===== GNOME top bar — always dark ===== */

.top-bar {
  min-height: 32px;
  background-color: #1c1c1c;
  color: #f6f5f4;
  padding: 0 8px;
}

.clock {
  font-size: 13px;
  font-weight: 500;
  color: #f6f5f4;
  padding: 0 12px;
}

.panel-btn {
  min-height: 24px;
  min-width: 24px;
  padding: 2px 10px;
  border-radius: 999px;
  background: transparent;
  border: none;
  color: #f6f5f4;
}

.panel-btn:hover,
.panel-btn.open {
  background-color: rgba(255, 255, 255, 0.12);
}

.panel-icons {
  padding: 0 2px;
}

/* ===== Floating shell menus ===== */

.shell-panel {
  background-color: #242424;
  color: #f6f5f4;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 24px;
  padding: 16px;
  min-width: 340px;
}

window.firstboot.light .shell-panel {
  background-color: #ffffff;
  color: #1c1c1c;
  border-color: rgba(0, 0, 0, 0.14);
}

.shell-panel.power-menu,
.shell-panel.app-menu {
  border-radius: 18px;
  padding: 8px;
  min-width: 220px;
}

.shell-panel.app-menu {
  min-width: 240px;
}

.qs-toolbar {
  padding: 0 0 2px;
}

.qs-round {
  min-width: 40px;
  min-height: 40px;
  padding: 0;
  border-radius: 999px;
  background-color: rgba(255, 255, 255, 0.10);
  border: none;
}

.qs-round:hover {
  background-color: rgba(255, 255, 255, 0.14);
}

window.firstboot.light .qs-round {
  background-color: rgba(0, 0, 0, 0.06);
}

window.firstboot.light .qs-round:hover {
  background-color: rgba(0, 0, 0, 0.10);
}

button.qs-toggle {
  min-height: 52px;
  min-width: 0;
  padding: 6px 12px;
  border-radius: 999px;
  background-color: rgba(255, 255, 255, 0.10);
  border: none;
  color: #f6f5f4;
}

button.qs-toggle:hover {
  background-color: rgba(255, 255, 255, 0.14);
}

button.qs-toggle.active {
  background-color: #3584e4;
  color: #ffffff;
}

window.firstboot.light button.qs-toggle {
  background-color: rgba(0, 0, 0, 0.06);
  color: #1c1c1c;
}

window.firstboot.light button.qs-toggle:hover {
  background-color: rgba(0, 0, 0, 0.10);
}

window.firstboot.light button.qs-toggle.active {
  background-color: #3584e4;
  color: #ffffff;
}

.qs-toggle-label {
  font-size: 13px;
  font-weight: 600;
  color: inherit;
}

.qs-toggle-sub {
  font-size: 11px;
  font-weight: 500;
  opacity: 0.9;
  color: inherit;
}

.qs-slider-icon {
  min-width: 36px;
  min-height: 36px;
  padding: 0;
  border-radius: 999px;
  background: transparent;
  border: none;
}

.qs-slider-icon:hover {
  background-color: rgba(255, 255, 255, 0.10);
}

window.firstboot.light .qs-slider-icon:hover {
  background-color: rgba(0, 0, 0, 0.06);
}

scale.qs-slider {
  min-width: 220px;
  padding: 8px 6px;
}

scale.qs-slider trough {
  min-height: 4px;
  border-radius: 999px;
  background-color: rgba(255, 255, 255, 0.10);
}

window.firstboot.light scale.qs-slider trough {
  background-color: rgba(0, 0, 0, 0.08);
}

scale.qs-slider highlight {
  min-height: 4px;
  border-radius: 999px;
  background-color: #3584e4;
}

scale.qs-slider slider {
  min-width: 16px;
  min-height: 16px;
  margin: -6px 0;
  border-radius: 999px;
  background-color: #f6f5f4;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
}

window.firstboot.light scale.qs-slider slider {
  background-color: #ffffff;
}

.menu-header {
  padding: 4px 4px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 10px;
}

window.firstboot.light .menu-header {
  border-bottom-color: rgba(0, 0, 0, 0.08);
}

.menu-header-title {
  font-size: 14px;
  font-weight: 600;
}

.menu-back {
  min-width: 32px;
  min-height: 32px;
  padding: 0;
  border-radius: 999px;
  background-color: rgba(255, 255, 255, 0.10);
  border: none;
}

.menu-back:hover {
  background-color: rgba(255, 255, 255, 0.14);
}



window.firstboot.light .menu-back {
  background-color: rgba(0, 0, 0, 0.06);
}

.net-section {
  font-size: 11px;
  font-weight: 600;
  color: rgba(246, 245, 244, 0.75);
  padding: 8px 4px 4px;
}

window.firstboot.light .net-section {
  color: rgba(28, 28, 28, 0.7);
}

.net-row {
  padding: 10px 12px;
  border-radius: 14px;
  background-color: rgba(255, 255, 255, 0.10);
}

window.firstboot.light .net-row {
  background-color: rgba(0, 0, 0, 0.06);
}

.net-name {
  font-size: 13px;
  font-weight: 600;
}

.net-detail {
  font-size: 12px;
  color: rgba(246, 245, 244, 0.75);
}

window.firstboot.light .net-detail {
  color: rgba(28, 28, 28, 0.7);
}

.btn-pill {
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background-color: rgba(255, 255, 255, 0.10);
  border: none;
}

.btn-pill:hover {
  background-color: rgba(255, 255, 255, 0.16);
}

window.firstboot.light .btn-pill {
  background-color: rgba(0, 0, 0, 0.06);
}

.wifi-scroll {
  min-height: 0;
}

.wifi-row {
  border-radius: 12px;
}

.wifi-row.expanded {
  background-color: rgba(255, 255, 255, 0.10);
}

.wifi-row.active {
  background-color: rgba(53, 132, 228, 0.25);
}

window.firstboot.light .wifi-row.expanded {
  background-color: rgba(0, 0, 0, 0.06);
}

.wifi-item {
  padding: 10px 12px;
  border-radius: 12px;
  background: transparent;
  border: none;
}

.wifi-row:not(.expanded):not(.active) .wifi-item:hover {
  background-color: rgba(255, 255, 255, 0.10);
}

window.firstboot.light .wifi-row:not(.expanded):not(.active) .wifi-item:hover {
  background-color: rgba(0, 0, 0, 0.06);
}

.wifi-ssid {
  font-size: 13px;
}

.wifi-meta {
  font-size: 12px;
  opacity: 0.7;
}

.wifi-expand {
  padding: 0 12px 12px;
}

.wifi-password-field {
  min-height: 36px;
}

entry.wifi-password {
  min-height: 36px;
  padding-left: 12px;
  padding-right: 76px;
  border-radius: 10px;
  background-color: rgba(0, 0, 0, 0.28);
  color: #f6f5f4;
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: none;
  outline: none;
}

entry.wifi-password:focus {
  border-color: #3584e4;
}

window.firstboot.light entry.wifi-password {
  background-color: #ffffff;
  color: #1c1c1c;
  border-color: rgba(0, 0, 0, 0.14);
}

button.wifi-unhide {
  min-height: 28px;
  min-width: 0;
  padding: 0 10px;
  margin: 4px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  background: transparent;
  border: none;
  color: rgba(246, 245, 244, 0.75);
}

button.wifi-unhide:hover {
  background-color: rgba(255, 255, 255, 0.14);
  color: #f6f5f4;
}

window.firstboot.light button.wifi-unhide {
  color: rgba(28, 28, 28, 0.7);
}

window.firstboot.light button.wifi-unhide:hover {
  background-color: rgba(0, 0, 0, 0.08);
  color: #1c1c1c;
}

.wifi-expand-actions {
  padding: 0;
}

button.wifi-connect {
  background-color: #3584e4;
  color: #ffffff;
}

button.wifi-connect:hover {
  background-color: #62a0ea;
}

.wifi-row.active button.btn-pill {
  background-color: rgba(255, 255, 255, 0.16);
  color: #ffffff;
}

.wifi-row.active button.btn-pill:hover {
  background-color: rgba(255, 255, 255, 0.24);
}

.wifi-row.active button.wifi-connect {
  background-color: #3584e4;
}

.wifi-row.active button.wifi-connect:hover {
  background-color: #62a0ea;
}

.app-menu-sep {
  min-height: 1px;
  margin: 6px 8px;
  background-color: rgba(255, 255, 255, 0.12);
}

window.firstboot.light .app-menu-sep {
  background-color: rgba(0, 0, 0, 0.14);
}

.app-running-dot {
  min-width: 8px;
  min-height: 8px;
  border-radius: 999px;
  background-color: #3584e4;
}

.app-menu-item-label {
  font-size: 14px;
  font-weight: 500;
}

.app-menu-item-sub {
  font-size: 11px;
  font-weight: 400;
  color: rgba(246, 245, 244, 0.42);
}

window.firstboot.light .app-menu-item-sub {
  color: rgba(28, 28, 28, 0.4);
}

.app-menu-item, .power-menu-item {
  padding: 10px 12px;
  border-radius: 12px;
  background: transparent;
  border: none;
  font-size: 14px;
  font-weight: 500;
}

.app-menu-item:hover, .power-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.10);
}

window.firstboot.light .app-menu-item:hover,
window.firstboot.light .power-menu-item:hover {
  background-color: rgba(0, 0, 0, 0.06);
}

.power-menu-header {
  padding: 10px 12px 8px;
  font-size: 13px;
  font-weight: 600;
  color: rgba(246, 245, 244, 0.75);
}

window.firstboot.light .power-menu-header {
  color: rgba(28, 28, 28, 0.7);
}

/* ===== Chooser content ===== */

.content {
  padding: 48px 24px 72px;
}

.brand-footer {
  font-size: 12px;
  font-weight: 400;
  line-height: 1.4;
  color: rgba(154, 163, 178, 0.7);
}

window.firstboot.light .brand-footer {
  color: rgba(94, 103, 114, 0.75);
}

.distro-card {
  padding: 22px 12px 18px;
  border-radius: 16px;
  background-color: rgba(18, 20, 26, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.18);
}

.distro-card:hover {
  background-color: rgba(28, 32, 40, 0.86);
  border-color: rgba(255, 255, 255, 0.16);
}

window.firstboot.light .distro-card {
  background-color: rgba(255, 255, 255, 0.78);
  border-color: rgba(0, 0, 0, 0.08);
}

window.firstboot.light .distro-card:hover {
  background-color: rgba(255, 255, 255, 0.92);
}

.card-name {
  font-size: 14px;
  font-weight: 600;
  margin-top: 10px;
  color: #eef1f6;
}

window.firstboot.light .card-name {
  color: #1c1c1c;
}

.card-desktop, .card-version {
  font-size: 12px;
  font-weight: 500;
  color: #9aa3b2;
}

window.firstboot.light .card-desktop,
window.firstboot.light .card-version {
  color: #5e6772;
}

.other-option-card .card-name {
  color: #9aa3b2;
}

window.firstboot.light .other-option-card .card-name {
  color: #5e6772;
}

.catalog-title {
  font-size: 16px;
  font-weight: 600;
  color: #eef1f6;
  margin-bottom: 4px;
}

window.firstboot.light .catalog-title {
  color: #1c1c1c;
}

entry.catalog-search {
  min-height: 36px;
  margin: 2px 0 8px;
  padding-left: 8px;
  padding-right: 8px;
  border-radius: 10px;
  background-color: rgba(0, 0, 0, 0.28);
  color: #eef1f6;
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: none;
  outline: none;
}

entry.catalog-search:focus-within,
entry.catalog-search:focus {
  border-color: #3584e4;
}

window.firstboot.light entry.catalog-search {
  background-color: rgba(0, 0, 0, 0.04);
  color: #1c1c1c;
  border-color: rgba(0, 0, 0, 0.14);
}

.catalog-empty {
  font-size: 14px;
  color: #9aa3b2;
  padding: 8px 2px 4px;
}

window.firstboot.light .catalog-empty {
  color: #5e6772;
}

scrolledwindow.catalog-scroll {
  background: transparent;
  border: none;
  box-shadow: none;
}

listview.catalog-list {
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 0;
}

listview.catalog-list > row {
  padding: 0;
  margin: 0 0 6px 0;
  min-height: 0;
  background: transparent;
  border: none;
  box-shadow: none;
  outline: none;
}

listview.catalog-list > row:hover,
listview.catalog-list > row:selected,
listview.catalog-list > row:active,
listview.catalog-list > row:focus {
  background: transparent;
  outline: none;
  box-shadow: none;
}

.catalog-row {
  min-height: 60px;
  padding: 10px 14px;
  border-radius: 12px;
  background-color: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.10);
}

.catalog-row:hover {
  background-color: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.16);
}

window.firstboot.light .catalog-row {
  background-color: rgba(0, 0, 0, 0.03);
  border-color: rgba(0, 0, 0, 0.08);
}

window.firstboot.light .catalog-row:hover {
  background-color: rgba(0, 0, 0, 0.055);
}

.row-name {
  font-size: 15px;
  font-weight: 600;
  color: #eef1f6;
}

window.firstboot.light .row-name {
  color: #1c1c1c;
}

.row-meta {
  font-size: 12px;
  color: #9aa3b2;
}

window.firstboot.light .row-meta {
  color: #5e6772;
}

.dimmer {
  background-color: transparent;
}

.detail-card {
  background-color: rgba(36, 36, 36, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  padding: 28px;
  min-width: 420px;
}

window.firstboot.light .detail-card {
  background-color: rgba(255, 255, 255, 0.96);
  border-color: rgba(0, 0, 0, 0.08);
}

.back-link {
  color: #9aa3b2;
  background: transparent;
  padding: 4px 0;
  margin-bottom: 8px;
  border: none;
}

window.firstboot.light .back-link {
  color: #5e6772;
}

.detail-title {
  font-size: 26px;
  font-weight: 700;
}

window.firstboot.light .detail-title {
  color: #1c1c1c;
}

.detail-desktop {
  font-size: 14px;
  font-weight: 500;
  color: #9aa3b2;
}

.detail-version, .detail-tagline, .detail-desc {
  font-size: 14px;
  color: #9aa3b2;
}

.detail-desc {
  color: #eef1f6;
  margin-top: 10px;
}

window.firstboot.light .detail-desktop,
window.firstboot.light .detail-version,
window.firstboot.light .detail-tagline,
window.firstboot.light .de-label {
  color: #5e6772;
}

window.firstboot.light .detail-desc {
  color: #1c1c1c;
}

.de-label {
  font-size: 12px;
  font-weight: 600;
  color: #9aa3b2;
  margin-top: 14px;
  margin-bottom: 6px;
}

.de-row {
  padding: 8px 10px;
  border-radius: 10px;
  background-color: rgba(255, 255, 255, 0.04);
}

.btn-primary {
  background-color: #3584e4;
  color: #ffffff;
  border-radius: 999px;
  padding: 10px 26px;
  font-weight: 600;
  border: none;
}

.btn-primary:hover {
  background-color: #62a0ea;
}

.btn-danger {
  background-color: #e01b24;
  color: #ffffff;
  border-radius: 999px;
  padding: 8px 16px;
  border: none;
}

.install-panel, .done-panel {
  background-color: rgba(36, 36, 36, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  padding: 28px 28px 24px;
  min-width: 360px;
}

window.firstboot.light .install-panel,
window.firstboot.light .done-panel {
  background-color: rgba(255, 255, 255, 0.96);
  border-color: rgba(0, 0, 0, 0.08);
}

.install-title, .done-title {
  font-size: 22px;
  font-weight: 700;
}

window.firstboot.light .install-title,
window.firstboot.light .done-title {
  color: #1c1c1c;
}

.install-sub, .done-msg {
  font-size: 14px;
  color: #9aa3b2;
}

window.firstboot.light .install-sub,
window.firstboot.light .done-msg {
  color: #5e6772;
}

.progress-meta {
  font-size: 12px;
  font-weight: 500;
  color: #9aa3b2;
}

window.firstboot.light .progress-meta {
  color: #5e6772;
}

progressbar.shop-progress trough {
  min-height: 8px;
  border-radius: 999px;
  background-color: rgba(255, 255, 255, 0.10);
}

window.firstboot.light progressbar.shop-progress trough {
  background-color: rgba(0, 0, 0, 0.08);
}

progressbar.shop-progress progress {
  min-height: 8px;
  border-radius: 999px;
  background-image: linear-gradient(90deg, #3584e4, #57e389);
}

.done-check {
  min-width: 64px;
  min-height: 64px;
  border-radius: 999px;
  background-color: rgba(87, 227, 137, 0.14);
  color: #57e389;
  font-size: 28px;
  font-weight: 700;
}

.empty-note, .error-note {
  font-size: 14px;
  color: #9aa3b2;
  padding: 12px 16px;
}

.net-empty {
  font-size: 13px;
  color: rgba(246, 245, 244, 0.75);
  padding: 8px 12px;
}

window.firstboot.light .net-empty {
  color: rgba(28, 28, 28, 0.7);
}

/* ===== In-kiosk terminal ===== */

.term-window {
  background-color: #242424;
  color: #e8e6e3;
  border: 1px solid #3d3d3d;
  border-radius: 12px;
  min-width: 480px;
  min-height: 280px;
}

.term-window.maximized {
  border-radius: 0;
  border: none;
}

.term-headerbar {
  min-height: 42px;
  padding: 0 8px 0 12px;
  background-color: #303030;
  border-bottom: 1px solid #3d3d3d;
}

window.firstboot.light .term-headerbar {
  background-color: #ebebeb;
}

.term-title {
  font-size: 13px;
  font-weight: 600;
  color: #f6f5f4;
}

window.firstboot.light .term-title {
  color: #1c1c1c;
}

button.term-wc {
  min-width: 28px;
  min-height: 28px;
  padding: 0;
  border-radius: 999px;
  background: transparent;
  border: none;
}

button.term-wc:hover {
  background-color: rgba(255, 255, 255, 0.10);
}

window.firstboot.light button.term-wc:hover {
  background-color: rgba(0, 0, 0, 0.08);
}

button.term-close:hover {
  background-color: #e01b24;
}

.term-max-mark {
  min-width: 10px;
  min-height: 10px;
  border: 1.5px solid rgba(246, 245, 244, 0.85);
  border-radius: 2px;
}

window.firstboot.light .term-max-mark {
  border-color: rgba(28, 28, 28, 0.75);
}

.term-window.maximized .term-max-mark {
  min-width: 8px;
  min-height: 8px;
}

.term-missing {
  font-size: 14px;
  color: #c0bfbc;
  padding: 24px;
  background-color: #1e1e1e;
}

.info-window {
  background-color: #242424;
  color: #eef1f6;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  min-width: 640px;
}

window.firstboot.light .info-window {
  background-color: #ffffff;
  color: #1c1c1c;
  border-color: rgba(0, 0, 0, 0.14);
}

.info-window.maximized {
  border-radius: 0;
  border: none;
  min-width: 0;
  min-height: 0;
}

.info-body {
  padding: 8px 20px 20px;
}

.info-heading {
  font-size: 15px;
  font-weight: 700;
  padding: 8px 0 8px;
}

.info-field {
  padding: 6px 0;
}

.info-field-label {
  font-size: 12px;
  opacity: 0.65;
}

.info-field-value {
  font-size: 14px;
  font-weight: 500;
}

picture.info-sw-brand {
  margin: 0 0 8px;
}

.epi-window {
  background-color: #242424;
  color: #eef1f6;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  min-width: 480px;
  min-height: 280px;
}

window.firstboot.light .epi-window {
  background-color: #ffffff;
  color: #1c1c1c;
  border-color: rgba(0, 0, 0, 0.14);
}

.epi-window.maximized,
.epi-window.toplevel {
  border-radius: 0;
  min-width: 0;
  min-height: 0;
}

.epi-window.maximized {
  border: none;
}

.epi-toolbar {
  padding: 8px 12px;
  background-color: #303030;
  border-bottom: 1px solid #3d3d3d;
}

window.firstboot.light .epi-toolbar {
  background-color: #ebebeb;
  border-bottom-color: rgba(0, 0, 0, 0.12);
}

entry.epi-url {
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  background-color: rgba(255, 255, 255, 0.08);
  color: #eef1f6;
  border: none;
  box-shadow: none;
  outline: none;
  font-size: 13px;
}

window.firstboot.light entry.epi-url {
  background-color: rgba(0, 0, 0, 0.06);
  color: #1c1c1c;
}
""".encode("utf-8")

# Standalone System details: layout only. Adwaita owns window/headerbar colors.
SYSINFO_CSS = """
.info-body {
  padding: 8px 20px 20px;
}

.info-heading {
  font-size: 15px;
  font-weight: 700;
  padding: 8px 0 8px;
}

.info-field {
  padding: 6px 0;
}

.info-field-label {
  font-size: 12px;
  opacity: 0.65;
}

.info-field-value {
  font-size: 14px;
  font-weight: 500;
}

picture.info-sw-brand {
  margin: 0 0 8px;
}
""".encode("utf-8")
