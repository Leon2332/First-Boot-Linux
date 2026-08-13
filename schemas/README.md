# Payload contracts

Two files on every shop USB (`payload/`). One file in this repo for the creator. Paths and labels are defined in [`USB-LAYOUT.md`](../USB-LAYOUT.md).

| File | Where | Who writes it | Purpose |
| --- | --- | --- | --- |
| `retailer.conf` | USB `payload/` | Creator, per shop | Name, support, wallpaper paths |
| `catalog.json` | USB `payload/` | Creator, per shop | What this shop offers (self-contained) |
| `official-catalog.json` | This repo / creator | Us | Menu of distros we support |

The live chooser reads only `/run/payload/retailer.conf` and `/run/payload/catalog.json`. It does not need `official-catalog.json`. That file is how the creator knows what may be ticked, staged, or offered as a download.

First Boot’s own version is **not** in `retailer.conf`. It lives on the `fbl` partition (`/etc/os-release` or `fbl/.disk/info`).

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
| `family` | Distro family (`ubuntu`, `mint`, `fedora`, `debian`, `suse`, `other`) |
| `install` | Install driver id, or `null` if we cannot install it yet |
| `can_stage` | Creator may copy an edition ISO onto `payload/images/` |
| `suggested_default` | Pre-tick in the creator GUI |
| `editions[]` | One ISO per desktop (or flavor) |

Each edition:

| Field | Meaning |
| --- | --- |
| `id` | `gnome`, `cinnamon`, `plasma`, … |
| `name` | Display name |
| `default` | Featured on the recommended card (exactly one `true` per distro) |
| `filename` | Basename written to `payload/images/` |
| `url` | Direct ISO URL, or `null` until pinned |
| `sha256` | 64 lowercase hex, or `null` until pinned |
| `size_bytes` | ISO size, or `null` until pinned |

Rules:

- `can_stage` is true only when `install` is set. Do not stage an ISO we cannot install.
- `suggested_default` is true only when `can_stage` is true.
- v1 **install** is Ubuntu (`ubuntu-autoinstall`) then Linux Mint (`mint`). Other entries are reserved ids for the GUI; the creator must not offer them as on-disk or download until `install` is set.
- Pin `url`, `sha256`, and `size_bytes` before the creator ships. Example / unpinned values stay `null`.

## `catalog.json` (on the USB)

Self-contained shop catalog. Schema: [`catalog.schema.json`](catalog.schema.json). Example: [`examples/catalog.json`](examples/catalog.json).

```json
{
  "schema_version": 1,
  "recommended": [ /* grid; at least one edition local */ ],
  "catalog": [ /* download-only extras; no id also in recommended */ ]
}
```

The chooser grid is `recommended`. The “other distros” list is `recommended` followed by `catalog` (do not duplicate ids in the JSON).

Each distro copies display fields from the official catalog (`id`, `name`, `version`, `tagline`, `description`, `family`, `install`) plus `editions`.

Each edition on the stick:

| Field | Meaning |
| --- | --- |
| `local` | ISO is on this payload |
| `file` | Required if `local`. Path like `images/ubuntu-26.04-desktop-amd64.iso` |
| `url` | Required if not `local` |
| `sha256` | Always required (64 lowercase hex) |
| `size_bytes` | Always required |

The creator sets `local: true` and `file` only after the ISO is copied and verified. Recommended entries must have at least one local default edition.

Logos are bundled in the chooser by `id` (`assets/distros/<id>.png` in the mockup). Not payload files.

## Integrity

`payload/checksums.sha256` is separate: hashes of `retailer.conf`, `catalog.json`, wallpapers, and every file in `images/`. That file is partition integrity. `catalog.json` `sha256` fields are ISO content hashes used before install.

## Validation (creator, before write)

1. `retailer.conf` has the five keys; wallpapers exist.
2. `catalog.json` matches `catalog.schema.json`.
3. Every distro `id` / edition exists in `official-catalog.json`.
4. Every `local` edition file exists under `images/` and matches `sha256`.
5. No `local` / recommended edition unless official `can_stage` and `install` are set.
6. No `..` or absolute paths.
