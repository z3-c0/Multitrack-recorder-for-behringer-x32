#!/usr/bin/env python3
"""
Native fullscreen status display for Multitrack Recorder.

Connects as a Socket.IO client to the already-running web.py server and shows
live connection / recording / playback status plus the recordings list. Pure
status display, no controls — use the web UI for that.

Usage:
    python3 kiosk_app.py                 # fullscreen, borderless, always-on-top
    python3 kiosk_app.py --windowed      # resizable window, for dev/testing
    python3 kiosk_app.py --url http://127.0.0.1:8080
"""
import argparse
import sys
from threading import Thread

import socketio
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFrame, QSizePolicy
)

DEFAULT_URL = "http://127.0.0.1"


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def human_time(seconds):
    seconds = max(0, int(seconds or 0))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


class Bridge(QObject):
    """Socket.IO callbacks fire on a background thread; re-emit as Qt signals
    so all UI updates happen on the main thread."""
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    status = pyqtSignal(dict)
    files = pyqtSignal(list)


class SocketClient:
    def __init__(self, url, bridge: Bridge):
        self.url = url
        self.bridge = bridge
        self.sio = socketio.Client(reconnection=True, reconnection_delay=1,
                                    reconnection_delay_max=5)

        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("status", self._on_status)
        self.sio.on("files", self._on_files)

    def _on_connect(self):
        self.bridge.connected.emit()

    def _on_disconnect(self):
        self.bridge.disconnected.emit()

    def _on_status(self, data):
        self.bridge.status.emit(data)

    def _on_files(self, data):
        self.bridge.files.emit(data)

    def run_forever(self):
        while True:
            try:
                self.sio.connect(self.url, wait_timeout=10)
                self.sio.wait()
            except Exception:
                pass
            # sio.wait() returns after a dropped connection; retry loop keeps
            # trying rather than exiting the app if the server isn't up yet.
            self.sio.sleep(2)


class StatPill(QFrame):
    def __init__(self, label_text):
        super().__init__()
        self.setObjectName("pill")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(2)

        self.title = QLabel(label_text)
        self.title.setObjectName("pillTitle")
        self.value = QLabel("—")
        self.value.setObjectName("pillValue")

        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, text):
        self.value.setText(text)


