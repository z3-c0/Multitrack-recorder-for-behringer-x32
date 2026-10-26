# Multitrack Recorder for Behringer X32

This project is still in development so may not work as expected.  
Inspired by https://github.com/jajito/X32-Recorder/tree/main

**Multitrack-Recorder-Behringer-X32** is a Python-based wrapper around FFmpeg for Linux.  
It allows recording and playback of 16-channel audio from a Behringer X32 (or any other console acting as a multichannel audio interface) with a simple **Web UI** by Flask.

This project was primarily created to enable devices like **Odroid** or **Raspberry Pi** to stay connected to a X32 console, record live shows, or play multitrack `.wav` files for virtual soundcheck.

## Requirements

### System Dependencies
- `ffmpeg`
- `alsa-utils`
- Python 3 (Tested on 3.9)
### Python Dependencies
- `flask`
- `flask-socketio`
- `simple-websocket`
- `zeroconf`

## To Install
Run python3 install.py from the project folder  
Recorder will be available as a daemon at `http://recorder.local`  
No need to start separately  

## Check status

Status:  
`sudo systemctl status multitrack-recorder`  
Disable autostart on boot (keeps it installed, just won't launch at boot):  
`sudo systemctl disable multitrack-recorder`  
Re-enable autostart on boot:  
`sudo systemctl enable multitrack-recorder`  

Start / stop / restart:  
`sudo systemctl start multitrack-recorder`  
`sudo systemctl stop multitrack-recorder`  
`sudo systemctl restart multitrack-recorder`  

Fully remove the service:  
`sudo systemctl disable --now multitrack-recorder`  
`sudo rm /etc/systemd/system/multitrack-recorder.service`  
`sudo systemctl daemon-reload`  


## To start without installation
To run it manually (bypassing the systemd service entirely)
1. Install system packages
`sudo apt-get update`  
`sudo apt-get install ffmpeg alsa-utils`
2. Install Python dependencies  
`pip3 install flask flask-socketio simple-websocket zeroconf`
(If your system blocks global pip installs with an "externally managed environment" error, add --break-system-packages (at your own risk), or just make a quick venv:  
`python3 -m venv .venv && .venv/bin/pip install flask flask-socketio simple-websocket zeroconf`.)
3. just invoke `web.py` directly with the project's venv:

`cd /path/to/Multitrack-recorder-for-behringer-x32`  

Local only: http://127.0.0.1:5000  
`.venv/bin/python web.py` with venv or without: `python3 web.py`  
LAN-accessible: http://recorder.local (port 80)  
`.venv/bin/python web.py --lan` with venv or without: `python3 web.py --lan`  
LAN-accessible on a specific port, no sudo needed  
`.venv/bin/python web.py --lan --port 8080`  with venv or without `python3 web.py --lan --port 8080`  

No sudo required for the default or --port 8080 form. The --lan form without --port binds to port 80, which needs the setcap grant install.py already applied to .venv/bin/python - if that worked, it'll just work; if not, you'll get a permission error and should pick a port ≥1024 or run with sudo.  
One thing to watch: if the systemd service is already running, it's likely holding port 80 (or whatever you configured). Stop it first so your manual run doesn't collide:
`sudo systemctl stop multitrack-recorder`
`python3 web.py --lan`

## THIS IS EXPERIMENTAL VIBE CODED KIOSK: NOT EVER TESTED

Last gig, I had no time to check whether the Odroid had booted up, and I assumed that everything was fine as long as the web interface loaded. However, when I tried to start the recording 5 seconds before the gig started, nothing worked.  
My phone had probably just loaded a cached version of the page. This got me thinking about getting some kind of AliExpress HDMI screen that would fit in the rack, so I could at least see whether the Odroid had booted up properly and the app was running.  
This particular kiosk runs instead of a desktop session.  

## Optional: Kiosk Display

If the device has a screen attached (e.g. a small panel), you can run a
fullscreen status display instead of a desktop session. It shows connection /
recording / playback status and the recordings list, read-only, always on top,
starting automatically on boot.

There are **two alternative ways to do this**, aimed at different starting
points:

- **Native app** (`install_kiosk.py`): for a device that boots to a plain
  text console with no desktop at all (the setup this project was originally
  built for). It disables any existing desktop display manager, sets up tty
  autologin, and runs a PyQt5 app fullscreen via a bare `startx` — a full
  replacement for a desktop session.
- **Browser-based** (`install_kiosk_web.py`): for a device that already boots
  into a desktop session with autologin (e.g. Raspberry Pi OS Desktop set up
  via `raspi-config`). It makes **no changes to display managers, boot
  targets, or autologin** — it just adds a per-user autostart entry
  (`~/.config/autostart/multitrack-recorder-kiosk.desktop`) that launches
  Chromium in `--kiosk` mode, pointed at the recorder's own `/kiosk` page,
  once you're logged into the desktop you already have. No PyQt5/venv needed,
  and easier to customize since the page is plain HTML/CSS
  (`templates/kiosk.html`, `static/css/kiosk.css`, `static/js/kiosk.js`).

Pick whichever matches how the device currently boots — they don't conflict
with each other, but running the native app's installer on a desktop-booting
device will disable that desktop (which the browser option deliberately
avoids).

### Native app (replaces a desktop/console boot entirely)

Run on the device with the screen attached:
`python3 install_kiosk.py`

This installs Xorg + PyQt5, sets up autologin + `startx` on boot, and launches
`kiosk_app.py` fullscreen with no window manager or desktop environment.

To try it without installing (requires `pip install PyQt5 "python-socketio[client]"`):
`python3 kiosk_app.py --windowed`

To uninstall (recorder service is unaffected; the script prints the exact
commands for your machine, including restoring the desktop display
manager/boot target if it disabled one):
```
sudo rm /etc/systemd/system/getty@tty1.service.d/autologin.conf
sudo systemctl daemon-reload && sudo systemctl restart getty@tty1
# then remove the "multitrack-recorder kiosk autostart" block from ~/.bash_profile
rm ~/.xinitrc
# if the installer disabled a desktop display manager / changed the boot target:
sudo systemctl enable --now <display-manager>.service
sudo systemctl set-default graphical.target
```

### Browser-based (autostarts inside an existing desktop session)

Requires the device to already boot into a desktop session with autologin
enabled (e.g. via `raspi-config` → System Options → Boot / Auto Login →
"Desktop Autologin"). This script won't set that up for you — if the device
currently boots to a plain text console, use the native app option above
instead.

Make sure the recorder service is already installed and running
(`python3 install.py`), then run on the device with the screen attached:
`python3 install_kiosk_web.py`

This installs Chromium and writes
`~/.config/autostart/multitrack-recorder-kiosk.desktop`, which launches
Chromium in `--kiosk` mode pointed at `http://localhost/kiosk` the next time
you log into the desktop. If the server runs on a non-default port, pass it
explicitly:
`python3 install_kiosk_web.py --url http://localhost:8080/kiosk`

To try the page without installing the kiosk autostart, just visit `/kiosk`
on the running server from any browser, e.g. `http://recorder.local/kiosk`.

To uninstall: `rm ~/.config/autostart/multitrack-recorder-kiosk.desktop`