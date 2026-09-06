# Payload contracts

Two files on every shop USB (`payload/`). One file in this repo for the creator. Paths and labels are defined in [`USB-LAYOUT.md`](../USB-LAYOUT.md).

| File | Where | Who writes it | Purpose |
| --- | --- | --- | --- |
| `retailer.conf` | USB `payload/` | Creator, per shop | Name, support, wallpaper paths |
| `catalog.json` | USB `payload/` | Creator, per shop | What this shop offers (self-contained) |
| `official-catalog.json` | This repo / creator | Us | Menu of distros we support |
| `custom-driver.schema.json` | This repo / pack zip | Distro team | `manifest.json` inside a retailer `.zip` |

The live chooser reads only `/run/payload/retailer.conf` and `/run/payload/catalog.json`. It does not need `official-catalog.json`. That file is how the creator knows what may be ticked (recommended, ISO on disk), left as Other options (download), or hidden until an install driver exists. A well-formed `install` id that this seed does not know still loads: the chooser shows an **Unknown** card with `unknown.png` instead of emptying recommended.

First Boot’s own version is **not** in `retailer.conf`. In the live session it is `/etc/os-release` inside the squashfs. On the `fbl` partition the file is `fbl/.disk/info`.

`docs/app.js` is UI exploration. These files are the contract.

## `retailer.conf`

UTF-8, `key = value`, `#` comments. Paths are relative to the payload root. No absolute paths, no `..`.

| Key | Required | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Must be `1` |
| `name` | yes | Shop name (chooser footer “Configured by”) |
| `support` | yes | Contact line (chooser footer “Support”) |
| `wallpaper_dark` | yes | Dark-style image, under `wallpapers/` |
| `wallpaper_light` | yes | Light-style image, under `wallpapers/` |
| `language` | no | Shop default language id (`en-us`, `en-gb`, `en-za`, `af`, …). Missing means `en-us`. `en` is an alias of `en-us`. Only languages the chooser ships. This is also the language (locale / language pack) passed into Ubuntu, flavor, Mint, and Fedora installs. |
| `keyboard` | no | Shop keyboard layout, xkb id (`us`, `gb`, `de`, `za`, …). Missing means `us`. Independent of `language`. Used on the live kiosk and in the distro installers. |
| `timezone` | no | Shop default UTC offset (`UTC+0000`, `UTC+0200`, `UTC+0530`, …). 30-minute steps from `UTC-1200` to `UTC+1400`. Missing means the live session keeps the seed UTC until the customer sets the clock. |

See [`examples/retailer.conf`](examples/retailer.conf).

## `official-catalog.json`

Creator menu. Schema: [`official-catalog.schema.json`](official-catalog.schema.json). Current list: [`official-catalog.json`](official-catalog.json).

Each distro:

| Field | Meaning |
| --- | --- |
| `id` | Stable kebab-case id (logo key, chooser id) |
| `name`, `version`, `tagline`, `description` | UI copy |
| `family` | Distro family (`ubuntu`, `mint`, `fedora`, `debian`, `suse`, `windows`, `bsd`, `other`) |
| `redistributable` | We may copy an official ISO onto `payload/images/`. False when the license forbids redistribution (MS Windows). Independent of `install`. |
| `install` | Install driver id, or `null` if we cannot install it yet. `windows` and `freebsd` are reserved; no driver yet. |
| `can_stage` | Creator may copy an edition ISO onto `payload/images/` |
| `suggested_default` | Reserved. Creator does not pre-tick anything. |
| `secure_boot` | Installer loads with firmware Secure Boot on |
| `editions[]` | One ISO per desktop (or flavor) |

Each edition:

| Field | Meaning |
| --- | --- |
| `id` | `gnome`, `cinnamon`, `plasma`, … |
| `name` | Display name |
| `default` | Exactly one `true` per distro. Chooser recommended cards are each local edition; default is the fallback card when none are local |
| `install` | Optional. Overrides the distro install driver for this edition (Mint MATE is `mint-223-mate`) |
| `filename` | Basename written to `payload/images/` |
| `url` | Direct ISO URL, or `null` until pinned |
| `sha256` | 64 lowercase hex, or `null` until pinned |
| `size_bytes` | ISO size, or `null` until pinned |

