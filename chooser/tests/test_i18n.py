#!/usr/bin/env python3
"""Language catalogs, search, and payload persistence — no GTK."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE,
    LANGUAGE_FILE,
    Language,
    _,
    apply_language,
    current_language,
    format_status,
    has_catalog,
    language_matches,
    load_catalog,
    load_language,
    merge_pack_locales,
    load_language_index,
    normalize_id,
    parse_po,
    persist_language,
    resolve_language,
    supported_ids,
    supported_languages,
    write_language_file,
)


def _pot_msgids(path: str) -> list[str]:
    ids: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line.startswith("msgid "):
                continue
            token = line[6:].strip()
            if token in {"", '""'}:
                continue
            if token.startswith('"') and token.endswith('"'):
                token = token[1:-1]
            ids.append(token)
    return ids


class IdTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_id("EN"), "en-us")
        self.assertEqual(normalize_id("af_ZA"), "af")
        self.assertEqual(normalize_id("pt-br"), "pt-br")
        self.assertEqual(normalize_id("en-US"), "en-us")
        self.assertEqual(normalize_id("en-GB"), "en-gb")
        self.assertEqual(normalize_id("en"), "en-us")
        self.assertIsNone(normalize_id("English"))
        self.assertIsNone(normalize_id("../af"))

    def test_resolve_unknown_is_english_us(self) -> None:
        self.assertEqual(resolve_language("de"), DEFAULT_LANGUAGE)
        self.assertEqual(resolve_language(None), DEFAULT_LANGUAGE)
        self.assertEqual(resolve_language("af"), "af")
        self.assertEqual(resolve_language("en"), "en-us")
        self.assertEqual(resolve_language("en-gb"), "en-gb")
        self.assertEqual(resolve_language("en-za"), "en-za")
        self.assertEqual(resolve_language("en_ZA"), "en-za")
        self.assertEqual(DEFAULT_LANGUAGE, "en-us")


class IndexTests(unittest.TestCase):
    def test_shipped_english_and_afrikaans(self) -> None:
        ids = [lang.id for lang in load_language_index()]
        self.assertIn("en-us", ids)
        self.assertIn("en-gb", ids)
        self.assertIn("af", ids)
        self.assertIn("en-za", ids)
        self.assertEqual(set(ids), {"en-us", "en-gb", "en-za", "af"})
        self.assertNotIn("en", ids)

    def test_supported_matches_catalogs(self) -> None:
        langs = supported_languages()
        ids = [lang.id for lang in langs]
        self.assertIn("en-us", ids)
        self.assertIn("en-gb", ids)
        self.assertIn("en-za", ids)
        self.assertIn("af", ids)
        self.assertTrue(has_catalog("en-us"))
        self.assertTrue(has_catalog("en-gb"))
        self.assertTrue(has_catalog("en-za"))
        self.assertTrue(has_catalog("en"))
        self.assertTrue(has_catalog("af"))
        af = next(lang for lang in langs if lang.id == "af")
        self.assertEqual(af.name, "Afrikaans")
        us = next(lang for lang in langs if lang.id == "en-us")
        self.assertEqual(us.name, "English (US)")
        gb = next(lang for lang in langs if lang.id == "en-gb")
        self.assertEqual(gb.name, "English (UK)")
        za = next(lang for lang in langs if lang.id == "en-za")
        self.assertEqual(za.name, "English (South Africa)")
        self.assertEqual(supported_ids(), frozenset({"en-us", "en-gb", "en-za", "af"}))

    def test_not_the_mockup_list(self) -> None:
        ids = supported_ids()
        self.assertNotIn("zu", ids)
        self.assertNotIn("zh-cn", ids)
        self.assertNotIn("de", ids)


class SearchTests(unittest.TestCase):
    def test_native_and_english(self) -> None:
        af = Language("af", "Afrikaans", "Afrikaans")
        de = Language("de", "Deutsch", "German")
        self.assertTrue(language_matches(af, ""))
        self.assertTrue(language_matches(af, "afrik"))
        self.assertTrue(language_matches(de, "german"))
        self.assertTrue(language_matches(de, "DEUT"))
        self.assertFalse(language_matches(de, "french"))
        self.assertTrue(language_matches(de, "de ger"))
        self.assertFalse(language_matches(de, "de french"))


class PoTests(unittest.TestCase):
    def setUp(self) -> None:
        apply_language("en")

    def tearDown(self) -> None:
        apply_language("en")

    def test_parse_and_apply_afrikaans(self) -> None:
        self.assertEqual(_("Network"), "Network")
        apply_language("af")
        self.assertEqual(current_language(), "af")
        self.assertEqual(_("Network"), "Netwerk")
        self.assertEqual(_("Language"), "Taal")
        self.assertEqual(_("Other options"), "Ander opsies")
        self.assertEqual(_("Unknown"), "Onbekend")
        self.assertEqual(_("Configured by {name}").format(name="Shop"), "Opgestel deur Shop")
        apply_language("en-gb")
        self.assertEqual(current_language(), "en-gb")
        self.assertEqual(_("Network"), "Network")
        self.assertEqual(_("Maximize"), "Maximise")
        self.assertEqual(_("No Wi-Fi adapter"), "No Wi-Fi adaptor")
        self.assertEqual(
            _("The catalog checksum is not valid."),
            "The catalogue checksum is not valid.",
        )
        apply_language("en-za")
        self.assertEqual(current_language(), "en-za")
        self.assertEqual(_("Maximize"), "Maximise")
        apply_language("en-us")
        self.assertEqual(_("Maximize"), "Maximize")
        self.assertEqual(_("Network"), "Network")
        self.assertEqual(_("Unknown"), "Unknown")

    def test_geen_has_no_trailing_nie(self) -> None:
        apply_language("af")
        from firstboot.i18n import load_catalog

        catalog = load_catalog("af")
        for src, dst in catalog.items():
            words = dst.casefold().replace(".", "").split()
            if "geen" in words:
                self.assertNotEqual(
                    words[-1],
                    "nie",
                    f"geen must not take a trailing nie: {src!r} → {dst!r}",
                )

    def test_install_progress(self) -> None:
        apply_language("af")
        self.assertEqual(_("Preparing the disk…"), "Berei die skyf voor…")
        self.assertEqual(_("Copying First Boot…"), "Kopieer First Boot…")
        self.assertEqual(_("Checking the image…"), "Kontroleer die beeld…")
        self.assertEqual(_("Installing the system"), "Installeer die stelsel")
        self.assertEqual(_("Checking the install"), "Kontroleer die installasie")
        self.assertEqual(
            _("Installing {name}").format(name="Ubuntu (GNOME)"),
            "Installeer Ubuntu (GNOME)",
        )
        self.assertEqual(
            _("Install {name}?").format(name="Linux Mint (Cinnamon)"),
            "Installeer Linux Mint (Cinnamon)?",
        )
        self.assertEqual(
            format_status("Restarting to install {name}…\tFedora"),
            "Herbegin om Fedora te installeer…",
        )
        self.assertEqual(
            _("No internal disk to install to."),
            "Geen interne skyf om op te installeer",
        )
        apply_language("en-us")
        self.assertEqual(_("Preparing the disk…"), "Preparing the disk…")

    def test_distro_description(self) -> None:
        apply_language("af")
        self.assertEqual(_("Popular and well-supported"), "Gewild en goed ondersteun")
        self.assertIn("Afgewerkte werkskerm", _("A polished desktop with excellent hardware support and a large software library. A safe default for most laptops."))
        self.assertEqual(_("Ubuntu with KDE Plasma"), "Ubuntu met KDE Plasma")
        self.assertEqual(_("Very lightweight"), "Baie liggewig")
        apply_language("en-us")
        self.assertEqual(_("Popular and well-supported"), "Popular and well-supported")

    def test_creator_strings(self) -> None:
        apply_language("af")
        self.assertEqual(_("USB creator"), "USB-skepper")
        self.assertEqual(_("Shop details"), "Winkelbesonderhede")
        self.assertEqual(_("Continue"), "Gaan voort")
        self.assertEqual(_("Default language"), "Standaardtaal")
        apply_language("en-us")
        self.assertEqual(_("USB creator"), "USB creator")
        apply_language("en-gb")
        self.assertEqual(_("USB creator"), "USB creator")
        self.assertEqual(_("Shop details"), "Shop details")
        self.assertEqual(_("Continue"), "Continue")
        apply_language("en-za")
        self.assertEqual(_("USB creator"), "USB creator")
        self.assertEqual(_("Keyboard layout"), "Keyboard layout")

    def test_english_variants_cover_pot(self) -> None:
        repo = os.path.abspath(os.path.join(CHOOSER_DIR, ".."))
        pot = os.path.join(repo, "po", "firstboot.pot")
        ids = _pot_msgids(pot)
        self.assertIn("USB creator", ids)
        self.assertIn("Shop details", ids)
        gb = load_catalog("en-gb")
        za = load_catalog("en-za")
        missing_gb = [msgid for msgid in ids if msgid not in gb]
        missing_za = [msgid for msgid in ids if msgid not in za]
        self.assertEqual(missing_gb, [])
        self.assertEqual(missing_za, [])
        self.assertEqual(gb["USB creator"], "USB creator")
        self.assertEqual(za["USB creator"], "USB creator")
        self.assertEqual(gb["The catalog checksum is not valid."], "The catalogue checksum is not valid.")
        self.assertEqual(za["The catalog checksum is not valid."], "The catalogue checksum is not valid.")

    def test_parse_escapes(self) -> None:
        catalog = parse_po(
            'msgid "Say \\"hi\\"\\n"\nmsgstr "Sê \\"hallo\\"\\n"\n'
        )
        self.assertEqual(catalog['Say "hi"\n'], 'Sê "hallo"\n')


class PackLocaleTests(unittest.TestCase):
    def test_merge_fills_missing_and_skips_chrome(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-pack-po-")
        try:
            loc = os.path.join(root, "custom", "pop-os", "locale")
            os.makedirs(loc)
            with open(os.path.join(loc, "af.po"), "w", encoding="utf-8") as fh:
                fh.write(
                    'msgid "Back"\n'
                    'msgstr "MOENIE"\n'
                    "\n"
                    'msgid "COSMIC and GNOME from System76"\n'
                    'msgstr "COSMIC en GNOME van System76"\n'
                )
            apply_language("af", payload_root=root)
            self.assertEqual(_("Back"), "Terug")
            self.assertEqual(
                _("COSMIC and GNOME from System76"),
                "COSMIC en GNOME van System76",
            )
            merged = merge_pack_locales(load_catalog("af"), "af", root)
            self.assertEqual(merged["Back"], "Terug")
            self.assertEqual(
                merged["COSMIC and GNOME from System76"],
                "COSMIC en GNOME van System76",
            )
        finally:
            apply_language("en-us")
            shutil.rmtree(root, ignore_errors=True)

    def test_english_us_does_not_merge(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-pack-po-en-")
        try:
            loc = os.path.join(root, "custom", "pop-os", "locale")
            os.makedirs(loc)
            with open(os.path.join(loc, "af.po"), "w", encoding="utf-8") as fh:
                fh.write(
                    'msgid "COSMIC and GNOME from System76"\n'
                    'msgstr "COSMIC en GNOME van System76"\n'
                )
            apply_language("en-us", payload_root=root)
            self.assertEqual(
                _("COSMIC and GNOME from System76"),
                "COSMIC and GNOME from System76",
            )
        finally:
            apply_language("en-us")
            shutil.rmtree(root, ignore_errors=True)


class LayoutTests(unittest.TestCase):
    def test_seed_and_po_files(self) -> None:
        repo = os.path.abspath(os.path.join(CHOOSER_DIR, ".."))
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "af.po")))
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "en-gb.po")))
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "en-za.po")))
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "firstboot.pot")))
        with open(os.path.join(repo, "po", "firstboot.pot"), encoding="utf-8") as fh:
            pot = fh.read()
        self.assertIn('msgid "USB creator"', pot)
        self.assertIn('msgid "Shop details"', pot)
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "languages.json")))
        self.assertTrue(
            os.path.isfile(os.path.join(CHOOSER_DIR, "firstboot-set-language"))
        )
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "keyboards.json")))
        sudoers = os.path.join(
            repo, "seed", "overlay", "etc", "sudoers.d", "firstboot-language"
        )
        with open(sudoers, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("/usr/libexec/firstboot/set-language", text)


class PersistTests(unittest.TestCase):
    def test_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fbl-lang-") as tmp:
            self.assertEqual(load_language(tmp), "en-us")
            write_language_file(tmp, "af")
            path = os.path.join(tmp, LANGUAGE_FILE)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "af")
            self.assertEqual(load_language(tmp), "af")
            self.assertEqual(load_language(tmp, "en-us"), "af")
            os.remove(path)
            self.assertEqual(load_language(tmp, "af"), "af")
            self.assertTrue(persist_language(tmp, "en"))
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "en-us")
            self.assertEqual(load_language(tmp, "af"), "en-us")
            self.assertTrue(persist_language(tmp, "en-gb"))
            self.assertEqual(load_language(tmp), "en-gb")

    def test_unsupported_file_falls_back(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fbl-lang-") as tmp:
            path = os.path.join(tmp, LANGUAGE_FILE)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("de\n")
            self.assertEqual(load_language(tmp, "en"), "en-us")
            self.assertEqual(load_language(tmp, "en-us"), "en-us")


if __name__ == "__main__":
    unittest.main()
