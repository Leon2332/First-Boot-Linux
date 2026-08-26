#!/usr/bin/env python3
"""Browser helpers — no GTK window required."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.browser import (  # noqa: E402
    BROWSER_BIN,
    DEFAULT_SEARCH_ENGINE,
    HELPER_ENV,
    SEARCH_ENGINES,
    START_PAGE_PATH,
    START_PAGE_URI,
    START_TITLE,
    WEBKIT_API,
    WEBKIT_SAFE_ENV,
    browser_command,
    browser_log_path,
    drop_process_caps,
    is_start_uri,
    launch_env,
    normalize_url,
    search_engine_providers_variant,
    start_html,
    url_bar_text,
    webkit_available,
    write_start_page,
)
from firstboot.assets import find_search_icon  # noqa: E402
from firstboot.shell import APP_ITEMS, APP_TOASTS  # noqa: E402


class UrlTests(unittest.TestCase):
    def test_empty_is_start(self) -> None:
        self.assertIsNone(normalize_url(""))
        self.assertIsNone(normalize_url("   "))
        self.assertIsNone(normalize_url("about:blank"))
        self.assertTrue(is_start_uri(None))
        self.assertTrue(is_start_uri("about:blank"))
        self.assertEqual(url_bar_text("about:blank"), "")
        self.assertEqual(url_bar_text(""), "")

    def test_keeps_scheme(self) -> None:
        self.assertEqual(
            normalize_url("https://example.com/a"),
            "https://example.com/a",
        )
        self.assertEqual(normalize_url("http://127.0.0.1:8765"), "http://127.0.0.1:8765")
        self.assertEqual(normalize_url("about:start"), None)

    def test_adds_https(self) -> None:
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(
            normalize_url("  x.ai/cli/install.sh  "),
            "https://x.ai/cli/install.sh",
        )

    def test_url_bar_passthrough(self) -> None:
        self.assertEqual(url_bar_text("https://x.ai/"), "https://x.ai/")


class StartPageTests(unittest.TestCase):
    def test_start_copy(self) -> None:
        html = start_html()
        self.assertIn("<title>First Boot Linux</title>", html)
        self.assertIn("Search or type an address.", html)
        self.assertNotIn("<h1", html)
        self.assertNotIn("Ecosia", html)
        self.assertNotIn("Baidu", html)
        self.assertNotIn("preview for first boot only", html)
        self.assertEqual(START_TITLE, "First Boot Linux")
        names = [engine.name for engine in SEARCH_ENGINES]
        homes = [engine.home for engine in SEARCH_ENGINES]
        searches = [engine.search for engine in SEARCH_ENGINES]
        self.assertEqual(names, ["Google", "Brave", "DuckDuckGo"])
        self.assertEqual(DEFAULT_SEARCH_ENGINE, "Brave")
        self.assertEqual(
            searches,
            [
                "https://www.google.com/search?q=%s",
                "https://search.brave.com/search?q=%s",
                "https://duckduckgo.com/search?q=%s",
            ],
        )
        for engine in SEARCH_ENGINES:
            self.assertIn(engine.name, html)
            self.assertIn(engine.home, html)
            self.assertIsNotNone(find_search_icon(engine.icon))
        self.assertIn("data:image/png;base64,", html)
        self.assertEqual(len(homes), 3)
        self.assertEqual(START_PAGE_PATH, "/usr/share/firstboot/start.html")
        self.assertEqual(START_PAGE_URI, "file:///usr/share/firstboot/start.html")

    def test_search_engine_providers_variant(self) -> None:
        text = search_engine_providers_variant()
        self.assertIn("'Google'", text)
        self.assertIn("'Brave'", text)
        self.assertIn("'DuckDuckGo'", text)
        self.assertIn("https://www.google.com/search?q=%s", text)
        self.assertIn("https://search.brave.com/search?q=%s", text)
        self.assertIn("https://duckduckgo.com/search?q=%s", text)
        self.assertNotIn("Bing", text)
        self.assertNotIn("Ecosia", text)
        self.assertNotIn("Baidu", text)

    def test_write_start_page(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "start.html")
            write_start_page(path)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("Search or type an address.", body)
            self.assertIn("Google", body)
            self.assertIn("Brave", body)
            self.assertIn("DuckDuckGo", body)


class WebKitHelperTests(unittest.TestCase):
    def test_api(self) -> None:
        self.assertEqual(WEBKIT_API, "6.0")

    def test_available_is_bool(self) -> None:
        self.assertIsInstance(webkit_available(), bool)

    def test_dmabuf_not_forced_off(self) -> None:
        from firstboot.browser import WEBKIT_UNSET_ENV, apply_webkit_env

        keys = tuple(WEBKIT_SAFE_ENV) + tuple(WEBKIT_UNSET_ENV)
        prev = {key: os.environ.pop(key, None) for key in keys}
        os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"
        os.environ["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1"
        try:
            apply_webkit_env()
            for key, val in WEBKIT_SAFE_ENV.items():
                self.assertEqual(os.environ.get(key), val)
            for key in WEBKIT_UNSET_ENV:
                self.assertIsNone(os.environ.get(key))
        finally:
            for key, old in prev.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old

    def test_ephemeral_when_available(self) -> None:
        if not webkit_available():
            self.skipTest("webkit missing")
        from firstboot.browser import new_ephemeral_session

        session = new_ephemeral_session()
        self.assertTrue(session.is_ephemeral())
        self.assertFalse(session.get_persistent_credential_storage_enabled())


class LaunchTests(unittest.TestCase):
    def test_command_in_tree(self) -> None:
        cmd = browser_command()
        self.assertIsNotNone(cmd)
        assert cmd is not None
        self.assertTrue(os.path.isfile(cmd))
        self.assertEqual(os.path.basename(cmd), BROWSER_BIN)

    def test_launch_env_forces_cairo(self) -> None:
        env = launch_env(
            {
                "GSK_RENDERER": "ngl",
                "PATH": "/bin",
                "WEBKIT_DISABLE_DMABUF_RENDERER": "1",
                "WEBKIT_DISABLE_COMPOSITING_MODE": "1",
            }
        )
        self.assertEqual(env["GSK_RENDERER"], "cairo")
        self.assertNotIn("WEBKIT_DISABLE_DMABUF_RENDERER", env)
        self.assertNotIn("WEBKIT_DISABLE_COMPOSITING_MODE", env)
        for key, val in HELPER_ENV.items():
            self.assertEqual(env[key], val)

    def test_log_path_uses_runtime_dir(self) -> None:
        path = browser_log_path({"XDG_RUNTIME_DIR": "/run/user/1000"})
        self.assertEqual(path, "/run/user/1000/firstboot-browser.log")

    def test_command_is_executable(self) -> None:
        cmd = browser_command()
        self.assertTrue(os.access(cmd, os.X_OK))

    def test_drop_process_caps_is_safe(self) -> None:
        drop_process_caps()


class AppGridTests(unittest.TestCase):
    def test_browser_is_wired(self) -> None:
        actions = [item[2] for item in APP_ITEMS]
        self.assertEqual(actions, ["browser", "sysinfo", "terminal"])
        self.assertNotIn("browser", APP_TOASTS)


if __name__ == "__main__":
    unittest.main()
