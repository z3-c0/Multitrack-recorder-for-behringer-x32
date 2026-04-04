import os
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
from threading import Lock
from audio_engine import AudioEngine
RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)



app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading"
                    )
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

@socketio.on("disconnect")
def on_disconnect():
    global playback_running
    playback_running = False

@socketio.on("start_record")
def start_record():
    try:
        engine.start_record()
        emit_status()
        emit_file_list()
    except RuntimeError as e:
        emit("app_error", {"msg": str(e)})

@socketio.on("stop_record")
def stop_record():
    engine.stop_record()
    emit_status()
    emit_file_list()

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
        engine.play(data["file"])

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
        engine.rename_file(data["old"], data["new"])
        emit_file_list()
        emit_status()
    except Exception as e:
        emit("app_error", {"msg": str(e)})



@socketio.on("delete")
def delete(data):
    try:
        engine.delete_file(data["file"])
        emit_file_list()
        emit_status()
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



# ---------- RUN ----------
if __name__ == "__main__":
    print("Starting Web Server...")
    socketio.run(app, host="127.0.0.1", port=5000, debug=False)
