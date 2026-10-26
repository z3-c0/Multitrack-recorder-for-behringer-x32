#!/usr/bin/env python3
"""
Optional installer for the native kiosk status display (kiosk_app.py).

Run this on the device that has a screen physically attached (e.g. a small
1920x440 panel). It is independent of install.py / the recorder service —
skip this entirely on headless deployments.

This is one of two alternative kiosk options — see install_kiosk_web.py for a
browser/Chromium-based alternative that doesn't need PyQt5. Install only one;
both write to ~/.xinitrc and whichever runs last wins.

What it does (safe to re-run — every step checks first, skips if already done):
  1. apt-get install: xserver-xorg, xinit, x11-xserver-utils, python3-pyqt5
  2. detects and disables any enabled desktop display manager (gdm/lightdm/
     sddm/...) and switches the default boot target from graphical.target to
     multi-user.target — otherwise the desktop login screen/session would
     fight the kiosk for the screen (previous state is recorded so it can be
     restored, see the uninstall instructions printed at the end)
  3. creates a project-local virtual environment at .venv-kiosk, built with
     --system-site-packages so it can import the apt-installed PyQt5 bindings
     (PyQt5 is painful to build from pip on a Pi; apt's build is the
     supported path), then pip-installs python-socketio[client] into it
  4. writes ~/.xinitrc to launch kiosk_app.py fullscreen as the only thing
     running under X (no window manager, no desktop)
  5. appends an autostart snippet to ~/.bash_profile that runs `startx` on
     login on tty1 if no X session is already active
  6. configures autologin on tty1 via a systemd drop-in, so the device boots
     straight to a logged-in shell, which bash_profile turns into `startx`,
     which turns into the fullscreen app — no display manager involved

If kiosk_app.py ever exits or crashes, X exits, the shell returns, and the
getty (restarted by systemd) re-triggers autologin -> startx -> the app again.

Note: if a desktop session is currently active on this device's screen, step 2
disables it immediately (not just on next boot) — the screen will go blank/
drop to a console right away.

Will prompt for your sudo password when needed (apt-get, systemctl).
"""
import getpass
import subprocess
import sys
from pathlib import Path

import kiosk_common as kc

SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = SCRIPT_DIR / ".venv-kiosk"

APT_PACKAGES = [
    "xserver-xorg",
    "xinit",
    "x11-xserver-utils",
    "python3-pyqt5",
]

STATE_PATH = SCRIPT_DIR / ".kiosk_install_state.json"


def ensure_virtualenv():
    kc.step("Creating kiosk virtual environment (.venv-kiosk, with --system-site-packages)")

    py_bin = VENV_DIR / "bin" / "python"

    if not VENV_DIR.exists():
        kc.run([sys.executable, "-m", "venv", "--system-site-packages", str(VENV_DIR)], check=True)

    if not py_bin.exists():
        print(f"Virtualenv python not found at {py_bin}")
        sys.exit(1)

    kc.run([str(py_bin), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    kc.run([str(py_bin), "-m", "pip", "install", "python-socketio[client]"], check=True)

    # Sanity check: PyQt5 must be importable via the inherited system site-packages.
    check = subprocess.run([str(py_bin), "-c", "import PyQt5.QtWidgets"], capture_output=True, text=True)
    if check.returncode != 0:
        print("WARNING: PyQt5 is not importable from the kiosk venv. "
              "python3-pyqt5 may not be installed for the system Python used to build this venv.")
        print(check.stderr)

    return str(py_bin)


def main():
    kc.check_linux()
    kc.check_apt(APT_PACKAGES)

    user = getpass.getuser()

    try:
        kc.install_apt_packages(APT_PACKAGES, "xorg, xinit, PyQt5")
        kc.disable_desktop_session(STATE_PATH)
        python_bin = ensure_virtualenv()
        kc.write_xinitrc(f"exec {python_bin} {SCRIPT_DIR}/kiosk_app.py")
        kc.append_bash_profile_autostart()
        kc.configure_autologin(user)
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: command failed ({' '.join(str(c) for c in e.cmd)}), exit code {e.returncode}.")
        print("Fix the issue above and re-run this script — it's safe to run multiple times.")
        sys.exit(1)

    state = kc.load_state(STATE_PATH)

    print("\nAll set! On next boot, tty1 will auto-login and launch straight into the")
    print("fullscreen kiosk display (no desktop environment involved).")
    print()
    print("To test right now without rebooting:")
    print("  startx")
    print()
    print("If the kiosk app ever gets stuck and you need a normal shell:")
    print("  Ctrl+Alt+F2 switches to another virtual terminal (tty2) for a normal login.")
    print()
    print("To uninstall the kiosk autostart (recorder service is unaffected):")
    kc.print_uninstall_instructions(state, STATE_PATH)


if __name__ == "__main__":
    main()
