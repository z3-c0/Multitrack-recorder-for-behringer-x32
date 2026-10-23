import argparse
import os
import socket
import sys
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
from threading import Lock
from audio_engine import AudioEngine

MDNS_NAME = "recorder"  # advertised as http://recorder.local

RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)



app = Flask(__name__)
# manage_session=False: this app doesn't use Flask's session, and enabling
# session management trips an incompatibility between this flask-socketio
# version and newer Flask versions (RequestContext.session is read-only there).
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                     manage_session=False)
playback_thread = None
playback_running = False
playback_lock = Lock()

engine = AudioEngine(RECORDINGS_DIR)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/recordings/<path:filename>")
def recordings(filename):
    return send_from_directory(RECORDINGS_DIR, filename)

# ---------- SOCKET EVENTS ----------

@socketio.on("connect")
def handle_connect():
    emit_status()
    emit_file_list()
    emit_storage_options()

@socketio.on("disconnect")
def on_disconnect():
    global playback_running
    playback_running = False

def record_time_worker():
    while engine.rec_proc is not None:
        socketio.emit("record_time", {"record_time": engine.record_time()})
        socketio.sleep(0.25)

@socketio.on("start_record")
def start_record():
    try:
        engine.start_record()
        socketio.start_background_task(record_time_worker)
        emit_status()
        emit_file_list()
        emit_storage_options()
    except RuntimeError as e:
        emit("app_error", {"msg": str(e)})

@socketio.on("stop_record")
def stop_record():
    engine.stop_record()
    emit_status()
    emit_file_list()
    emit_storage_options()

@socketio.on("discard_record")
def discard_record():
    try:
        engine.stop_record(discard=True)
        emit_status()
        emit_file_list()
        emit_storage_options()
    except Exception as e:
        emit("app_error", {"msg": str(e)})

def playback_position_worker():
    global playback_running

    while True:
        with playback_lock:
            if not playback_running:
                break
        engine.refresh_playback_state() 
        if not engine.play_proc:
            with playback_lock:
                playback_running = False
            break

        socketio.emit("position", {
            "position": engine.position(),
            "duration": engine.duration
        })

        if engine.paused:
            socketio.sleep(0.1)
        else:
            socketio.sleep(0.25)

    socketio.emit("position", {"position": 0, "duration": engine.duration})
    emit_status()

@socketio.on("play")
def play(data):
    global playback_thread, playback_running

    try:
        engine.play(data["file"], dir=data.get("dir"))

        with playback_lock:
            if not playback_running:
                playback_running = True
                playback_thread = socketio.start_background_task(
                    playback_position_worker
                )

        emit_status()

    except Exception as e:
        emit("app_error", {"msg": str(e)})


@socketio.on("stop_play")
def stop_play():
    global playback_running

    engine.stop()

    with playback_lock:
        playback_running = False

    emit_status()

@socketio.on("seek")
def handle_seek(data):
    try:
        pos = float(data.get("pos", 0))
        engine.seek(pos)
    except Exception as e:
        emit("app_error", {"msg": str(e)})

@socketio.on("pause_play")
def pause_play():
    if engine.paused:
        engine.resume()
    else:
        engine.pause()

    emit_status()


@socketio.on("rename")
def rename(data):
    try:
        engine.rename_file(data["old"], data["new"], dir=data.get("dir"))
        emit_file_list()
        emit_status()
        emit_storage_options()
    except Exception as e:
        emit("app_error", {"msg": str(e)})



@socketio.on("delete")
def delete(data):
    try:
        engine.delete_file(data["file"], dir=data.get("dir"))
        emit_file_list()
        emit_status()
        emit_storage_options()
    except Exception as e:
        emit("app_error", {"msg": str(e)})


@socketio.on("move_file")
def move_file(data):
    try:
        engine.move_file(data["file"], data["src_dir"], data["dest_dir"])
        emit_file_list()
        emit_status()
        emit_storage_options()
    except Exception as e:
        emit("app_error", {"msg": str(e)})


