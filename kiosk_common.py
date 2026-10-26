#!/usr/bin/env python3
"""
Shared helpers for the kiosk installers (install_kiosk.py / install_kiosk_web.py).

Both installers boot the device straight into a fullscreen kiosk instead of a
desktop session, differing only in what actually runs under X (a native PyQt
app vs. a kiosk-mode browser). Everything about getting X running on tty1 at
boot — disabling any desktop display manager, autologin, autostarting startx —
is identical between the two, so it lives here once.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

GETTY_OVERRIDE_DIR = Path("/etc/systemd/system/getty@tty1.service.d")
GETTY_OVERRIDE_PATH = GETTY_OVERRIDE_DIR / "autologin.conf"

BASH_PROFILE_MARKER = "# multitrack-recorder kiosk autostart"

KNOWN_DISPLAY_MANAGERS = ["gdm3", "gdm", "lightdm", "sddm", "lxdm", "nodm", "xdm"]


def run(cmd, **kwargs):
    print(f"$ {' '.join(str(part) for part in cmd)}")
    return subprocess.run(cmd, **kwargs)


def step(title):
    print(f"\n==> {title}")


def check_linux():
    if sys.platform != "linux":
        print("This install script targets Linux (Raspberry Pi OS / Debian / Ubuntu).")
        sys.exit(1)


def check_apt(required_packages):
    if not shutil.which("apt-get"):
        print("apt-get not found. This script currently only supports Debian/Ubuntu-based "
              "systems (including Raspberry Pi OS). Install the following manually:")
        for pkg in required_packages:
            print(f"  - {pkg}")
        sys.exit(1)


def apt_installed(pkg):
    r = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", pkg],
        capture_output=True, text=True
    )
    return r.returncode == 0 and "install ok installed" in r.stdout


def install_apt_packages(packages, description):
    step(f"Checking system packages ({description})")
    missing = [p for p in packages if not apt_installed(p)]

    if not missing:
        print("All required apt packages already installed.")
        return

    print(f"Installing missing packages: {', '.join(missing)}")
    run(["sudo", "apt-get", "update"], check=True)
    run(["sudo", "apt-get", "install", "-y", *missing], check=True)


def load_state(state_path):
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except Exception:
            return {}
    return {}


def save_state(state_path, state):
    state_path.write_text(json.dumps(state, indent=2))


def active_display_manager():
    """Return the unit name of the currently enabled display-manager, or None.
    display-manager.service is a symlink alias systemd maintains to whichever
    DM is actually configured, so this works regardless of distro/DM choice."""
    r = subprocess.run(
        ["systemctl", "show", "-p", "Id", "display-manager.service"],
        capture_output=True, text=True
    )
    if r.returncode == 0 and "=" in r.stdout:
        unit = r.stdout.strip().split("=", 1)[1]
        if unit:
            return unit

    for dm in KNOWN_DISPLAY_MANAGERS:
        r = subprocess.run(
            ["systemctl", "is-enabled", f"{dm}.service"],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.strip() == "enabled":
            return f"{dm}.service"
    return None


def disable_desktop_session(state_path):
    """A desktop display manager boots to graphical.target and grabs the
    screen before tty1's getty/startx ever gets a chance to run — it would
    fight the kiosk for the display rather than being replaced by it. Detect
    and disable it, and switch the default boot target to multi-user.target
    (console-only), recording what was changed so it can be undone later."""
    step("Checking for a desktop display manager")

    state = load_state(state_path)

    dm_unit = active_display_manager()
    if dm_unit:
        print(f"Found active display manager: {dm_unit}. Disabling it.")
        run(["sudo", "systemctl", "disable", "--now", dm_unit], check=True)
        state["disabled_display_manager"] = dm_unit
    else:
        print("No desktop display manager is enabled. Nothing to disable.")

    r = subprocess.run(["systemctl", "get-default"], capture_output=True, text=True)
    current_target = r.stdout.strip()
    if current_target and current_target != "multi-user.target":
        print(f"Switching default boot target from {current_target} to multi-user.target.")
        state.setdefault("previous_default_target", current_target)
        run(["sudo", "systemctl", "set-default", "multi-user.target"], check=True)
    else:
        print("Default boot target is already multi-user.target.")

    save_state(state_path, state)


def write_xinitrc(exec_line):
    step("Writing ~/.xinitrc")

    xinitrc = Path.home() / ".xinitrc"
    content = (
        "xset s off\n"
        "xset -dpms\n"
        "xset s noblank\n"
        f"{exec_line}\n"
    )

    if xinitrc.exists() and xinitrc.read_text() == content:
        print(f"{xinitrc} already up to date. Skipping write.")
        return

    xinitrc.write_text(content)
    print(f"Wrote {xinitrc}")


def append_bash_profile_autostart():
    step("Checking ~/.bash_profile for kiosk autostart")

    bash_profile = Path.home() / ".bash_profile"
    snippet = (
        f"\n{BASH_PROFILE_MARKER}\n"
        'if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then\n'
        "    startx -- -nocursor\n"
        "fi\n"
    )

    existing = bash_profile.read_text() if bash_profile.exists() else ""
    if BASH_PROFILE_MARKER in existing:
        print(f"{bash_profile} already has the kiosk autostart snippet. Skipping.")
        return

    with bash_profile.open("a") as f:
        f.write(snippet)
    print(f"Appended kiosk autostart snippet to {bash_profile}")


def configure_autologin(user):
    step(f"Configuring tty1 autologin for '{user}'")

    override_content = (
        "[Service]\n"
        "ExecStart=\n"
        f"ExecStart=-/sbin/agetty --autologin {user} --noclear %I $TERM\n"
    )

    if GETTY_OVERRIDE_PATH.exists() and GETTY_OVERRIDE_PATH.read_text() == override_content:
        print(f"{GETTY_OVERRIDE_PATH} already up to date. Skipping.")
        return

    run(["sudo", "mkdir", "-p", str(GETTY_OVERRIDE_DIR)], check=True)
    run(
        ["sudo", "tee", str(GETTY_OVERRIDE_PATH)],
        input=override_content, text=True, capture_output=True, check=True
    )
    run(["sudo", "systemctl", "daemon-reload"], check=True)
    run(["sudo", "systemctl", "restart", "getty@tty1"], check=True)


def print_uninstall_instructions(state, extra_state_path):
    print(f"  sudo rm {GETTY_OVERRIDE_PATH}")
    print("  sudo systemctl daemon-reload && sudo systemctl restart getty@tty1")
    print(f"  Remove the '{BASH_PROFILE_MARKER}' block from ~/.bash_profile")
    print("  rm ~/.xinitrc")
    if state.get("disabled_display_manager"):
        print(f"  sudo systemctl enable --now {state['disabled_display_manager']}  # restore desktop login")
    if state.get("previous_default_target"):
        print(f"  sudo systemctl set-default {state['previous_default_target']}")
    if state:
        print(f"  rm {extra_state_path}")
