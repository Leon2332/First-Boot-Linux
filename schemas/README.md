# Payload contracts

Two files on every shop USB (`payload/`). One file in this repo for the creator. Paths and labels are defined in [`USB-LAYOUT.md`](../USB-LAYOUT.md).

| File | Where | Who writes it | Purpose |
| --- | --- | --- | --- |
| `retailer.conf` | USB `payload/` | Creator, per shop | Name, support, wallpaper paths |
| `catalog.json` | USB `payload/` | Creator, per shop | What this shop offers (self-contained) |
| `official-catalog.json` | This repo / creator | Us | Menu of distros we support |

The live chooser reads only `/run/payload/retailer.conf` and `/run/payload/catalog.json`. It does not need `official-catalog.json`. That file is how the creator knows what may be ticked (recommended, ISO on disk), left as Other options (download), or hidden until an install driver exists.

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
| `editions[]` | One ISO per desktop (or flavor) |

Each edition:

| Field | Meaning |
| --- | --- |
| `id` | `gnome`, `cinnamon`, `plasma`, … |
| `name` | Display name |
| `default` | Exactly one `true` per distro. Chooser recommended cards are each local edition; default is the fallback card when none are local |
| `filename` | Basename written to `payload/images/` |
| `url` | Direct ISO URL, or `null` until pinned |
| `sha256` | 64 lowercase hex, or `null` until pinned |
| `size_bytes` | ISO size, or `null` until pinned |

Rules:

- `can_stage` is true only when `install` is set **and** `redistributable` is true. Do not stage an ISO we cannot install or may not copy.
- `redistributable: false` forces `can_stage: false`. The shop may still put that distro in `recommended` as download-only once `install` is set. The creator must never write its ISO to `images/`.
- `suggested_default` requires `install`. The creator GUI does not pre-tick; shops tick desktops under each distro.
- Official catalog is only distros with a working install driver: Ubuntu (`ubuntu-2604`), Linux Mint (`mint-223`, Cinnamon / MATE / Xfce editions), Fedora Plasma (`fedora-44-plasma`). Older sticks may still say `ubuntu-autoinstall` / `mint` / `fedora-kickstart` (aliases). `windows` and `freebsd` stay reserved in the schema. The mockup in `docs/` is the longer future list. Driver Python lives in `chooser/firstboot/osinstall/`.
- Pin `url`, `sha256`, and `size_bytes` before the creator downloads that edition.

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

Each distro copies display fields from the official catalog (`id`, `name`, `version`, `tagline`, `description`, `family`, `install`) plus `editions`. Do not copy official edition objects through: they have `filename` and nullable hashes, which this schema rejects (`additionalProperties: false`).

Official edition → shop edition:

- keep `id`, `name`, `default`
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
| `local` | yes | ISO is on this payload |
| `file` | if `local` | Path like `images/ubuntu-26.04-desktop-amd64.iso` |
| `url` | if not `local` | Direct ISO URL |
| `sha256` | yes | 64 lowercase hex |
| `size_bytes` | yes | ISO size in bytes |

The creator sets `local: true` and `file` only after the ISO is copied and verified. Recommended entries may be entirely download-only when the official row is not redistributable. Never set `local: true` on a non-redistributable edition.

Logos are bundled in the chooser by `id` (`assets/distros/<id>.png` in the mockup). Not payload files.

## Integrity

`payload/checksums.sha256` is separate: hashes of `retailer.conf`, `catalog.json`, wallpapers, and every file in `images/`. That file is partition integrity. `catalog.json` `sha256` fields are ISO content hashes used before install.

## Validation (creator, before write)

1. `retailer.conf` has the five keys; wallpapers exist.
2. `catalog.json` matches `catalog.schema.json`.
3. Every distro `id` / edition exists in `official-catalog.json`.
4. Every `local` edition file exists under `images/` and matches `sha256`.
5. No `local` edition unless official `can_stage`, `redistributable`, and `install` are set. Recommended may list a non-redistributable distro with every edition `local: false`.
6. No `..` or absolute paths.
