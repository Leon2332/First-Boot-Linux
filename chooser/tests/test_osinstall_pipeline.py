#!/usr/bin/env python3
"""Native install pipeline helpers — no root, no full ISO."""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.osinstall.casper import (  # noqa: E402
    copy_signed_esp_binaries,
    ensure_grub_efi_modules,
    install_casper_bootloader,
    unpack_squashfs,
)
from firstboot.disk import Disk, Partition  # noqa: E402
from firstboot.install import EXT4_GRUB_OPTS, STALE_EFI_LABELS  # noqa: E402
from firstboot.osinstall.common import (  # noqa: E402
    LOOP_CHANGE_FD,
    InstalledDisk,
    OsIdentity,
    OsInstallError,
    OsInstallPlan,
    health_check,
    partition_disk,
    register_os_efi,
    retarget_casper_loops,
)
from firstboot.osinstall.pipeline import (  # noqa: E402
    PIPELINE_TICKS,
    copy_live_to_ram,
    do_pivot_root,
    mount_ram_tmpfs,
    release_disk_holders,
    umount_in_all_namespaces,
    unmount_target,
)


class ListLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, msg: str) -> None:
        self.lines.append(msg)
from firstboot.osinstall.ubuntu_2604_gnome import DRIVER  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def installed_tree(root: str, efi: str, *, username: str = "leon") -> InstalledDisk:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-6.17.0"), "wb").close()
    open(os.path.join(boot, "initrd.img-6.17.0"), "wb").close()
    os.makedirs(os.path.join(root, "etc", "default"), exist_ok=True)
    os.makedirs(os.path.join(root, "etc", "systemd", "system"), exist_ok=True)
    os.makedirs(os.path.join(root, "usr", "lib", "systemd", "system"), exist_ok=True)
    with open(os.path.join(root, "etc", "passwd"), "w", encoding="utf-8") as fh:
        fh.write(f"root:x:0:0:root:/root:/bin/bash\n{username}:x:1000:1000:User:/home/{username}:/bin/bash\n")
    with open(os.path.join(root, "etc", "shadow"), "w", encoding="utf-8") as fh:
        fh.write(f"root:!:0:0:99999:7:::\n{username}:{UBUNTU_HASH}:0:0:99999:7:::\n")
    with open(os.path.join(root, "etc", "fstab"), "w", encoding="utf-8") as fh:
        fh.write("UUID=ROOT-UUID-2222 / ext4 errors=remount-ro 0 1\n")
        fh.write("UUID=ESP-UUID-1111 /boot/efi vfat umask=0077 0 1\n")
    with open(os.path.join(root, "etc", "default", "grub"), "w", encoding="utf-8") as fh:
        fh.write('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\nGRUB_CMDLINE_LINUX=""\n')
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "graphical.target"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "gdm.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    os.symlink(
        "../graphical.target",
        os.path.join(root, "etc", "systemd", "system", "default.target"),
    )
    os.symlink(
        "gdm.service",
        os.path.join(root, "etc", "systemd", "system", "display-manager.service"),
    )
    bootx = os.path.join(efi, "EFI", "BOOT")
    os.makedirs(bootx)
    open(os.path.join(bootx, "BOOTX64.EFI"), "wb").close()
    os.makedirs(os.path.join(efi, "EFI", "ubuntu"))
    open(os.path.join(efi, "EFI", "ubuntu", "grubx64.efi"), "wb").close()
    return InstalledDisk(
        disk="/dev/vda",
        esp_dev="/dev/vda1",
        root_dev="/dev/vda2",
        esp_uuid="ESP-UUID-1111",
        root_uuid="ROOT-UUID-2222",
        esp_mp=efi,
        root_mp=root,
    )


class TickTests(unittest.TestCase):
    def test_nine_steps(self) -> None:
        self.assertEqual(len(PIPELINE_TICKS), 9)
        self.assertEqual(PIPELINE_TICKS[0], "Checking the image")
        self.assertEqual(PIPELINE_TICKS[3], "Installing the system")
        self.assertEqual(PIPELINE_TICKS[6], "Checking the install")
        self.assertEqual(PIPELINE_TICKS[-1], "Restarting")


