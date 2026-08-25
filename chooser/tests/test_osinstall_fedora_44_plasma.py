#!/usr/bin/env python3
"""Fedora 44 Plasma driver only."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.osinstall import OsIdentity  # noqa: E402
from firstboot.osinstall.fedora_44_plasma import (  # noqa: E402
    AUTOSTART_DESKTOP,
    DRACUT_HOOK,
    DRIVER,
    ID,
    LINK_SERVICE,
    LINK_SQUASH,
    LIVEINST_WRAPPER,
    SQUASH_LINK,
    fedora_kernel_args,
    fedora_kickstart,
)

OFFICIAL_LIVEINST = """#!/bin/bash
ANACONDA="/sbin/anaconda --liveinst --graphical ${LIVECMD}"
[ -z "$LIVECMD" ] && ANACONDA="/sbin/anaconda --liveinst --graphical"
exec $ANACONDA "$@"
"""

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$Zx9Rit70sU0wKFAKESECRET_k4l5m6n7o8p9q0r1s2t3"
)


class Fedora44PlasmaTests(unittest.TestCase):
    def test_driver_id(self) -> None:
        self.assertEqual(ID, "fedora-44-plasma")
        self.assertIn("fedora-kickstart", DRIVER.aliases)
        self.assertEqual(DRIVER.default_hostname, "fedora")

    def test_seed_files(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        files = DRIVER.seed_files(ident, "/dev/sda", "")
        self.assertIn("ks.cfg", files)
        self.assertIn("fbl-liveinst", files)
        self.assertIn("usr/libexec/fbl-link-squashfs", files)
        self.assertIn("etc/xdg/autostart/fbl-liveinst.desktop", files)

    def test_kickstart_is_liveimg_not_dnf(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = fedora_kickstart(ident, "/dev/sda")
        self.assertIn(f"liveimg --url=file://{SQUASH_LINK}", text)
        self.assertNotIn("%packages", text)
        self.assertNotIn("boot=casper", text)
        self.assertIn("liveinst.real", LIVEINST_WRAPPER)
        args = fedora_kernel_args(
            "/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso",
            "Fedora-KDE-Live-44",
            toram=True,
        )
        self.assertNotIn("liveinst", args.split())
        self.assertNotIn("inst.ks", args)
        self.assertIn("Exec=/usr/bin/liveinst", AUTOSTART_DESKTOP)
        self.assertIn("/usr/bin/liveinst.real", LIVEINST_WRAPPER)
        self.assertIn("squashed.img", LINK_SQUASH)
        self.assertIn("ensure_link", LIVEINST_WRAPPER)
        self.assertIn("WantedBy=graphical.target", LINK_SERVICE)
        self.assertNotIn('ln -sfn ../sbin/liveinst "', DRACUT_HOOK)

    def _run_pre_pivot(self, newroot: str, wrapper: str) -> None:
        hook = DRACUT_HOOK.replace("/fbl-liveinst", wrapper)
        script = os.path.join(newroot, "run-hook.sh")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(hook)
        os.chmod(script, 0o755)
        proc = subprocess.run(
            ["sh", script],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "NEWROOT": newroot},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

    def test_usr_merge_keeps_liveinst_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            usr_bin = os.path.join(tmp, "usr", "bin")
            os.makedirs(usr_bin)
            os.symlink("bin", os.path.join(tmp, "usr", "sbin"))
            liveinst = os.path.join(usr_bin, "liveinst")
            with open(liveinst, "w", encoding="utf-8") as fh:
                fh.write(OFFICIAL_LIVEINST)
            os.chmod(liveinst, 0o755)
            wrapper = os.path.join(tmp, "wrapper")
            with open(wrapper, "w", encoding="utf-8") as fh:
                fh.write(LIVEINST_WRAPPER)
            os.chmod(wrapper, 0o755)
            self._run_pre_pivot(tmp, wrapper)
            self.assertTrue(os.path.isfile(liveinst), liveinst)
            self.assertFalse(os.path.islink(liveinst))
            self.assertTrue(os.access(liveinst, os.X_OK))
            self.assertFalse(os.path.islink(os.path.realpath(liveinst)))
            real = os.path.join(usr_bin, "liveinst.real")
            self.assertTrue(os.path.isfile(real))
            with open(liveinst, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("liveinst.real", body)
            with open(real, encoding="utf-8") as fh:
                official = fh.read()
            self.assertIn("--kickstart=/ks.cfg", official)

    def test_split_sbin_gets_symlink_to_bin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            usr_bin = os.path.join(tmp, "usr", "bin")
            usr_sbin = os.path.join(tmp, "usr", "sbin")
            os.makedirs(usr_bin)
            os.makedirs(usr_sbin)
            liveinst = os.path.join(usr_sbin, "liveinst")
            with open(liveinst, "w", encoding="utf-8") as fh:
                fh.write(OFFICIAL_LIVEINST)
            os.chmod(liveinst, 0o755)
            wrapper = os.path.join(tmp, "wrapper")
            with open(wrapper, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/bash\nexec /usr/sbin/liveinst.real \"$@\"\n")
            os.chmod(wrapper, 0o755)
            self._run_pre_pivot(tmp, wrapper)
            bin_live = os.path.join(usr_bin, "liveinst")
            self.assertTrue(os.path.isfile(bin_live))
            self.assertTrue(os.path.islink(liveinst) or os.path.isfile(liveinst))
            self.assertEqual(os.path.realpath(liveinst), os.path.realpath(bin_live))
            self.assertTrue(os.path.isfile(os.path.join(usr_sbin, "liveinst.real")))
