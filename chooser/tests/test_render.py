#!/usr/bin/env python3
"""Renderer pick — no GTK, no DRM required."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.render import (  # noqa: E402
    drm_card_names,
    drm_drivers,
    renderer_env,
    use_software_render,
)


class DriverScanTests(unittest.TestCase):
    def test_card_names_skip_connectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "card1"))
            os.makedirs(os.path.join(tmp, "card1-eDP-1"))
            os.makedirs(os.path.join(tmp, "renderD128"))
            self.assertEqual(drm_card_names(tmp), ["card1"])

    def test_driver_from_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            card = os.path.join(tmp, "card1", "device")
            os.makedirs(card)
            target = os.path.join(tmp, "i915")
            os.makedirs(target)
            os.symlink(target, os.path.join(card, "driver"))
            self.assertEqual(drm_drivers(tmp), ["i915"])


class PolicyTests(unittest.TestCase):
    def test_i915_uses_gpu(self) -> None:
        self.assertFalse(use_software_render(["i915"]))
        env = renderer_env(["i915"], {})
        self.assertEqual(env["GSK_RENDERER"], "ngl")
        self.assertEqual(env["WLR_RENDERER"], "gles2")
        self.assertNotIn("WEBKIT_DISABLE_DMABUF_RENDERER", env)

    def test_virtio_uses_software(self) -> None:
        self.assertTrue(use_software_render(["virtio_gpu"]))
        env = renderer_env(["virtio_gpu"], {})
        self.assertEqual(env["GSK_RENDERER"], "cairo")
        self.assertEqual(env["WLR_RENDERER"], "pixman")
        self.assertNotIn("WEBKIT_DISABLE_DMABUF_RENDERER", env)

    def test_no_drm_is_software(self) -> None:
        self.assertTrue(use_software_render([]))

    def test_unknown_driver_is_software(self) -> None:
        self.assertTrue(use_software_render(["virtio-pci"]))

    def test_force_software(self) -> None:
        self.assertTrue(use_software_render(["i915"], {"FIRSTBOOT_SOFTWARE_RENDER": "1"}))

    def test_force_gpu(self) -> None:
        self.assertFalse(use_software_render(["virtio_gpu"], {"FIRSTBOOT_SOFTWARE_RENDER": "0"}))

    def test_existing_env_not_overwritten(self) -> None:
        env = renderer_env(
            ["i915"],
            {
                "GSK_RENDERER": "cairo",
                "WLR_RENDERER": "pixman",
            },
        )
        self.assertEqual(env, {})

    def test_session_does_not_force_webkit_dmabuf_off(self) -> None:
        env = renderer_env(["i915"], {"GSK_RENDERER": "ngl", "WLR_RENDERER": "gles2"})
        self.assertEqual(env, {})


if __name__ == "__main__":
    unittest.main()
