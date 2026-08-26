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
    ANACONDA_SCRIPT,
    ANACONDA_SERVICE,
    DRACUT_HOOK,
    DRIVER,
    GENERATOR,
    ID,
    LINK_SQUASH,
    SQUASH_LINK,
    STRIP_INSTALLER_CMDLINE_PY,
    fedora_kernel_args,
    fedora_kickstart,
)

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
        self.assertIn("usr/libexec/fbl-link-squashfs", files)
        self.assertIn("usr/libexec/fbl-anaconda", files)
        self.assertIn("etc/systemd/system/getty@tty1.service", files)
        self.assertIn("etc/systemd/system-generators/fbl-anaconda-gen", files)
        self.assertNotIn("etc/systemd/system/fbl-anaconda.service", files)
        self.assertIn("var/lib/dracut/hooks/pre-pivot/90-fbl-ks.sh", files)
        self.assertNotIn("fbl-liveinst", files)
        self.assertNotIn("fbl-pkexec.policy", files)
        self.assertNotIn("etc/xdg/autostart/fbl-liveinst.desktop", files)
        self.assertNotIn("etc/polkit-1/rules.d/00-fbl-liveinst.rules", files)

    def test_kickstart_is_liveimg_not_dnf(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = fedora_kickstart(ident, "/dev/sda")
        self.assertIn(f"liveimg --url=file://{SQUASH_LINK}", text)
        self.assertIn("cmdline\n", text)
        self.assertNotIn("graphical\n", text)
        self.assertIn('--append="rhgb quiet"', text)
        self.assertIn("selinux --enforcing", text)
        self.assertIn("services --enabled=sddm,NetworkManager", text)
        self.assertIn("graphical.target", text)
        self.assertIn("systemd.unit=", text)
        self.assertIn("systemd.mask=", text)
        self.assertIn("rm -f /etc/systemd/system/getty@tty1.service", text)
        self.assertIn("fbl-anaconda-gen", text)
        self.assertNotIn("%packages", text)
        self.assertNotIn("boot=casper", text)
        args = fedora_kernel_args(
            "/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso",
            "Fedora-KDE-Live-44",
            toram=True,
        )
        self.assertNotIn("liveinst", args.split())
        self.assertNotIn("inst.ks", args.split())
        self.assertIn("systemd.unit=multi-user.target", args)
        self.assertIn("inst.cmdline", args.split())
        self.assertIn("rd.live.ram=1", args)
        self.assertIn("--kickstart=/ks.cfg --cmdline", ANACONDA_SCRIPT)
        self.assertNotIn("pkexec /", ANACONDA_SCRIPT)
        self.assertNotIn("--liveinst", ANACONDA_SCRIPT)
        self.assertIn("squashfs link missing", ANACONDA_SCRIPT)
        self.assertIn("squashed.img", LINK_SQUASH)
        self.assertIn("FBL_LIVE_ROOT", LINK_SQUASH)
        self.assertIn("hardlinked", LINK_SQUASH)
        self.assertNotIn("symlinked", LINK_SQUASH)
        self.assertIn("WantedBy=getty.target", ANACONDA_SERVICE)
        self.assertIn("ExecStart=/usr/libexec/fbl-anaconda", ANACONDA_SERVICE)
        self.assertIn("ExecStartPre=-/usr/sbin/setenforce 0", ANACONDA_SERVICE)
        self.assertNotIn("ExecStartPre=/usr/libexec/fbl-link-squashfs", ANACONDA_SERVICE)
        self.assertIn("ConditionKernelCommandLine=fbl.install", ANACONDA_SERVICE)
        self.assertNotIn("Conflicts=getty@tty1.service", ANACONDA_SERVICE)
        self.assertIn("exec /bin/bash", ANACONDA_SCRIPT)
        self.assertIn("enforcing=0", args.split())
        self.assertIn("systemd.mask=display-manager.service", args)
        self.assertIn("rd.live.overlay.overlayfs", args)
        self.assertIn("getty@tty1.service", GENERATOR)
        self.assertLess(
            ANACONDA_SERVICE.find("ExecStartPre=-/usr/sbin/setenforce 0"),
            ANACONDA_SERVICE.find("ExecStart=/usr/libexec/fbl-anaconda"),
        )
        self.assertIn("getty@tty1.service", DRACUT_HOOK)
        self.assertNotIn("\nexit ", DRACUT_HOOK)
        self.assertIn("FBL_LIVE_LOG=", DRACUT_HOOK)
        self.assertLess(
            DRACUT_HOOK.find("getty@tty1.service"),
            DRACUT_HOOK.find("FBL_LIVE_LOG="),
        )
        self.assertIn("rm -f", DRACUT_HOOK)
        self.assertNotIn("liveinst.real", DRACUT_HOOK)
        self.assertNotIn("pkexec", DRACUT_HOOK)
        self.assertNotIn("polkit-1", DRACUT_HOOK)
        self.assertNotIn("allow_any>yes", DRACUT_HOOK)
        self.assertNotIn('ln -sfn ../sbin/liveinst "', DRACUT_HOOK)

    def _bind_hook_to_initrd(self, initrd: str) -> str:
        """Point initramfs source paths at a fake tree. Leave $root dests alone."""
        hook = DRACUT_HOOK
        hook = hook.replace(
            "if [ -f /ks.cfg ]; then\n  cp /ks.cfg ",
            f"if [ -f {initrd}/ks.cfg ]; then\n  cp {initrd}/ks.cfg ",
        )
        hook = hook.replace(
            "if [ -f /usr/libexec/fbl-link-squashfs ]; then\n"
            "  cp /usr/libexec/fbl-link-squashfs ",
            f"if [ -f {initrd}/usr/libexec/fbl-link-squashfs ]; then\n"
            f"  cp {initrd}/usr/libexec/fbl-link-squashfs ",
        )
        hook = hook.replace(
            'FBL_LIVE_LOG="$log" /usr/libexec/fbl-link-squashfs >>',
            f'FBL_LIVE_LOG="$log" {initrd}/usr/libexec/fbl-link-squashfs >>',
        )
        hook = hook.replace(
            "if [ -f /usr/libexec/fbl-anaconda ]; then\n"
            "  cp /usr/libexec/fbl-anaconda ",
            f"if [ -f {initrd}/usr/libexec/fbl-anaconda ]; then\n"
            f"  cp {initrd}/usr/libexec/fbl-anaconda ",
        )
        hook = hook.replace(
            "if [ -f /etc/systemd/system/getty@tty1.service ]; then\n",
            f"if [ -f {initrd}/etc/systemd/system/getty@tty1.service ]; then\n",
        )
        hook = hook.replace(
            "  cp /etc/systemd/system/getty@tty1.service ",
            f"  cp {initrd}/etc/systemd/system/getty@tty1.service ",
        )
        hook = hook.replace(
            "if [ -f /etc/systemd/system-generators/fbl-anaconda-gen ]; then\n"
            "  cp /etc/systemd/system-generators/fbl-anaconda-gen ",
            f"if [ -f {initrd}/etc/systemd/system-generators/fbl-anaconda-gen ]; then\n"
            f"  cp {initrd}/etc/systemd/system-generators/fbl-anaconda-gen ",
        )
        hook = hook.replace(
            "ls -l /ks.cfg /usr/libexec/fbl-link-squashfs /usr/libexec/fbl-anaconda",
            f"ls -l {initrd}/ks.cfg {initrd}/usr/libexec/fbl-link-squashfs "
            f"{initrd}/usr/libexec/fbl-anaconda",
        )
        return hook

    def _write_initrd_seed(self, initrd: str) -> None:
        os.makedirs(os.path.join(initrd, "usr/libexec"))
        os.makedirs(os.path.join(initrd, "etc/systemd/system"))
        os.makedirs(os.path.join(initrd, "etc/systemd/system-generators"))
        os.makedirs(os.path.join(initrd, "var/lib/dracut/hooks/pre-pivot"))
        with open(os.path.join(initrd, "ks.cfg"), "w", encoding="utf-8") as fh:
            fh.write("cmdline\nliveimg --url=file:///run/fbl-squashfs.img\n")
        linker = os.path.join(initrd, "usr/libexec/fbl-link-squashfs")
        with open(linker, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/bash\nexit 0\n")
        os.chmod(linker, 0o755)
        ana = os.path.join(initrd, "usr/libexec/fbl-anaconda")
        with open(ana, "w", encoding="utf-8") as fh:
            fh.write(ANACONDA_SCRIPT)
        os.chmod(ana, 0o755)
        unit = os.path.join(initrd, "etc/systemd/system/getty@tty1.service")
        with open(unit, "w", encoding="utf-8") as fh:
            fh.write(ANACONDA_SERVICE)
        gen = os.path.join(initrd, "etc/systemd/system-generators/fbl-anaconda-gen")
        with open(gen, "w", encoding="utf-8") as fh:
            fh.write(GENERATOR)
        os.chmod(gen, 0o755)

    def test_pre_pivot_leaves_official_liveinst_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            newroot = os.path.join(tmp, "sysroot")
            initrd = os.path.join(tmp, "initrd")
            usr_bin = os.path.join(newroot, "usr", "bin")
            os.makedirs(usr_bin)
            os.symlink("bin", os.path.join(newroot, "usr", "sbin"))
            liveinst = os.path.join(usr_bin, "liveinst")
            official = "#!/bin/bash\nANACONDA=\"anaconda --liveinst --graphical\"\n"
            with open(liveinst, "w", encoding="utf-8") as fh:
                fh.write(official)
            os.chmod(liveinst, 0o755)
            self._write_initrd_seed(initrd)
            script = os.path.join(tmp, "run-hook.sh")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(self._bind_hook_to_initrd(initrd))
            os.chmod(script, 0o755)
            proc = subprocess.run(
                ["sh", script],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "NEWROOT": newroot},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            with open(liveinst, encoding="utf-8") as fh:
                body = fh.read()
            self.assertEqual(body, official)
            self.assertFalse(
                os.path.exists(os.path.join(usr_bin, "liveinst.real"))
            )

    def test_pre_pivot_copies_ks_and_enables_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            newroot = os.path.join(tmp, "sysroot")
            initrd = os.path.join(tmp, "initrd")
            os.makedirs(newroot)
            self._write_initrd_seed(initrd)
            script = os.path.join(tmp, "run-hook.sh")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(self._bind_hook_to_initrd(initrd))
            os.chmod(script, 0o755)
            proc = subprocess.run(
                ["sh", script],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "NEWROOT": newroot},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertTrue(os.path.isfile(os.path.join(newroot, "ks.cfg")))
            with open(os.path.join(newroot, "ks.cfg"), encoding="utf-8") as fh:
                self.assertIn("liveimg", fh.read())
            self.assertTrue(
                os.path.isfile(os.path.join(newroot, "usr/libexec/fbl-anaconda"))
            )
            getty = os.path.join(newroot, "etc/systemd/system/getty@tty1.service")
            self.assertTrue(os.path.isfile(getty), getty)
            gen = os.path.join(
                newroot, "etc/systemd/system-generators/fbl-anaconda-gen"
            )
            self.assertTrue(os.path.isfile(gen), gen)
            self.assertTrue(os.access(gen, os.X_OK))

    def test_linker_hardlinks_squashed_img(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_dir = os.path.join(tmp, "run", "initramfs")
            os.makedirs(img_dir)
            src = os.path.join(img_dir, "squashed.img")
            with open(src, "wb") as fh:
                fh.write(b"live-image" * 64)
            script = os.path.join(tmp, "link.sh")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(LINK_SQUASH)
            os.chmod(script, 0o755)
            proc = subprocess.run(
                ["bash", script],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "FBL_LIVE_ROOT": tmp},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            dest = os.path.join(tmp, "run", "fbl-squashfs.img")
            self.assertTrue(os.path.isfile(dest), dest)
            self.assertGreater(os.path.getsize(dest), 0)
            self.assertEqual(os.path.samefile(src, dest), True)
            log = os.path.join(tmp, "var", "log", "firstboot-fedora.log")
            self.assertTrue(os.path.isfile(log))
            with open(log, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("hardlinked", body)

    def test_linker_does_not_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            other = os.path.join(tmp, "otherfs")
            os.makedirs(other)
            src = os.path.join(other, "squashfs.img")
            with open(src, "wb") as fh:
                fh.write(b"live-image" * 64)
            # Point find() fallback at other/ by putting it under run/live.
            live = os.path.join(tmp, "run", "live")
            os.makedirs(live)
            src2 = os.path.join(live, "squashfs.img")
            # Different file (copy) so hardlink from dest's filesystem fails
            # if we later used a bind; here dest is tmp/run which is same FS.
            # Simulate cross-device by making dest's parent a file? Skip —
            # assert the script text never falls back to ln -s.
            self.assertNotIn("ln -sfn", LINK_SQUASH)
            self.assertIn("no symlink", LINK_SQUASH)
            _ = src2

    def test_anaconda_script_refuses_without_image(self) -> None:
        self.assertIn("refusing to start (would DNF)", ANACONDA_SCRIPT)
        self.assertLess(
            ANACONDA_SCRIPT.find("squashfs link missing"),
            ANACONDA_SCRIPT.find("exec \"$ana\""),
        )
        self.assertIn("not root; refusing", ANACONDA_SCRIPT)
        self.assertIn("exec /bin/bash", ANACONDA_SCRIPT)
        self.assertIn("Installer did not finish", ANACONDA_SCRIPT)

    def test_strip_installer_cmdline_leaves_desktop(self) -> None:
        ns: dict = {}
        exec(STRIP_INSTALLER_CMDLINE_PY, ns)
        clean = ns["clean"]
        patch_text = ns["patch_text"]
        src = (
            "root=UUID=abc rd.luks.uuid=x rd.live.image rd.live.ram=1 "
            "rd.live.overlay.overlayfs iso-scan/filename=/images/Fedora.iso "
            "root=live:CDLABEL=Fedora-KDE-Live-44 systemd.unit=multi-user.target "
            "systemd.mask=display-manager.service systemd.mask=sddm.service "
            "inst.cmdline fbl.install enforcing=0"
        )
        out = clean(src)
        toks = out.split()
        self.assertIn("root=UUID=abc", toks)
        self.assertIn("rd.luks.uuid=x", toks)
        self.assertIn("rhgb", toks)
        self.assertIn("quiet", toks)
        self.assertNotIn("inst.cmdline", toks)
        self.assertNotIn("fbl.install", toks)
        self.assertNotIn("enforcing=0", toks)
        self.assertFalse(any(t.startswith("systemd.unit=") for t in toks))
        self.assertFalse(any(t.startswith("systemd.mask=") for t in toks))
        self.assertFalse(any(t.startswith("rd.live.") for t in toks))
        self.assertFalse(any(t.startswith("iso-scan/") for t in toks))
        self.assertFalse(any(t.startswith("root=live:") for t in toks))
        bls = (
            "title Fedora\n"
            "linux /vmlinuz\n"
            f"options {src}\n"
        )
        patched = patch_text(bls)
        self.assertIn("options root=UUID=abc", patched)
        self.assertNotIn("systemd.unit=", patched)
        grub = 'GRUB_CMDLINE_LINUX="rhgb quiet systemd.unit=multi-user.target"\n'
        self.assertNotIn("systemd.unit=", patch_text(grub))

    def test_pre_pivot_hook_can_be_sourced(self) -> None:
        """dracut source_hook sources scripts; exit would abort pre-pivot."""
        with tempfile.TemporaryDirectory() as tmp:
            newroot = os.path.join(tmp, "sysroot")
            initrd = os.path.join(tmp, "initrd")
            os.makedirs(newroot)
            self._write_initrd_seed(initrd)
            script = os.path.join(tmp, "run-hook.sh")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(self._bind_hook_to_initrd(initrd))
            os.chmod(script, 0o755)
            proc = subprocess.run(
                ["sh", "-c", ". ./run-hook.sh; echo STILL_ALIVE"],
                check=False,
                capture_output=True,
                text=True,
                cwd=tmp,
                env={**os.environ, "NEWROOT": newroot},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn("STILL_ALIVE", proc.stdout)
