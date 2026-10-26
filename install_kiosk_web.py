#!/usr/bin/env python3
"""
Optional installer for the browser-based kiosk status display (served by
web.py at /kiosk).

Run this on the device that has a screen physically attached (e.g. a small
1920x440 panel) AND that already boots into a desktop session (e.g. Raspberry
Pi OS Desktop with desktop autologin enabled via raspi-config). This script
does NOT touch display managers, boot targets, or tty autologin — it only
adds a per-user autostart entry that launches Chromium in kiosk mode once
you're logged into the desktop. If this device currently boots to a plain
text console with no desktop environment at all, this won't autostart
anything; use install_kiosk.py (the native PyQt5 app) instead, which handles
that case via tty autologin + bare startx.

It is independent of install.py — the recorder service should already be
installed and running, since this just points a kiosk-mode browser at it.

What it does (safe to re-run — every step checks first, skips if already done):
  1. apt-get install Chromium (tries the 'chromium' package first, falls back
     to 'chromium-browser' since the package name differs between
     Debian/Ubuntu and Raspberry Pi OS)
  2. writes ~/.config/autostart/multitrack-recorder-kiosk.desktop, an XDG
     autostart entry that launches Chromium in --kiosk mode pointed at the
     recorder's /kiosk page as soon as you log into the desktop

To uninstall, just delete that one .desktop file — nothing else on the
system is touched.

Will prompt for your sudo password when needed (apt-get).
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import kiosk_common as kc

CHROMIUM_CANDIDATES = ["chromium", "chromium-browser"]

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_PATH = AUTOSTART_DIR / "multitrack-recorder-kiosk.desktop"

DEFAULT_URL = "http://localhost/kiosk"


def install_chromium():
    kc.step("Checking for Chromium")

    for pkg in CHROMIUM_CANDIDATES:
        if kc.apt_installed(pkg):
            print(f"{pkg} already installed.")
            return pkg

    kc.run(["sudo", "apt-get", "update"], check=True)
    for pkg in CHROMIUM_CANDIDATES:
        print(f"Trying to install '{pkg}'...")
        result = kc.run(["sudo", "apt-get", "install", "-y", pkg])
        if result.returncode == 0:
            return pkg
        print(f"'{pkg}' not available, trying next candidate...")

    print("ERROR: could not install Chromium under any known package name "
          f"({', '.join(CHROMIUM_CANDIDATES)}). Install it manually and re-run.")
    sys.exit(1)


def resolve_chromium_binary(pkg):
    for name in ["chromium", "chromium-browser"]:
        path = shutil.which(name)
        if path:
            return path
    print(f"ERROR: installed package '{pkg}' but no chromium/chromium-browser binary found on PATH.")
    sys.exit(1)


def write_autostart_entry(chromium_bin, url):
    kc.step("Writing desktop autostart entry")

    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)

    exec_line = (
        f"{chromium_bin} --kiosk --noerrdialogs --disable-infobars "
        f"--incognito --no-first-run {url}"
    )
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Multitrack Recorder Kiosk\n"
        f"Exec={exec_line}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=true\n"
    )

    if AUTOSTART_PATH.exists() and AUTOSTART_PATH.read_text() == content:
        print(f"{AUTOSTART_PATH} already up to date. Skipping write.")
        return

    AUTOSTART_PATH.write_text(content)
    print(f"Wrote {AUTOSTART_PATH}")


def parse_args():
    parser = argparse.ArgumentParser(description="Install the browser-based kiosk display")
    parser.add_argument("--url", default=DEFAULT_URL,
                         help=f"URL to open in kiosk mode (default: {DEFAULT_URL}). "
                              "Change this if web.py is running on a non-default port.")
    return parser.parse_args()


def main():
    args = parse_args()

    kc.check_linux()
    kc.check_apt(CHROMIUM_CANDIDATES)

    try:
        chromium_pkg = install_chromium()
        chromium_bin = resolve_chromium_binary(chromium_pkg)
        write_autostart_entry(chromium_bin, args.url)
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: command failed ({' '.join(str(c) for c in e.cmd)}), exit code {e.returncode}.")
        print("Fix the issue above and re-run this script — it's safe to run multiple times.")
        sys.exit(1)

    print("\nAll set! Next time you log into the desktop, Chromium will launch")
    print(f"fullscreen in kiosk mode, pointed at {args.url}.")
    print()
    print("Make sure the recorder service is installed and running (see install.py) —")
    print("this kiosk just displays its /kiosk page, it doesn't start the server itself.")
    print()
    print("This only works if the device already boots into a desktop session with")
    print("autologin enabled. If it boots to a plain text console, this autostart entry")
    print("will never run — use install_kiosk.py instead for that case.")
    print()
    print("To test right now without logging out: just run the command yourself:")
    print(f"  {chromium_bin} --kiosk {args.url}")
    print()
    print("To uninstall:")
    print(f"  rm {AUTOSTART_PATH}")


if __name__ == "__main__":
    main()
