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