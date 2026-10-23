#!/usr/bin/env python3
"""
Install script for Multitrack Recorder (Behringer X32) on Raspberry Pi / Linux.

Run this on the device that will actually record (the Raspberry Pi / Odroid),
NOT on your dev machine, unless you also want to run the recorder there.

Usage:
    python3 install.py

What it does (safe to re-run — every step checks first, skips if already done):
  1. apt-get install: ffmpeg, alsa-utils, python3-venv, libcap2-bin
  2. creates a project-local virtual environment at .venv (built with --copies,
     so its python binary is a real file, never a symlink back to the system
     interpreter — symlinks can't be setcap'd)
  3. installs Python dependencies (requirements.txt + flask/flask-socketio)
     into that venv
  4. best-effort setcap on the venv's python so it can bind to port 80 without
     root/sudo, enabling manual `.venv/bin/python web.py --lan` runs to serve
     on http://recorder.local with no port number needed. This step is purely
     a convenience for manual testing — if it fails (e.g. symlink, unsupported
     filesystem), it's skipped with a warning rather than aborting the install,
     because...
  5. ...the systemd service (installed in step 7) grants port 80 access via
     AmbientCapabilities, independent of setcap/filesystem support. That's the
     real, supported way this app binds to port 80.
  6. adds the current user to the audio / plugdev groups (needed to access the
     USB audio interface)
  7. installs and enables a systemd service (multitrack-recorder.service) that
     runs `web.py --lan` automatically on every boot, restarting it if it
     crashes, so the app is ready at http://recorder.local as soon as the
     device powers up.

Will prompt for your sudo password when needed (apt-get, setcap, usermod, systemctl).
"""
import getpass
import grp
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = SCRIPT_DIR / ".venv"

SERVICE_NAME = "multitrack-recorder"
SERVICE_PATH = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
SERVICE_GROUPS = ["audio", "plugdev"]

APT_PACKAGES = [
    "ffmpeg",
    "alsa-utils",
    "python3-venv",
    "libcap2-bin",
]


def run(cmd, **kwargs):
    print(f"$ {' '.join(str(part) for part in cmd)}")
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
        print("  - Python 3 venv module")
        sys.exit(1)


def apt_installed(pkg):
    r = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", pkg],
        capture_output=True, text=True
    )
    return r.returncode == 0 and "install ok installed" in r.stdout


def install_apt_packages():
    step("Checking system packages (ffmpeg, alsa-utils, venv, libcap2-bin)")
    missing = [p for p in APT_PACKAGES if not apt_installed(p)]

    if not missing:
        print("All required apt packages already installed.")
        return

    print(f"Installing missing packages: {', '.join(missing)}")
    run(["sudo", "apt-get", "update"], check=True)
    run(["sudo", "apt-get", "install", "-y", *missing], check=True)


def ensure_virtualenv():
    step("Creating project virtual environment (.venv, with --copies)")

    py_bin = VENV_DIR / "bin" / "python"

    if VENV_DIR.exists():
        # A venv built without --copies (or inherited from a broken earlier
        # attempt) just symlinks back to the system python. setcap refuses to
        # touch symlinks, so rebuild it properly rather than fighting that.
        if py_bin.exists() and py_bin.is_symlink():
            print("Existing venv is symlink-based; rebuilding it with --copies.")
            shutil.rmtree(VENV_DIR)

    if not VENV_DIR.exists():
        run([sys.executable, "-m", "venv", "--copies", str(VENV_DIR)], check=True)

    if not py_bin.exists():
        print(f"Virtualenv python not found at {py_bin}")
        sys.exit(1)

    # Old/bundled pip can be too old to install some wheels cleanly; upgrading
    # inside the venv is cheap and avoids a whole class of install failures.
    run([str(py_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    req_file = SCRIPT_DIR / "requirements.txt"
    if req_file.exists():
        run([str(py_bin), "-m", "pip", "install", "-r", str(req_file)], check=True)

    # Flask is required by the app itself and is not always in requirements.txt
    run([str(py_bin), "-m", "pip", "install", "flask", "flask-socketio"], check=True)

    return str(py_bin)


def maybe_setcap_for_manual_runs(python_bin):
    """
    Best-effort only. Lets you run `.venv/bin/python web.py --lan` directly on
    port 80 without sudo. Never fatal: the systemd service (AmbientCapabilities)
    is what actually matters for the real deployment, and doesn't depend on this
    succeeding.
    """
    step("Enabling port 80 for manual runs (setcap on venv python)")

    p = Path(python_bin)
    if not p.exists():
        print(f"Python binary not found: {p}; skipping setcap.")
        return

    # setcap refuses to operate on symlinks — skip rather than fail.
    if p.is_symlink():
        print(f"Skipping setcap for symlinked Python: {p}")
        return

    real = p.resolve(strict=False)
    if str(real) in {"/usr/bin/python3", "/usr/local/bin/python3"}:
        print(f"Skipping setcap for system Python: {real}")
        print("Port 80 will be handled by the systemd service via AmbientCapabilities=CAP_NET_BIND_SERVICE.")
        return

    result = subprocess.run(["getcap", str(p)], capture_output=True, text=True)
    if "cap_net_bind_service" in result.stdout:
        print(f"{p} already has cap_net_bind_service. Skipping.")
        return

    if not shutil.which("setcap"):
        print("setcap not found; installing libcap2-bin...")
        run(["sudo", "apt-get", "install", "-y", "libcap2-bin"], check=True)

    print(f"Granting {p} permission to bind ports below 1024...")
    try:
        run(["sudo", "setcap", "cap_net_bind_service=+ep", str(p)], check=True)
    except subprocess.CalledProcessError as e:
        print(f"WARNING: setcap failed (exit {e.returncode}); skipping.")
        print("This is only needed for manual `--lan` runs on port 80 without sudo.")
        print("The systemd service does not need this — it uses AmbientCapabilities instead.")


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

    try:
        install_apt_packages()
        python_bin = ensure_virtualenv()
        maybe_setcap_for_manual_runs(python_bin)  # best-effort, never fatal
        ensure_user_in_groups(user)
        install_systemd_service(user, python_bin)
        enable_and_start_service()
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: command failed ({' '.join(str(c) for c in e.cmd)}), exit code {e.returncode}.")
        print("Fix the issue above and re-run this script — it's safe to run multiple times.")
        sys.exit(1)

    print("\nAll set! The recorder now starts automatically on every boot.")
    print(f"  Web UI:        http://recorder.local")
    print(f"  Service status: sudo systemctl status {SERVICE_NAME}")
    print(f"  Live logs:      journalctl -u {SERVICE_NAME} -f")
    print(f"  Restart:        sudo systemctl restart {SERVICE_NAME}")
    print()
    print("You can still run it manually for testing (this won't affect the service):")
    print(f"  {VENV_DIR}/bin/python web.py            # local only, http://127.0.0.1:5000")
    print(f"  {VENV_DIR}/bin/python web.py --lan      # LAN-accessible, http://recorder.local")


if __name__ == "__main__":
    main()
