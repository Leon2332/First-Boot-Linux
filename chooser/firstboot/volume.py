"""Output volume. Pulse/PipeWire via pactl when present; otherwise memory."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class VolumeState:
    level: int
    muted: bool

    @property
    def output(self) -> int:
        return 0 if self.muted else self.level

    @property
    def icon(self) -> str:
        if self.output == 0:
            return "audio-volume-muted-symbolic.svg"
        return "audio-volume-medium-symbolic.svg"


class Volume:
    def get(self) -> VolumeState:
        raise NotImplementedError

    def set_level(self, level: int) -> VolumeState:
        raise NotImplementedError

    def set_muted(self, muted: bool) -> VolumeState:
        raise NotImplementedError

    def toggle_mute(self) -> VolumeState:
        st = self.get()
        if st.output == 0:
            if st.level <= 0:
                self.set_level(70)
            return self.set_muted(False)
        return self.set_muted(True)


class MemoryVolume(Volume):
    def __init__(self, level: int = 70, muted: bool = False) -> None:
        self._state = VolumeState(level=clamp_level(level), muted=muted)

    def get(self) -> VolumeState:
        return VolumeState(self._state.level, self._state.muted)

    def set_level(self, level: int) -> VolumeState:
        n = clamp_level(level)
        self._state = VolumeState(level=n, muted=n == 0)
        return self.get()

    def set_muted(self, muted: bool) -> VolumeState:
        if not muted and self._state.level <= 0:
            self._state = VolumeState(70, False)
        else:
            self._state = VolumeState(self._state.level, muted)
        return self.get()


class PactlVolume(Volume):
    def get(self) -> VolumeState:
        vol = _pactl(["get-sink-volume", "@DEFAULT_SINK@"])
        mute = _pactl(["get-sink-mute", "@DEFAULT_SINK@"])
        return VolumeState(parse_pactl_volume(vol), parse_pactl_mute(mute))

    def set_level(self, level: int) -> VolumeState:
        n = clamp_level(level)
        _pactl(["set-sink-volume", "@DEFAULT_SINK@", f"{n}%"])
        if n == 0:
            _pactl(["set-sink-mute", "@DEFAULT_SINK@", "1"])
        else:
            _pactl(["set-sink-mute", "@DEFAULT_SINK@", "0"])
        return self.get()

    def set_muted(self, muted: bool) -> VolumeState:
        if not muted:
            cur = self.get()
            if cur.level <= 0:
                _pactl(["set-sink-volume", "@DEFAULT_SINK@", "70%"])
        _pactl(["set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"])
        return self.get()


def clamp_level(level: int) -> int:
    return max(0, min(100, int(level)))


def parse_pactl_volume(text: str) -> int:
    matches = re.findall(r"(\d+)%", text)
    if not matches:
        return 0
    return clamp_level(int(matches[0]))


def parse_pactl_mute(text: str) -> bool:
    return "yes" in text.lower()


def _pactl(args: list[str]) -> str:
    proc = subprocess.run(
        ["pactl", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=0.4,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "pactl failed").strip())
    return proc.stdout


def get_volume_backend() -> Volume:
    if not shutil.which("pactl"):
        return MemoryVolume()
    backend = PactlVolume()
    try:
        backend.get()
    except Exception:
        return MemoryVolume()
    return backend