@socketio.on("move_all")
def move_all(data):
    try:
        result = engine.move_all(data["dest_dir"])
        emit_file_list()
        emit_status()
        emit_storage_options()
        if result["skipped"]:
            names = ", ".join(s["name"] for s in result["skipped"])
            emit("app_error", {
                "msg": f"Moved {len(result['moved'])} recording(s). "
                       f"Skipped: {names}"
            })
    except Exception as e:
        emit("app_error", {"msg": str(e)})


@socketio.on("set_storage")
def set_storage(data):
    try:
        engine.set_storage_path(data["path"])
        emit_file_list()
        emit_status()
        emit_storage_options()
    except Exception as e:
        emit("app_error", {"msg": str(e)})


# ---------- HELPERS ----------

def safe_path(filename):
    return os.path.join(RECORDINGS_DIR, os.path.basename(filename))

def emit_status():
    socketio.emit("status", engine.status())


def emit_file_list():
    files = engine.list_recordings()
    socketio.emit("files", files)


def emit_storage_options():
    socketio.emit("storage_options", {
        "options": engine.storage_options(),
        "current_path": str(engine.recordings_dir),
    })


def storage_watch_worker():
    """Periodically re-scans mounted drives so a plugged-in USB stick shows
    up in the Settings dropdown and Recordings list without any user action.
    Cheap: no subprocess spawning, just os.path.ismount() + disk_usage()."""
    while True:
        emit_storage_options()
        emit_file_list()
        socketio.sleep(3)


def get_lan_ip():
    """Best-effort local LAN IP (no packets are actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def register_mdns(port):
    """Broadcast http://<MDNS_NAME>.local:<port> via mDNS/Zeroconf."""
    from zeroconf import Zeroconf, ServiceInfo

    ip = get_lan_ip()
    info = ServiceInfo(
        "_http._tcp.local.",
        f"{MDNS_NAME}._http._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=port,
        server=f"{MDNS_NAME}.local.",
    )
    zc = Zeroconf()
    zc.register_service(info)
    return zc


DEFAULT_LOCAL_PORT = 5000
DEFAULT_LAN_PORT = 80


def parse_args():
    parser = argparse.ArgumentParser(description="Multitrack Recorder web server")
    parser.add_argument(
        "--lan", action="store_true",
        help="Bind to 0.0.0.0 so other devices on the network can connect "
             f"(also broadcasts http://{MDNS_NAME}.local via mDNS). "
             f"Defaults to port {DEFAULT_LAN_PORT} so the URL needs no port. "
             "Without this flag, binds to 127.0.0.1 (local machine only)."
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help=f"Port to listen on. Default is {DEFAULT_LAN_PORT} with --lan, "
             f"or {DEFAULT_LOCAL_PORT} otherwise."
    )
    return parser.parse_args()


def can_bind(host, port):
    """Pre-flight check: can we actually bind this host:port? Avoids relying on
    Werkzeug's own error handling, which calls sys.exit(1) instead of raising."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
        return True, None
    except OSError as e:
        return False, e
    finally:
        s.close()


# ---------- RUN ----------
if __name__ == "__main__":
    args = parse_args()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    port = args.port if args.port is not None else (
        DEFAULT_LAN_PORT if args.lan else DEFAULT_LOCAL_PORT
    )

    ok, err = can_bind(host, port)
    if not ok:
        if isinstance(err, PermissionError) or getattr(err, "errno", None) == 13:
            print(
                f"\nERROR: Permission denied binding to port {port}.\n"
                f"Ports below 1024 need elevated privileges. Either:\n"
                f"  - run install.py (it sets up setcap so Python can bind low ports without root), or\n"
                f"  - pass a higher port explicitly, e.g.: python3 web.py --lan --port 8080\n"
            )
        else:
            print(f"\nERROR: Could not bind {host}:{port} ({err}).\n")
        sys.exit(1)

    zc = None
    if args.lan:
        try:
            zc = register_mdns(port)
            suffix = "" if port == 80 else f":{port}"
            print(f"Broadcasting as http://{MDNS_NAME}.local{suffix}")
        except Exception as e:
            print(f"mDNS broadcast failed (continuing without it): {e}")

    print(f"Starting Web Server on {host}:{port} ...")
    try:
        socketio.start_background_task(storage_watch_worker)
        socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
    finally:
        if zc:
            zc.close()