Rules:

- `can_stage` is true only when `install` is set **and** `redistributable` is true. Do not stage an ISO we cannot install or may not copy.
- `redistributable: false` forces `can_stage: false`. The shop may still put that distro in `recommended` as download-only once `install` is set. The creator must never write its ISO to `images/`.
- `suggested_default` requires `install`. The creator GUI does not pre-tick; shops tick desktops under each distro.
- Official catalog is only distros with a working **FBL-native** install driver. Current rows: Ubuntu GNOME (`ubuntu-2604-gnome`) and Linux Mint Cinnamon / MATE / Xfce (`mint-223-cinnamon`, `mint-223-mate`, `mint-223-xfce`). Flavors and Fedora stay out until native files exist. The old Subiquity / Calamares / Ubiquity / Anaconda Python drivers are gone. Older sticks may still say `ubuntu-autoinstall` / `ubuntu-2604` / `ubuntu-calamares-2604` / `mint` / `mint-223` / `fedora-kickstart` / `fedora-44-plasma` (reserved ids, no baked-in driver). `windows` and `freebsd` stay reserved in the schema. The mockup in `docs/` is the longer future list. Driver Python lives in `chooser/firstboot/osinstall/`.
- Pin `url`, `sha256`, and `size_bytes` before the creator downloads that edition.
- Shop-private distros (Pop!_OS, TUXEDO OS, a store’s own image) are **not** official-catalog rows. They are a `.zip` pack the creator copies to `payload/custom/<id>/`. See [Retailer driver packs](#retailer-driver-packs).

## `catalog.json` (on the USB)

Self-contained shop catalog. Schema: [`catalog.schema.json`](catalog.schema.json). Example: [`examples/catalog.json`](examples/catalog.json).

```json
{
  "schema_version": 1,
  "recommended": [ /* grid; editions may be local or download-only */ ],
  "catalog": [ /* extras; no id also in recommended */ ]
}
```

The chooser grid is `recommended`, one card per **local** edition (ticked desktop). The same distro id can appear on more than one card (Mint MATE and Mint Xfce). A recommended distro with no local edition (download-only, e.g. MS Windows) is still one card. **Other options** (the last card) opens `recommended` followed by `catalog`, sorted by name, one row per distro (do not duplicate ids in the JSON). `ms-windows` stays **MS Windows** on the card and **Microsoft Windows** in that list.

Each distro copies display fields from the official catalog (`id`, `name`, `version`, `tagline`, `description`, `family`, `install`, `secure_boot`) plus `editions`. Do not copy official edition objects through: they have `filename` and nullable hashes, which this schema rejects (`additionalProperties: false`).

`secure_boot` is optional on the stick (missing means true, for older payloads). The live chooser reads firmware Secure Boot. When it is on, Other options omits catalog rows with `secure_boot: false`. A **recommended** row without Secure Boot still appears, with a warning; Install is refused. Shop packs default to false unless the manifest sets `secure_boot: true`.

Official edition → shop edition:

- keep `id`, `name`, `default`
- copy `install` when it differs from the distro driver
- `file` = `images/` + official `filename` when `local` is true
- drop `filename`
- pin `sha256` and `size_bytes` (never null on the stick)
- set `local` and, if not local, `url`

Each edition on the stick:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Same kebab-case id as the official edition (`gnome`, `cinnamon`, …) |
| `name` | yes | Display name |
| `default` | yes | Featured edition (exactly one `true` per distro) |
| `install` | no | Overrides the distro `install` driver for this edition |
| `local` | yes | ISO is on this payload |
| `file` | if `local` | Path like `images/ubuntu-26.04-desktop-amd64.iso` |
| `url` | if not `local` | Direct ISO URL |
| `sha256` | yes | 64 lowercase hex |
| `size_bytes` | yes | ISO size in bytes |

The creator sets `local: true` and `file` only after the ISO is copied and verified. Recommended entries may be entirely download-only when the official row is not redistributable. Never set `local: true` on a non-redistributable edition.

Official logos are bundled in the chooser by `id` (`assets/distros/<id>.png` in the mockup). Shop packs put `logo.png` at `payload/custom/<id>/logo.png` (and a copy at `payload/logos/<id>.png`). The chooser looks there first.

## Integrity

`payload/checksums.sha256` is separate: hashes of `retailer.conf`, `catalog.json`, wallpapers, and every file in `images/`. That file is partition integrity. `catalog.json` `sha256` fields are ISO content hashes used before install.

## Validation (creator, before write)

1. `retailer.conf` has the required keys; wallpapers exist. `language`, `keyboard`, and `timezone` are optional.
2. `catalog.json` matches `catalog.schema.json`.
3. Every distro `id` / edition exists in `official-catalog.json`, **or** it is a shop pack under `custom/<install>/` whose `install` equals the pack id and is not a reserved official id.
4. Every `local` edition file exists under `images/` and matches `sha256`.
5. No `local` edition unless official `can_stage`, `redistributable`, and `install` are set, **or** the row is a shop pack with a staged ISO. Recommended may list a non-redistributable official distro with every edition `local: false`. Custom editions have no download URL; only ticked desktops are written.
6. No `..` or absolute paths.

## Retailer driver packs

A shop that maintains its own OS ships a `.zip` (repeatable) instead of a pull request. Schema: [`custom-driver.schema.json`](custom-driver.schema.json). Example: [`examples/custom-driver.json`](examples/custom-driver.json). Source for the Pop!_OS test pack: [`../examples/retailer-distros/pop-os/`](../examples/retailer-distros/pop-os/).

Zip layout (files at the root, or one top-level folder):

```text
manifest.json
driver.py          # same API as chooser/firstboot/osinstall/_template.py
logo.png
locale/af.po       # optional; also locale/en-gb.po, locale/en-za.po, …
```

`editions[]` is one ISO per desktop (Pop!_OS GNOME and COSMIC are two editions, one driver). Optional `sha256` / `size_bytes` pin the ISO; the creator rejects a file that does not match. ISOs may sit in the zip, next to the zip (same `filename`), in `~/.cache/firstboot/images/`, or be chosen in the USB Creator. They are written to `payload/images/`; they do not stay under `custom/`.

`id` = `install` = folder `payload/custom/<id>/` = `DRIVER.id` in `driver.py`. Must not collide with official catalog ids or baked-in driver ids (`ubuntu`, `kubuntu`, `lubuntu`, `ubuntu-budgie`, `ubuntu-mate`, `xubuntu`, `linux-mint`, `fedora`, `ubuntu-2604-gnome`, `ubuntu-2604`, `ubuntu-calamares-2604`, `mint-223-cinnamon`, `mint-223-mate`, `mint-223-xfce`, `mint-223`, `fedora-44-plasma`, aliases, `windows`, `freebsd`).

Optional `locale/<lang>.po` files (GNU gettext, same format as `po/af.po`) translate that pack’s **tagline and description**. `msgid` is the English string in `manifest.json`. Distro and desktop names stay untranslated. Compose copies them to `payload/custom/<id>/locale/`. The live chooser and the USB Creator GUI merge those entries **after** First Boot’s catalogues and never override chrome (`Install`, `Network`, `Back`, …). English (US) is the source; do not ship `en.po` / `en-us.po`. `en-gb.po` and `en-za.po` are spelling catalogues for that pack’s blurb.

The live chooser loads `custom/<id>/driver.py` with `importlib` when `catalog.json` `install` is not a baked-in module. That code runs as root at customer install. The pack is not from First Boot Linux.

Shop `catalog.json` `install` is an open kebab-case id (not a closed enum). Official-catalog.json stays a closed menu.