class HealthCheckTests(unittest.TestCase):
    def test_pass(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-hc-root-")
        efi = tempfile.mkdtemp(prefix="fbl-hc-efi-")
        try:
            disk = installed_tree(root, efi)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            fails = health_check(
                root, efi, ident, disk, display_manager="gdm"
            )
            self.assertEqual(fails, [])
            fails_drv = DRIVER.health_check(root, efi, ident, disk)
            self.assertEqual(fails_drv, [])
            # ISO-shim fallback: grub-install error is ok if ESP has BOOTX64.EFI.
            fails_grub = health_check(
                root,
                efi,
                ident,
                disk,
                display_manager="gdm",
                boot_log="grub-install: error: /usr/lib/grub/x86_64-efi/modinfo.sh doesn't exist.",
            )
            self.assertEqual(fails_grub, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_missing_kernel(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-hc-k-")
        efi = tempfile.mkdtemp(prefix="fbl-hc-e-")
        try:
            disk = installed_tree(root, efi)
            os.unlink(os.path.join(root, "boot", "vmlinuz-6.17.0"))
            os.unlink(os.path.join(root, "boot", "initrd.img-6.17.0"))
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            fails = health_check(root, efi, ident, disk, display_manager="gdm")
            self.assertTrue(any("kernel" in f.lower() for f in fails))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_leftover_cmdline(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-hc-c-")
        efi = tempfile.mkdtemp(prefix="fbl-hc-e-")
        try:
            disk = installed_tree(root, efi)
            with open(os.path.join(root, "etc", "default", "grub"), "w", encoding="utf-8") as fh:
                fh.write('GRUB_CMDLINE_LINUX="fbl.install toram"\n')
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            fails = health_check(root, efi, ident, disk, display_manager="gdm")
            self.assertTrue(any("cmdline" in f.lower() for f in fails))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_wrong_target(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-hc-t-")
        efi = tempfile.mkdtemp(prefix="fbl-hc-e-")
        try:
            disk = installed_tree(root, efi)
            dest = os.path.join(root, "etc", "systemd", "system", "default.target")
            os.unlink(dest)
            os.symlink("../multi-user.target", dest)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            fails = health_check(root, efi, ident, disk, display_manager="gdm")
            self.assertTrue(any("graphical.target" in f for f in fails))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)


class UnpackTests(unittest.TestCase):
    def test_tiny_squashfs(self) -> None:
        if not shutil.which("mksquashfs") or not shutil.which("unsquashfs"):
            self.skipTest("squashfs-tools not installed")
        src = tempfile.mkdtemp(prefix="fbl-sq-src-")
        dest = tempfile.mkdtemp(prefix="fbl-sq-dst-")
        sq = tempfile.NamedTemporaryFile(suffix=".squashfs", delete=False)
        sq.close()
        try:
            boot = os.path.join(src, "boot")
            os.makedirs(boot)
            with open(os.path.join(boot, "vmlinuz"), "wb") as fh:
                fh.write(b"k")
            proc = subprocess.run(
                ["mksquashfs", src, sq.name, "-noappend", "-quiet"],
                check=False,
                capture_output=True,
            )
            if proc.returncode != 0:
                self.skipTest("mksquashfs failed")
            unpack_squashfs(sq.name, dest)
            self.assertTrue(os.path.isfile(os.path.join(dest, "boot", "vmlinuz")))
        finally:
            shutil.rmtree(src, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)
            os.unlink(sq.name)


class DummyLog:
    def write(self, msg: str) -> None:
        pass


class PivotRootTests(unittest.TestCase):
    def test_pipeline_does_not_call_os_pivot_root(self) -> None:
        """Ubuntu 26.04 Python 3.14 is built without os.pivot_root.

        0.7.1.5 called os.pivot_root after the RAM copy; that is an
        AttributeError, which the helper turned into 'Install failed (1).'
        """
        import firstboot.osinstall.pipeline as pl

        with open(pl.__file__, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("os.pivot_root(", text)

    def _run_do_pivot_root(self, new_root: str, put_old: str, **kwargs) -> None:
        if hasattr(os, "pivot_root"):
            with mock.patch.object(os, "pivot_root", side_effect=OSError("skip")):
                do_pivot_root(new_root, put_old, **kwargs)
        else:
            do_pivot_root(new_root, put_old, **kwargs)

    def test_do_pivot_root_uses_libc(self) -> None:
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                new_root = os.path.join(tmp, "new")
                put_old = os.path.join(new_root, "oldroot")
                os.makedirs(put_old)
                pivot = mock.Mock(return_value=0)
                libc = mock.Mock()
                libc.pivot_root = pivot
                log = ListLog()
                runs: list[list[str]] = []

                def fake_run(argv, **_kwargs):
                    runs.append(list(argv))
                    return mock.Mock(returncode=0, stderr="", stdout="")

                with mock.patch(
                    "firstboot.osinstall.pipeline.ctypes.CDLL",
                    return_value=libc,
                ), mock.patch("subprocess.run", side_effect=fake_run):
                    self._run_do_pivot_root(new_root, put_old, log=log)
                self.assertTrue(
                    any(a[:3] == ["mount", "--make-rprivate", "/"] for a in runs)
                )
                self.assertTrue(
                    any(
                        a[:2] == ["mount", "--make-rprivate"] and a[-1] == new_root
                        for a in runs
                    )
                )
                pivot.assert_called_once()
                args = pivot.call_args[0]
                self.assertEqual(args[0], b".")
                self.assertEqual(args[1], b"oldroot")
                self.assertIn("pivot_root via libc", log.lines)
                self.assertTrue(
                    any(line.startswith("mount --make-rprivate /") for line in log.lines)
                )
        finally:
            os.chdir(cwd)

    def test_do_pivot_root_logs_einval(self) -> None:
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                new_root = os.path.join(tmp, "new")
                put_old = os.path.join(new_root, "oldroot")
                os.makedirs(put_old)
                pivot = mock.Mock(return_value=-1)
                libc = mock.Mock()
                libc.pivot_root = pivot
                log = ListLog()

                def fake_run(argv, **_kwargs):
                    return mock.Mock(returncode=1, stderr="Invalid argument", stdout="")

                with mock.patch(
                    "firstboot.osinstall.pipeline.ctypes.CDLL",
                    return_value=libc,
                ), mock.patch(
                    "firstboot.osinstall.pipeline.ctypes.get_errno",
                    return_value=errno.EINVAL,
                ), mock.patch("subprocess.run", side_effect=fake_run), mock.patch(
                    "os.path.isfile", return_value=False
                ), mock.patch("shutil.which", return_value=None):
                    with self.assertRaises(OsInstallError) as ctx:
                        self._run_do_pivot_root(new_root, put_old, log=log)
                self.assertIn("memory", str(ctx.exception).lower())
                joined = "\n".join(log.lines)
                self.assertIn(str(errno.EINVAL), joined)
                self.assertTrue(
                    "Invalid argument" in joined or "invalid argument" in joined.lower()
                )
        finally:
            os.chdir(cwd)


class RamTmpfsTests(unittest.TestCase):
    def test_mount_ram_tmpfs_uses_dedicated_mount(self) -> None:
        with mock.patch("os.makedirs"), mock.patch(
            "os.path.ismount", return_value=False
        ), mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
            mount_ram_tmpfs(8 * 1024 * 1024 * 1024)
        argv = run.call_args[0][0]
        self.assertEqual(argv[0], "mount")
        self.assertIn("-t", argv)
        self.assertIn("tmpfs", argv)
        self.assertTrue(any(isinstance(a, str) and a.startswith("size=") for a in argv))

    def test_copy_live_enospc_is_osinstallerror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.squashfs")
            with open(src, "wb") as fh:
                fh.write(b"x")
            with mock.patch("firstboot.osinstall.pipeline.mount_ram_tmpfs"), mock.patch(
                "firstboot.osinstall.pipeline.copy_file_progress",
                side_effect=OSError(errno.ENOSPC, "No space left"),
            ), mock.patch(
                "firstboot.osinstall.pipeline.find_live_squashfs",
                return_value="/cdrom/casper/filesystem.squashfs",
            ):
                with self.assertRaises(OsInstallError) as ctx:
                    copy_live_to_ram(
                        [src], {}, on_progress=None, log=DummyLog(), need_bytes=3
                    )
        self.assertIn("memory", str(ctx.exception).lower())

    def test_copy_live_skips_when_already_on_ram(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ram = os.path.join(tmp, "ram")
            os.makedirs(ram)
            layer = os.path.join(ram, "layer0.squashfs")
            live = os.path.join(ram, "live.squashfs")
            open(layer, "wb").close()
            open(live, "wb").close()
            src = os.path.join(tmp, "a.squashfs")
            open(src, "wb").close()
            log = ListLog()
            with mock.patch(
                "firstboot.osinstall.pipeline.RAM_DIR", ram
            ), mock.patch(
                "firstboot.osinstall.pipeline.already_on_ram_overlay",
                return_value=True,
            ), mock.patch(
                "firstboot.osinstall.pipeline.mount_ram_tmpfs"
            ) as mount:
                dest = copy_live_to_ram(
                    [src], {}, on_progress=None, log=log, need_bytes=3
                )
            mount.assert_not_called()
            self.assertEqual(dest, [layer])
            self.assertTrue(any("already on RAM overlay" in line for line in log.lines))


class UnmountNamespacesTests(unittest.TestCase):
    def test_umount_in_all_namespaces_uses_nsenter(self) -> None:
        runs: list[list[str]] = []

        def fake_run(argv, **_kwargs):
            runs.append(list(argv))
            return mock.Mock(returncode=0, stderr="", stdout="")

        log = ListLog()
        with mock.patch("os.listdir", return_value=["1", "self"]), mock.patch(
            "os.readlink", return_value="mnt:[1]"
        ), mock.patch("os.path.isfile", return_value=True), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            umount_in_all_namespaces(["/cdrom", "/run/payload"], log=log)
        self.assertTrue(
            any(a[:3] == ["/usr/bin/nsenter", "-t", "1"] and "umount" in a for a in runs)
        )
        self.assertTrue(any("umount /cdrom" in line for line in log.lines))

    def test_same_disk_unmount_does_not_skip_cdrom(self) -> None:
        disk = Disk(
            path="/dev/sda",
            size=100,
            parts=(
                Partition(
                    path="/dev/sda2",
                    size=1,
                    label="FBL-SYS",
                    mountpoints=("/cdrom",),
                ),
            ),
        )
        plan = OsInstallPlan(True, target=disk, same_disk=True)
        log = ListLog()
        with mock.patch(
            "firstboot.osinstall.pipeline.release_disk_holders"
        ) as release, mock.patch(
            "firstboot.osinstall.pipeline.collected_mounts",
            return_value=["/cdrom"],
        ), mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
            unmount_target(plan, log)
        release.assert_called_once()
        self.assertTrue(any("unmount /cdrom on target" in line for line in log.lines))
        self.assertFalse(any(line.startswith("skip unmount /cdrom") for line in log.lines))


class HelperMainTests(unittest.TestCase):
    def test_unexpected_exception_emits_error(self) -> None:
        from firstboot.osinstall import main

        argv = [
            "--apply",
            "--iso",
            "/tmp/x.iso",
            "--iso-rel",
            "/images/x.iso",
            "--sha256",
            "0" * 64,
            "--driver",
            "ubuntu-2604-gnome",
            "--target",
            "/dev/vda",
            "--live",
            "/dev/vda",
            "--hostname",
            "shop-pc",
            "--username",
            "leon",
            "--password-hash",
            UBUNTU_HASH,
        ]
        with mock.patch("firstboot.osinstall.apply_payload_language"), mock.patch(
            "firstboot.osinstall._plan_from_args",
            side_effect=RuntimeError("module 'os' has no attribute 'pivot_root'"),
        ), mock.patch("firstboot.osinstall.emit") as em:
            rc = main(argv)
        self.assertEqual(rc, 1)
        err = [c.args for c in em.call_args_list if c.args and c.args[0] == "ERROR"]
        self.assertTrue(err)
        self.assertIn("pivot_root", str(err[0]))


class RetargetLoopTests(unittest.TestCase):
    def test_change_fd_to_ram_copy(self) -> None:
        ioctls: list[tuple[int, int, int]] = []
        fds = iter([10, 11])
        log = ListLog()
        after = [
            ("/dev/loop0", (0, 55), "/run/fbl-install/live.squashfs"),
        ]

        def fake_ioctl(fd: int, req: int, arg: int) -> int:
            ioctls.append((fd, req, arg))
            return 0

        with mock.patch(
            "firstboot.osinstall.common.os.path.isfile", return_value=True
        ), mock.patch(
            "firstboot.osinstall.common.disk_holder_nums", return_value={(8, 2)}
        ), mock.patch(
            "firstboot.osinstall.common.list_loop_devices",
            side_effect=[
                [("/dev/loop0", (8, 2), "/casper/filesystem.squashfs")],
                after,
            ],
        ), mock.patch(
            "firstboot.osinstall.common.casper_loops_on_disk", return_value=[]
        ), mock.patch(
            "os.open", side_effect=lambda *_a, **_k: next(fds)
        ), mock.patch("os.close"), mock.patch(
            "fcntl.ioctl", side_effect=fake_ioctl
        ):
            retarget_casper_loops(
                "/dev/sda", "/run/fbl-install/live.squashfs", log=log
            )
        self.assertEqual(ioctls, [(10, LOOP_CHANGE_FD, 11)])
        self.assertTrue(any("retarget /dev/loop0" in line for line in log.lines))

    def test_change_fd_failure_raises(self) -> None:
        fds = iter([10, 11])
        with mock.patch(
            "firstboot.osinstall.common.os.path.isfile", return_value=True
        ), mock.patch(
            "firstboot.osinstall.common.disk_holder_nums", return_value={(8, 2)}
        ), mock.patch(
            "firstboot.osinstall.common.list_loop_devices",
            return_value=[("/dev/loop0", (8, 2), "/casper/filesystem.squashfs")],
        ), mock.patch(
            "os.open", side_effect=lambda *_a, **_k: next(fds)
        ), mock.patch("os.close"), mock.patch(
            "fcntl.ioctl", side_effect=OSError(errno.EINVAL, "Invalid argument")
        ):
            with self.assertRaises(OsInstallError) as ctx:
                retarget_casper_loops("/dev/sda", "/run/fbl-install/live.squashfs")
        self.assertIn("disk", str(ctx.exception).lower())

    def test_leftover_loop_raises(self) -> None:
        fds = iter([10, 11])
        with mock.patch(
            "firstboot.osinstall.common.os.path.isfile", return_value=True
        ), mock.patch(
            "firstboot.osinstall.common.disk_holder_nums", return_value={(8, 2)}
        ), mock.patch(
            "firstboot.osinstall.common.list_loop_devices",
            return_value=[("/dev/loop0", (8, 2), "/casper/filesystem.squashfs")],
        ), mock.patch(
            "firstboot.osinstall.common.casper_loops_on_disk",
            return_value=["/dev/loop0"],
        ), mock.patch(
            "os.open", side_effect=lambda *_a, **_k: next(fds)
        ), mock.patch("os.close"), mock.patch("fcntl.ioctl", return_value=0):
            with self.assertRaises(OsInstallError) as ctx:
                retarget_casper_loops("/dev/sda", "/run/fbl-install/live.squashfs")
        self.assertIn("disk", str(ctx.exception).lower())

    def test_release_retargets_before_umount(self) -> None:
        order: list[str] = []

        def retarget(*_a, **_k) -> None:
            order.append("retarget")

        def umount(*_a, **_k) -> None:
            order.append("umount")

        def detach(*_a, **_k) -> None:
            order.append("detach")

        with mock.patch(
            "firstboot.osinstall.pipeline.retarget_casper_loops", side_effect=retarget
        ), mock.patch(
            "firstboot.osinstall.pipeline.umount_in_all_namespaces", side_effect=umount
        ), mock.patch(
            "firstboot.osinstall.pipeline.detach_loops_on_disk", side_effect=detach
        ):
            release_disk_holders("/dev/sda")
        self.assertEqual(order, ["retarget", "umount", "detach"])

    def test_pipeline_does_not_kill_glycin(self) -> None:
        import firstboot.osinstall.pipeline as pl

        with open(pl.__file__, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("glycin-svg", text)
        self.assertNotIn("os.kill", text)
        self.assertNotIn("umount / in old-casper", text)


class PartitionDiskTests(unittest.TestCase):
    def test_root_is_partition_two(self) -> None:
        runs: list[list[str]] = []

        def fake_checked(argv, **_kwargs):
            runs.append(list(argv))

        with mock.patch(
            "firstboot.osinstall.common.casper_loops_on_disk", return_value=[]
        ), mock.patch(
            "firstboot.osinstall.common.run_checked", side_effect=fake_checked
        ), mock.patch("subprocess.run"), mock.patch(
            "firstboot.osinstall.common.wait_dev"
        ), mock.patch(
            "firstboot.osinstall.common.blkid_uuid", side_effect=["esp-uuid", "root-uuid"]
        ), mock.patch(
            "firstboot.osinstall.common.detach_loops_on_disk"
        ), mock.patch("os.makedirs"):
            disk = partition_disk("/dev/sda", "/tmp/work")
        sgdisk = [a for a in runs if a and a[0] == "sgdisk" and any(
            str(x).startswith("--new=") for x in a
        )]
        self.assertTrue(sgdisk)
        argv = sgdisk[0]
        self.assertIn("--new=2:0:0", argv)
        self.assertNotIn("--change-name=2:spare", argv)
        self.assertFalse(any("+16M" in str(x) for x in argv))
        self.assertEqual(disk.root_dev, "/dev/sda2")
        self.assertEqual(disk.esp_dev, "/dev/sda1")
        mkfs = [a for a in runs if a and a[0] == "mkfs.ext4"]
        self.assertEqual(mkfs[0].count("-F"), 1)
        self.assertIn("-O", mkfs[0])
        self.assertIn(EXT4_GRUB_OPTS, mkfs[0])

    def test_refuses_wipe_if_casper_loop_remains(self) -> None:
        with mock.patch(
            "firstboot.osinstall.common.casper_loops_on_disk",
            return_value=["/dev/loop0"],
        ), mock.patch("firstboot.osinstall.common.run_checked") as checked:
            with self.assertRaises(OsInstallError):
                partition_disk("/dev/sda", "/tmp/work")
        checked.assert_not_called()


class GrubEfiModuleTests(unittest.TestCase):
    def test_copies_modules_from_iso_when_live_missing(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-grub-root-")
        iso = tempfile.mkdtemp(prefix="fbl-grub-iso-")
        try:
            src = os.path.join(iso, "boot", "grub", "x86_64-efi")
            os.makedirs(src)
            with open(os.path.join(src, "modinfo.sh"), "w", encoding="utf-8") as fh:
                fh.write("ok\n")
            live = "/usr/lib/grub/x86_64-efi/modinfo.sh"
            real_isfile = os.path.isfile

            def isfile(path: str) -> bool:
                if path == live:
                    return False
                return real_isfile(path)

            with mock.patch("firstboot.osinstall.casper.os.path.isfile", side_effect=isfile):
                ensure_grub_efi_modules(root, iso_mnt=iso)
            dest = os.path.join(root, "usr", "lib", "grub", "x86_64-efi", "modinfo.sh")
            self.assertTrue(os.path.isfile(dest))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(iso, ignore_errors=True)

    def test_seed_keep_list_ships_grub_efi_modules(self) -> None:
        path = os.path.join(os.path.dirname(CHOOSER_DIR), "seed", "packages", "keep.list")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("grub-efi-amd64-bin", text)


def _disk() -> InstalledDisk:
    return InstalledDisk(
        disk="/dev/sda",
        esp_dev="/dev/sda1",
        root_dev="/dev/sda2",
        esp_uuid="esp",
        root_uuid="root-uuid",
        esp_mp="/mnt/efi",
        root_mp="/mnt/root",
    )


class NvramTests(unittest.TestCase):
    def test_stale_labels_include_anaconda(self) -> None:
        self.assertIn("anaconda", STALE_EFI_LABELS)

    def test_register_os_efi_bootnext(self) -> None:
        runs: list[list[str]] = []

        def fake_run(argv, **_kwargs):
            runs.append(list(argv))
            out = ""
            if "--create" in argv:
                out = "BootCurrent: 0001\nBootOrder: 0003,0001\nBoot0003* Ubuntu\n"
            elif "-v" in argv:
                out = (
                    "Boot0001* ubuntu\tHD(1,GPT,aaa,0x800,0x100000)/"
                    "File(\\EFI\\ubuntu\\grubx64.efi)RC\n"
                )
            return mock.Mock(returncode=0, stdout=out, stderr="")

        with mock.patch("shutil.which", return_value="/usr/sbin/efibootmgr"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            register_os_efi(_disk(), "Ubuntu", r"\EFI\ubuntu\shimx64.efi")
        create = [a for a in runs if "--create" in a]
        self.assertTrue(create)
        self.assertIn(r"\EFI\ubuntu\shimx64.efi", create[0])
        self.assertTrue(any("--bootnext" in a and "0003" in a for a in runs))
        self.assertTrue(
            any("--delete-bootnum" in a and "0001" in a for a in runs),
            "firmware-recovered grubx64.efi NVRAM entry must be deleted",
        )

    def test_register_os_efi_create_failure_raises(self) -> None:
        def fake_run(argv, **_kwargs):
            if "--create" in argv:
                return mock.Mock(returncode=1, stdout="", stderr="no space")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("shutil.which", return_value="/usr/sbin/efibootmgr"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            with self.assertRaises(OsInstallError):
                register_os_efi(_disk(), "Ubuntu", r"\EFI\ubuntu\shimx64.efi")


class CasperBootloaderTests(unittest.TestCase):
    def test_overlays_signed_grub_after_grub_install(self) -> None:
        copy = mock.Mock()
        efi = tempfile.mkdtemp(prefix="fbl-efi-")
        try:
            with mock.patch("firstboot.osinstall.casper.ensure_grub_efi_modules"), mock.patch(
                "firstboot.osinstall.casper.bind_chroot", return_value=[]
            ), mock.patch("firstboot.osinstall.casper.unbind_chroot"), mock.patch(
                "firstboot.osinstall.casper.chroot_run", return_value=(0, "ok")
            ), mock.patch(
                "firstboot.osinstall.casper.copy_signed_esp_binaries", copy
            ), mock.patch("firstboot.osinstall.casper.write_esp_grub_stub"):
                install_casper_bootloader("/tmp", efi, _disk(), "/iso")
            copy.assert_called_once()
        finally:
            shutil.rmtree(efi, ignore_errors=True)

    def test_signed_esp_uses_installed_grub_not_iso_gcdx64(self) -> None:
        efi = tempfile.mkdtemp(prefix="fbl-esp-")
        signed = tempfile.mkdtemp(prefix="fbl-signed-")
        try:
            with open(os.path.join(signed, "shimx64.efi"), "wb") as fh:
                fh.write(b"SHIM")
            with open(os.path.join(signed, "grubx64.efi"), "wb") as fh:
                fh.write(b"GRUBX64-INSTALLED")
            with open(os.path.join(signed, "mmx64.efi"), "wb") as fh:
                fh.write(b"MOK")
            boot = os.path.join(efi, "EFI", "BOOT")
            os.makedirs(boot, exist_ok=True)
            with open(os.path.join(boot, "grubx64.efi"), "wb") as fh:
                fh.write(b"LEFTOVER-GRUB")
            with open(os.path.join(boot, "mmx64.efi"), "wb") as fh:
                fh.write(b"LEFTOVER-MM")
            with mock.patch("firstboot.osinstall.casper.SIGNED_EFI_DIR", signed):
                copy_signed_esp_binaries(efi, "ubuntu")
            with open(os.path.join(efi, "EFI", "ubuntu", "grubx64.efi"), "rb") as fh:
                self.assertEqual(fh.read(), b"GRUBX64-INSTALLED")
            with open(os.path.join(efi, "EFI", "ubuntu", "shimx64.efi"), "rb") as fh:
                self.assertEqual(fh.read(), b"SHIM")
            with open(os.path.join(efi, "EFI", "ubuntu", "mmx64.efi"), "rb") as fh:
                self.assertEqual(fh.read(), b"MOK")
            with open(os.path.join(boot, "BOOTX64.EFI"), "rb") as fh:
                self.assertEqual(fh.read(), b"SHIM")
            self.assertFalse(os.path.isfile(os.path.join(boot, "grubx64.efi")))
            self.assertFalse(os.path.isfile(os.path.join(boot, "mmx64.efi")))
        finally:
            shutil.rmtree(efi, ignore_errors=True)
            shutil.rmtree(signed, ignore_errors=True)

    def test_seed_ships_installed_grubx64_not_only_gcdx64(self) -> None:
        path = os.path.join(os.path.dirname(CHOOSER_DIR), "seed", "build-seed.sh")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("grubx64.efi.signed", text)
        self.assertIn("usr/share/firstboot/signed-efi", text)
        self.assertIn("install_signed_efi_into_rootfs", text)


if __name__ == "__main__":
    unittest.main()
