"""Locale + keyboard for customer OS installs. Not inferred from each other."""

from __future__ import annotations

import os
from dataclasses import dataclass

from firstboot.i18n import DEFAULT_LANGUAGE, resolve_language
from firstboot.keyboard import DEFAULT_KEYBOARD, resolve_keyboard


@dataclass(frozen=True)
class InstallLocale:
    language: str = DEFAULT_LANGUAGE
    glibc: str = "en_US.UTF-8"
    keyboard: str = DEFAULT_KEYBOARD
    langpack: str = "en"
    di_language: str = "en"
    di_country: str = "US"
    di_name: str = "English"


# Shipped chooser ids → installer locale. Keyboard is passed in separately.
_BY_LANGUAGE: dict[str, dict[str, str]] = {
    "en-us": {
        "glibc": "en_US.UTF-8",
        "langpack": "en",
        "di_language": "en",
        "di_country": "US",
        "di_name": "English",
    },
    "en-gb": {
        "glibc": "en_GB.UTF-8",
        "langpack": "en",
        "di_language": "en",
        "di_country": "GB",
        "di_name": "English",
    },
    "en-za": {
        "glibc": "en_ZA.UTF-8",
        "langpack": "en",
        "di_language": "en",
        "di_country": "ZA",
        "di_name": "English",
    },
    "af": {
        "glibc": "af_ZA.UTF-8",
        "langpack": "af",
        "di_language": "af",
        "di_country": "ZA",
        "di_name": "Afrikaans",
    },
}


def resolve_install_locale(
    lang_id: str | None = None, keyboard: str | None = None
) -> InstallLocale:
    lid = resolve_language(lang_id)
    kbd = resolve_keyboard(keyboard)
    meta = _BY_LANGUAGE.get(lid) or _BY_LANGUAGE[DEFAULT_LANGUAGE]
    return InstallLocale(language=lid, keyboard=kbd, **meta)


def payload_install_locale(root: str | None = None) -> InstallLocale:
    from firstboot.i18n import load_language
    from firstboot.keyboard import load_keyboard
    from firstboot.payload import PayloadError, parse_retailer_conf

    path = (
        root
        or os.environ.get("FIRSTBOOT_PAYLOAD")
        or os.environ.get("FBL_PAYLOAD")
        or "/run/payload"
    )
    retailer_lang = None
    retailer_kbd = None
    conf = os.path.join(path, "retailer.conf")
    if os.path.isfile(conf):
        try:
            with open(conf, encoding="utf-8") as fh:
                raw = parse_retailer_conf(fh.read())
            retailer_lang = raw.get("language")
            retailer_kbd = raw.get("keyboard")
        except (OSError, PayloadError):
            pass
    return resolve_install_locale(
        load_language(path, retailer_lang),
        load_keyboard(path, retailer_kbd),
    )
