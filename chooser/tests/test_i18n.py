#!/usr/bin/env python3
"""Language catalogs, search, and payload persistence — no GTK."""

from __future__ import annotations

import os
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
    load_language,
    load_language_index,
    normalize_id,
    parse_po,
    persist_language,
    resolve_language,
    supported_ids,
    supported_languages,
    write_language_file,
)


class IdTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_id("EN"), "en")
        self.assertEqual(normalize_id("af_ZA"), "af")
        self.assertEqual(normalize_id("pt-br"), "pt-br")
        self.assertEqual(normalize_id("en-US"), "en")
        self.assertIsNone(normalize_id("English"))
        self.assertIsNone(normalize_id("../af"))

    def test_resolve_unknown_is_english(self) -> None:
        self.assertEqual(resolve_language("de"), DEFAULT_LANGUAGE)
        self.assertEqual(resolve_language(None), DEFAULT_LANGUAGE)
        self.assertEqual(resolve_language("af"), "af")


class IndexTests(unittest.TestCase):
    def test_shipped_english_and_afrikaans(self) -> None:
        ids = [lang.id for lang in load_language_index()]
        self.assertIn("en", ids)
        self.assertIn("af", ids)
        self.assertEqual(set(ids), {"en", "af"})

    def test_supported_matches_catalogs(self) -> None:
        langs = supported_languages()
        ids = [lang.id for lang in langs]
        self.assertIn("en", ids)
        self.assertIn("af", ids)
        self.assertTrue(has_catalog("en"))
        self.assertTrue(has_catalog("af"))
        af = next(lang for lang in langs if lang.id == "af")
        self.assertEqual(af.name, "Afrikaans")
        self.assertEqual(supported_ids(), frozenset({"en", "af"}))

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
        self.assertEqual(_("Configured by {name}").format(name="Shop"), "Opgestel deur Shop")
        apply_language("en")
        self.assertEqual(_("Network"), "Network")

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
        apply_language("en")
        self.assertEqual(_("Preparing the disk…"), "Preparing the disk…")

    def test_distro_description(self) -> None:
        apply_language("af")
        self.assertEqual(_("Popular and well-supported"), "Gewild en goed ondersteun")
        self.assertIn("Afgewerkte werkskerm", _("A polished desktop with excellent hardware support and a large software library. A safe default for most laptops."))
        apply_language("en")
        self.assertEqual(_("Popular and well-supported"), "Popular and well-supported")

    def test_parse_escapes(self) -> None:
        catalog = parse_po(
            'msgid "Say \\"hi\\"\\n"\nmsgstr "Sê \\"hallo\\"\\n"\n'
        )
        self.assertEqual(catalog['Say "hi"\n'], 'Sê "hallo"\n')


class LayoutTests(unittest.TestCase):
    def test_seed_and_po_files(self) -> None:
        repo = os.path.abspath(os.path.join(CHOOSER_DIR, ".."))
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "af.po")))
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "firstboot.pot")))
        self.assertTrue(os.path.isfile(os.path.join(repo, "po", "languages.json")))
        self.assertTrue(
            os.path.isfile(os.path.join(CHOOSER_DIR, "firstboot-set-language"))
        )
        sudoers = os.path.join(
            repo, "seed", "overlay", "etc", "sudoers.d", "firstboot-language"
        )
        with open(sudoers, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("/usr/libexec/firstboot/set-language", text)


class PersistTests(unittest.TestCase):
    def test_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fbl-lang-") as tmp:
            self.assertEqual(load_language(tmp), "en")
            write_language_file(tmp, "af")
            path = os.path.join(tmp, LANGUAGE_FILE)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "af")
            self.assertEqual(load_language(tmp), "af")
            self.assertEqual(load_language(tmp, "en"), "af")
            os.remove(path)
            self.assertEqual(load_language(tmp, "af"), "af")
            self.assertTrue(persist_language(tmp, "en"))
            self.assertEqual(load_language(tmp, "af"), "en")

    def test_unsupported_file_falls_back(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fbl-lang-") as tmp:
            path = os.path.join(tmp, LANGUAGE_FILE)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("de\n")
            self.assertEqual(load_language(tmp, "en"), "en")


if __name__ == "__main__":
    unittest.main()