class KioskWindow(QWidget):
    def __init__(self, url):
        super().__init__()
        self.setWindowTitle("Multitrack Recorder")
        self._build_ui()
        self._apply_styles()

        self.bridge = Bridge()
        self.bridge.connected.connect(self.on_connected)
        self.bridge.disconnected.connect(self.on_disconnected)
        self.bridge.status.connect(self.on_status)
        self.bridge.files.connect(self.on_files)

        self.client = SocketClient(url, self.bridge)
        self.thread = Thread(target=self.client.run_forever, daemon=True)
        self.thread.start()

        self.on_disconnected()  # start in "offline" state until connect fires

    # ---------- UI construction ----------

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(24)

        # ----- Left: status -----
        left = QVBoxLayout()
        left.setSpacing(10)

        top_row = QHBoxLayout()
        self.conn_dot = QLabel("●")
        self.conn_dot.setObjectName("connDot")
        self.conn_text = QLabel("Server offline")
        self.conn_text.setObjectName("connText")
        top_row.addWidget(self.conn_dot)
        top_row.addWidget(self.conn_text)
        top_row.addStretch(1)
        left.addLayout(top_row)

        self.device_label = QLabel("Console: —")
        self.device_label.setObjectName("deviceLabel")
        left.addWidget(self.device_label)

        pills_row = QHBoxLayout()
        pills_row.setSpacing(16)
        self.rec_pill = StatPill("RECORDING")
        self.play_pill = StatPill("PLAYBACK")
        self.storage_pill = StatPill("STORAGE")
        pills_row.addWidget(self.rec_pill)
        pills_row.addWidget(self.play_pill)
        pills_row.addWidget(self.storage_pill)
        left.addLayout(pills_row)

        left.addStretch(1)

        left_wrap = QFrame()
        left_wrap.setLayout(left)
        left_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(left_wrap, 2)

        # ----- Right: recordings list -----
        right = QVBoxLayout()
        right.setSpacing(8)

        right_title = QLabel("RECORDINGS")
        right_title.setObjectName("sectionTitle")
        right.addWidget(right_title)

        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch(1)
        self.list_area.setWidget(self.list_container)
        right.addWidget(self.list_area)

        right_wrap = QFrame()
        right_wrap.setLayout(right)
        right_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(right_wrap, 1)

    def _apply_styles(self):
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #eaeaea; font-family: sans-serif; }
            #connDot { font-size: 20px; color: #666; }
            #connText { font-size: 20px; font-weight: bold; }
            #deviceLabel { font-size: 16px; color: #aaa; }
            #sectionTitle { font-size: 14px; color: #888; letter-spacing: 1px; }
            #pill { background-color: #1e1e1e; border-radius: 10px; }
            #pillTitle { font-size: 12px; color: #888; letter-spacing: 1px; }
            #pillValue { font-size: 22px; font-weight: bold; }
            QScrollArea { border: none; }
            QLabel.fileRow { font-size: 15px; color: #ddd; }
        """)

    # ---------- socket event handlers ----------

    def on_connected(self):
        self.conn_dot.setStyleSheet("color: #4caf50;")
        self.conn_text.setText("Server online")

    def on_disconnected(self):
        self.conn_dot.setStyleSheet("color: #666;")
        self.conn_text.setText("Server offline")
        self.device_label.setText("Console: —")
        self.rec_pill.set_value("—")
        self.play_pill.set_value("—")
        self.storage_pill.set_value("—")

    def on_status(self, data):
        model = data.get("device_model") or "Unknown"
        connected = data.get("connected")
        self.device_label.setText(
            f"Console: {model} ({'connected' if connected else 'not detected'})"
        )

        if data.get("recording"):
            name = data.get("recording_file") or ""
            t = human_time(data.get("record_time"))
            self.rec_pill.set_value(f"● REC {t}\n{name}")
        else:
            self.rec_pill.set_value("Idle")

        if data.get("playing"):
            name = data.get("file") or ""
            pos = human_time(data.get("position"))
            dur = human_time(data.get("duration"))
            state = "Paused" if data.get("paused") else "Playing"
            self.play_pill.set_value(f"{state} {pos}/{dur}\n{name}")
        else:
            self.play_pill.set_value("Idle")

        free = data.get("storage_free_bytes")
        total = data.get("storage_total_bytes")
        if free is not None and total is not None:
            self.storage_pill.set_value(f"{human_size(free)} free\nof {human_size(total)}")
        else:
            self.storage_pill.set_value("—")

    def on_files(self, files):
        # Clear existing rows (keep the trailing stretch).
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for f in sorted(files, key=lambda x: x.get("name", "")):
            row = QLabel(f"{f.get('name')}  —  {human_size(f.get('size_bytes', 0))}  ({f.get('label')})")
            row.setProperty("class", "fileRow")
            row.setStyleSheet("font-size: 15px; color: #ddd;")
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    # ---------- keyboard escape for dev/testing ----------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


def parse_args():
    parser = argparse.ArgumentParser(description="Multitrack Recorder kiosk status display")
    parser.add_argument("--windowed", action="store_true",
                         help="Run in a normal resizable window instead of fullscreen/borderless/on-top")
    parser.add_argument("--url", default=DEFAULT_URL,
                         help=f"URL of the running web.py server (default: {DEFAULT_URL})")
    return parser.parse_args()


def main():
    args = parse_args()
    app = QApplication(sys.argv)

    window = KioskWindow(args.url)

    if args.windowed:
        window.resize(1280, 400)
        window.show()
    else:
        window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        screen_geo = app.primaryScreen().geometry()
        window.setGeometry(screen_geo)
        window.showFullScreen()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
