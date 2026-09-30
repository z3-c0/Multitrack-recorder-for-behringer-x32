#!/usr/bin/env python3
"""
Install script for Multitrack Recorder (Behringer X32) on Raspberry Pi / Linux.

Run this on the device that will actually record (the Raspberry Pi / Odroid),
NOT on your dev machine, unless you also want to run the recorder there.

Usage:
    python3 install.py

What it does (safe to re-run — every step checks first, skips if already done):
  1. apt-get install: ffmpeg, alsa-utils, python3-flask-socketio
  2. pip install --user: simple-websocket, zeroconf  (from requirements.txt)
  3. setcap on the python3 binary so it can bind to port 80 without root/sudo,
     enabling manual `python3 web.py --lan` runs to serve on http://recorder.local
     with no port number needed.
  4. Add the current user to the audio/plugdev groups (needed to access the
     USB audio interface).
  5. Install + enable a systemd service (multitrack-recorder.service) that runs
     `web.py --lan` automatically on every boot, restarting it if it crashes,
     so the app is ready at http://recorder.local as soon as the Pi powers up.

Will prompt for your sudo password when needed (apt-get, setcap, usermod, systemctl).
"""
import getpass
import grp
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APT_PACKAGES = ["ffmpeg", "alsa-utils", "python3-flask-socketio"]

SERVICE_NAME = "multitrack-recorder"
SERVICE_PATH = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
SERVICE_GROUPS = ["audio", "plugdev"]


def run(cmd, **kwargs):
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)


def step(title):
    print(f"\n==> {title}")


def check_linux():
    if sys.platform != "linux":
        print("This install script targets Linux (Raspberry Pi OS / Debian / Ubuntu).")
        sys.exit(1)


def check_apt():
    if not shutil.which("apt-get"):
        print("apt-get not found. This script currently only supports Debian/Ubuntu-based "
              "systems (including Raspberry Pi OS). Install the following manually:")
        print("  - ffmpeg")
        print("  - alsa-utils")
        print("  - Python package: flask, flask-socketio, simple-websocket, zeroconf")
        sys.exit(1)


def apt_installed(pkg):
    r = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", pkg],
        capture_output=True, text=True
    )
    return r.returncode == 0 and "install ok installed" in r.stdout


def install_apt_packages():
    step("Checking system packages (ffmpeg, alsa-utils, flask-socketio)")
    missing = [p for p in APT_PACKAGES if not apt_installed(p)]

    if not missing:
        print("All required apt packages already installed.")
        return

    print(f"Installing missing packages: {', '.join(missing)}")
    run(["sudo", "apt-get", "update"], check=True)
    run(["sudo", "apt-get", "install", "-y", *missing], check=True)


def install_pip_packages():
    step("Checking Python packages (simple-websocket, zeroconf)")
    req_file = SCRIPT_DIR / "requirements.txt"

    to_install = []
    for pkg in ["simple_websocket", "zeroconf"]:
        r = subprocess.run(
            [sys.executable, "-c", f"import {pkg}"],
            capture_output=True
        )
        if r.returncode != 0:
            to_install.append(pkg)

    if not to_install:
        print("All required Python packages already installed.")
        return

    print(f"Installing missing Python packages: {', '.join(to_install)}")
    run(
        [sys.executable, "-m", "pip", "install", "--user",
         "--break-system-packages", "-r", str(req_file)],
        check=True
    )


def resolve_python_bin():
    python_bin = Path(subprocess.run(
        ["readlink", "-f", sys.executable],
        capture_output=True, text=True
    ).stdout.strip())
    return python_bin if python_bin.exists() else None


def setup_port80_capability(python_bin):
    step("Enabling port 80 without sudo (setcap on python3)")

    if not python_bin:
        print(f"Could not resolve python binary path ({sys.executable}); skipping setcap.")
        return

    r = subprocess.run(["getcap", str(python_bin)], capture_output=True, text=True)
    if "cap_net_bind_service" in r.stdout:
        print(f"{python_bin} already has cap_net_bind_service. Skipping.")
        return

    if not shutil.which("setcap"):
        print("setcap not found — installing libcap2-bin...")
        run(["sudo", "apt-get", "install", "-y", "libcap2-bin"], check=True)

    print(f"Granting {python_bin} permission to bind ports < 1024...")
    print("NOTE: this applies to ALL scripts run with this python3 binary, not just this app.")
    run(["sudo", "setcap", "cap_net_bind_service=+ep", str(python_bin)], check=True)


def ensure_user_in_groups(user):
    step(f"Checking group membership for '{user}' (audio, plugdev)")

    current_groups = {g.gr_name for g in grp.getgrall() if user in g.gr_mem}
    try:
        import pwd
        primary_gid = pwd.getpwnam(user).pw_gid
        current_groups.add(grp.getgrgid(primary_gid).gr_name)
    except (KeyError, ImportError):
        pass

    missing = [g for g in SERVICE_GROUPS if g not in current_groups]
    if not missing:
        print(f"'{user}' is already in: {', '.join(SERVICE_GROUPS)}.")
        return False

    print(f"Adding '{user}' to missing group(s): {', '.join(missing)}")
    run(["sudo", "usermod", "-aG", ",".join(missing), user], check=True)
    print("NOTE: group changes apply to new process starts (e.g. this service); "
          "no reboot needed, but an already-open shell session for this user won't see it "
          "until it logs in again.")
    return True


def install_systemd_service(user, python_bin):
    step("Installing systemd service (start on boot)")

    home = str(Path.home())
    unit_content = f"""[Unit]
Description=Multitrack Recorder for Behringer X32 (web UI)
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={SCRIPT_DIR}
Environment=HOME={home}
Environment=PYTHONUNBUFFERED=1
ExecStart={python_bin} {SCRIPT_DIR}/web.py --lan
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
"""

    if SERVICE_PATH.exists() and SERVICE_PATH.read_text() == unit_content:
        print(f"{SERVICE_PATH} already up to date. Skipping write.")
    else:
        print(f"Writing {SERVICE_PATH} ...")
        run(
            ["sudo", "tee", str(SERVICE_PATH)],
            input=unit_content, text=True, capture_output=True, check=True
        )
        run(["sudo", "systemctl", "daemon-reload"], check=True)

    return unit_content


def enable_and_start_service():
    step(f"Enabling and starting '{SERVICE_NAME}' service")
    run(["sudo", "systemctl", "enable", SERVICE_NAME], check=True)
    run(["sudo", "systemctl", "restart", SERVICE_NAME], check=True)


def main():
    check_linux()
    check_apt()

    user = getpass.getuser()
    python_bin = resolve_python_bin()

    try:
        install_apt_packages()
        install_pip_packages()
        setup_port80_capability(python_bin)
        ensure_user_in_groups(user)
        install_systemd_service(user, python_bin)
        enable_and_start_service()
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: command failed ({' '.join(e.cmd)}), exit code {e.returncode}.")
        print("Fix the issue above and re-run this script — it's safe to run multiple times.")
        sys.exit(1)

    print("\nAll set! The recorder now starts automatically on every boot.")
    print(f"  Web UI:        http://recorder.local")
    print(f"  Service status: sudo systemctl status {SERVICE_NAME}")
    print(f"  Live logs:      journalctl -u {SERVICE_NAME} -f")
    print(f"  Restart:        sudo systemctl restart {SERVICE_NAME}")
    print()
    print("You can still run it manually for testing (this won't affect the service):")
    print("  python3 web.py            # local only, http://127.0.0.1:5000")
    print("  python3 web.py --lan      # LAN-accessible, http://recorder.local")


if __name__ == "__main__":
    main()
