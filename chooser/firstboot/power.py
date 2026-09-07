"""Power Off / Restart confirm copy. GNOME-style countdown, 30 seconds."""

from __future__ import annotations

from firstboot.i18n import _

POWER_DELAY_SECONDS = 30


def countdown_body(action: str, remaining: int) -> str:
    """Body text for the Power Off / Restart confirm dialog."""
    n = max(0, int(remaining))
    restart = action == "restart"
    if n == 1:
        if restart:
            return _("The computer will restart automatically in 1 second.")
        return _("The computer will shut down automatically in 1 second.")
    if restart:
        return _("The computer will restart automatically in {n} seconds.").format(n=n)
    return _("The computer will shut down automatically in {n} seconds.").format(n=n)
