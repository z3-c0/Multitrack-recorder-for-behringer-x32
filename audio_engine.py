#!/usr/bin/env python3
import subprocess
import time
import os
import signal
import shutil
from pathlib import Path
from datetime import datetime

SUPPORTED_USB_VENDORS = {
    "XUSB":"X32/M32",
    "XR18":"X Air 18",
    "WING":"Wing",
    "SQ":"SQ",
    "QU":"QU",
    "Steinberg":"TF",
    "Ui24R":"Ui24R"
}
class AudioEngine:
    def __init__(
            self,
            recordings_dir="recordings",
            device="hw:XUSB",
            device_model="X32/M32",
            channels=16,
            sample_rate=48000,
            codec="pcm_s32le"
    ):
        self.device = device
        self.channels = channels
        self.device_model = device_model
        self.sample_rate = sample_rate
        self.codec = codec

        self.recordings_dir = Path(recordings_dir)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.storage_roots = ["/media", "/mnt", "/run/media"]

        # playback
        self.play_proc = None
        self.play_file = None
        self.play_dir = None
        self.play_start = None
        self.play_offset = 0.0
        self.duration = 0.0
        self.paused = False
        self.pause_started = None
        # recording
        self.rec_proc = None
        self.rec_file = None
        self.rec_start = None

    # ---------- helpers ----------

    def is_console_connected(self) -> bool:
        try:
            r = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True
            )
            lines = r.stdout.splitlines()
            current_card = None
            for line in lines:
                line_upper = line.upper()
                if "CARD" in line_upper and ":" in line_upper:
                    parts = line.split()
                    try:
                        card_index = parts[1].replace(":", "")
                        current_card = f"hw:{card_index}"
                        self.device = current_card
                    except Exception:
                        self.device = None
                        return False

                # device_model detection
                for card, device_model in SUPPORTED_USB_VENDORS.items():
                    if card in line_upper and current_card:
                        self.device_model = device_model
                        return True
            return False
        except Exception as e:
            print("Device detection failed:", e)
            return False

    def _ffprobe_duration(self, file) -> float:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file)
            ],
            capture_output=True,
            text=True
        )
        return float(r.stdout.strip() or 0)


    def _writable_dir(self, path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_test"
            probe.touch(exist_ok=True)
            probe.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def _storage_info(self, path: Path):
        usage = shutil.disk_usage(path)
        return {
            "path": str(path),
            "free_bytes": usage.free,
            "total_bytes": usage.total,
        }

    def _discover_mount_points(self):
        """
        Find mounted volumes under the conventional auto-mount roots, at
        either nesting depth: /media/<label> (common on minimal setups) or
        /media/<user>/<label> and /run/media/<user>/<label> (the udisks2
        convention most desktop-session automounters use). os.path.ismount()
        verifies it's an actual separate filesystem, not just any directory,
        so this works regardless of username or distro.
        """
        found = []
        for root in self.storage_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            try:
                children = list(root_path.iterdir())
            except OSError:
                continue
            for child in children:
                if os.path.ismount(child):
                    found.append(child)
                elif child.is_dir():
                    try:
                        grandchildren = list(child.iterdir())
                    except OSError:
                        continue
                    for grandchild in grandchildren:
                        if os.path.ismount(grandchild):
                            found.append(grandchild)
        return found

    def _known_storage_dirs(self):
        """Every writable recordings directory the app currently knows about:
        the active local storage plus a 'recordings' subfolder on each
        mounted volume. Backing for both the storage picker and file moves."""
        dirs = [{"path": self.recordings_dir, "label": "Local Storage"}]
        for mount in self._discover_mount_points():
            dirs.append({"path": mount / "recordings", "label": mount.name})
        return dirs

    def storage_options(self):
        options = []
        seen = set()

        for entry in self._known_storage_dirs():
            path = entry["path"]
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)

            if not self._writable_dir(path):
                continue

            info = self._storage_info(path)
            info["label"] = entry["label"]
            options.append(info)

        return sorted(options, key=lambda item: item["label"].lower())

    def set_storage_path(self, path):
        if self.rec_proc:
            raise RuntimeError("Cannot change storage while recording")

        target = Path(path).expanduser()
        if not target.is_absolute():
            raise RuntimeError("Storage path must be absolute")

        if not self._writable_dir(target):
            raise RuntimeError("Storage path is not writable")

        self.recordings_dir = target

    def free_space(self):
        return self._storage_info(self.recordings_dir)
    def list_recordings(self):
        files = []
        seen_dirs = set()
        for entry in self._known_storage_dirs():
            path = entry["path"]
            resolved = str(path.resolve()) if path.exists() else str(path)
            if resolved in seen_dirs or not path.is_dir():
                continue
            seen_dirs.add(resolved)

            for file in sorted(path.glob("*.wav")):
                files.append({
                    "name": file.name,
                    "size_bytes": file.stat().st_size,
                    "dir": str(path.resolve()),
                    "label": entry["label"],
                })
        return files

    # ---------- RECORD ----------
    def record_time(self):
        if not self.rec_proc:
            return 0.0
        return time.time() - self.rec_start
        
    def start_record(self, filename=None):
        if self.rec_proc:
            raise RuntimeError("Recording already running")

        if not self.is_console_connected():
            raise RuntimeError("Console not connected")

        if not filename:
            filename = datetime.now().strftime("rec_%Y-%m-%d_%H-%M-%S.wav")
        elif not filename.endswith(".wav"):
            filename += ".wav"

        path = self.recordings_dir / filename

        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-f", "alsa",
            "-acodec", self.codec,
            "-ac", str(self.channels),
            "-ar", str(self.sample_rate),
            "-i", self.device,
            "-c:a", "pcm_s24le",
            str(path)
        ]

        self.rec_proc = subprocess.Popen(
            cmd,
            preexec_fn=os.setsid
        )
        self.rec_file = filename
        self.rec_start = time.time()

    def stop_record(self, discard=False):
        if not self.rec_proc:
            return None

        filename = self.rec_file

        os.killpg(os.getpgid(self.rec_proc.pid), signal.SIGTERM)
        self.rec_proc.wait()

        self.rec_proc = None
        self.rec_file = None
        self.rec_start = None

        if discard and filename:
            path = self.recordings_dir / filename
            if path.exists():
                path.unlink()

        return filename

    # ---------- FILE LOCATION RESOLUTION ----------

    def _resolve_dir(self, dir=None):
        """Resolve a client-supplied directory to one of the app's known
        storage dirs (local or a mounted drive's recordings folder),
        defaulting to the active local storage. Rejects anything that isn't
        a known dir rather than trusting an arbitrary client-supplied path."""
        if dir is None:
            return self.recordings_dir

        target = str(Path(dir).resolve())
        for entry in self._known_storage_dirs():
            if str(entry["path"].resolve()) == target:
                return entry["path"]
        raise RuntimeError("Unknown storage directory")

    # ---------- PLAYBACK ----------

    def play(self, filename, dir=None, offset=0.0):
        if self.rec_proc:
            raise RuntimeError("Recording in progress")

        base = self._resolve_dir(dir)
        path = base / filename
        if not path.exists():
            raise FileNotFoundError(filename)

        self.stop()

        self.duration = self._ffprobe_duration(path)

        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-ss", str(offset),
            "-i", str(path),
            "-ac", str(self.channels),
            "-ar", str(self.sample_rate),
            "-acodec", self.codec,
            "-f", "alsa",
            self.device
        ]

        self.play_proc = subprocess.Popen(cmd)
        self.play_file = filename
        self.play_dir = str(base.resolve())
        self.play_start = time.time()
        self.play_offset = offset
        self.paused = False


    def pause(self):
        if self.play_proc and not self.paused:
            self.play_proc.send_signal(signal.SIGSTOP)
            self.paused = True
            self.pause_started = time.time()
    
    def resume(self):
        if self.play_proc and self.paused:
            self.play_proc.send_signal(signal.SIGCONT)

            if self.pause_started:
                paused_time = time.time() - self.pause_started
                self.play_start += paused_time
            self.pause_started = None
            self.paused = False
    
    def stop(self):
        if not self.play_proc:
            return

        self.play_proc.terminate()
        self.play_proc.wait()

        self.play_proc = None
        self.play_file = None
        self.play_dir = None
        self.play_start = None
        self.play_offset = 0.0
        self.duration = 0.0
        self.paused = False
        self.pause_started = None

    def refresh_playback_state(self):
        if not self.play_proc:
            return

        if self.play_proc.poll() is not None:
            self.play_proc = None
            self.play_file = None
            self.play_dir = None
            self.play_start = None
            self.play_offset = 0.0
            self.duration = 0.0
            self.paused = False
            self.pause_started = None

    def seek(self, seconds):
        if not self.play_file:
            return

        was_paused = self.paused
        self.play(self.play_file, dir=self.play_dir, offset=seconds)

        if was_paused:
            self.pause()

    def position(self):
        self.refresh_playback_state()
        if not self.play_proc:
            return 0.0
        if self.paused and self.pause_started is not None:
            return min(
                self.play_offset + (self.pause_started - self.play_start),
                self.duration
            )

        return min(
            self.play_offset + (time.time() - self.play_start),
            self.duration
        )

    # ---------- FILE OPS ----------

    def rename_file(self, old, new, dir=None):
        if self.rec_proc:
            raise RuntimeError("Recording in progress")

        base = self._resolve_dir(dir)
        if self.play_file == old and self.play_dir == str(base.resolve()):
            raise RuntimeError("File is playing")

        if not new.endswith(".wav"):
            new += ".wav"

        src = base / old
        dst = base / new

        if not src.exists():
            raise FileNotFoundError(old)
        if dst.exists():
            raise RuntimeError("Target file exists")

        src.rename(dst)

    def delete_file(self, filename, dir=None):
        if self.rec_proc:
            raise RuntimeError("Recording in progress")

        base = self._resolve_dir(dir)
        if self.play_file == filename and self.play_dir == str(base.resolve()):
            raise RuntimeError("File is playing")

        path = base / filename
        if not path.exists():
            raise FileNotFoundError(filename)

        path.unlink()

    def move_file(self, filename, src_dir, dest_dir):
        if self.rec_proc and self.rec_file == filename and \
                self.recordings_dir.resolve() == Path(src_dir).resolve():
            raise RuntimeError("Recording in progress")

        src_base = self._resolve_dir(src_dir)
        dest_base = self._resolve_dir(dest_dir)

        if self.play_file == filename and self.play_dir == str(src_base.resolve()):
            raise RuntimeError("File is playing")

        src = src_base / filename
        dst = dest_base / filename

        if not src.exists():
            raise FileNotFoundError(filename)
        if src.resolve() == dst.resolve():
            raise RuntimeError("File is already at that location")
        if dst.exists():
            raise RuntimeError("Target file exists")

        dest_base.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

    def move_all(self, dest_dir):
        dest_base = self._resolve_dir(dest_dir)
        moved = []
        skipped = []

        for file in self.list_recordings():
            if Path(file["dir"]).resolve() == dest_base.resolve():
                continue
            try:
                self.move_file(file["name"], file["dir"], str(dest_base))
                moved.append(file["name"])
            except Exception as e:
                skipped.append({"name": file["name"], "reason": str(e)})

        return {"moved": moved, "skipped": skipped}

    # ---------- STATUS ----------

    def status(self):
        self.refresh_playback_state()

        connected = self.is_console_connected() or self.rec_proc is not None
        return {
            "connected": connected,
            "device_model": self.device_model,
            "recording": self.rec_proc is not None,
            "recording_file": self.rec_file,
            "record_time": self.record_time(),
            "playing": self.play_proc is not None,
            "paused": self.paused,
            "file": self.play_file,
            "file_dir": self.play_dir,
            "position": self.position(),
            "duration": self.duration,
            "files": self.list_recordings(),
            "storage_path": str(self.recordings_dir),
            "storage_free_bytes": self.free_space()["free_bytes"],
            "storage_total_bytes": self.free_space()["total_bytes"],
        }
