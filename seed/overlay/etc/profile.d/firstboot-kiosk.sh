# Start the First Boot kiosk on the first virtual terminal only.
# Sourced from login shells. exec replaces the shell so cage owns the session.

if [ -n "${FIRSTBOOT_NO_KIOSK:-}" ]; then
  return 0 2>/dev/null || exit 0
fi

if [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]; then
  return 0 2>/dev/null || exit 0
fi

[ "$(id -un 2>/dev/null)" = firstboot ] || return 0 2>/dev/null || exit 0

tty=$(tty 2>/dev/null) || return 0 2>/dev/null || exit 0
[ "$tty" = "/dev/tty1" ] || return 0 2>/dev/null || exit 0

[ -x /usr/bin/firstboot-session ] || return 0 2>/dev/null || exit 0

exec /usr/bin/firstboot-session
