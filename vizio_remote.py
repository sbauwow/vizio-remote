#!/usr/bin/env python3
"""Vizio SmartCast Remote Control — PyQt5 desktop app."""

import sys
import json
import urllib3
from functools import partial

import requests
from PyQt5.QtCore import Qt, QTimer, QThreadPool, QRunnable, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QPushButton,
    QLabel, QSlider, QVBoxLayout, QHBoxLayout, QSizePolicy, QMenu, QAction,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TV_IP = "10.26.209.142"
TV_PORT = 7345
AUTH_TOKEN = "Z6a2sannbw"
BASE_URL = f"https://{TV_IP}:{TV_PORT}"

KEYS = {
    "UP":        (3, 8),
    "DOWN":      (3, 0),
    "LEFT":      (3, 1),
    "RIGHT":     (3, 7),
    "OK":        (3, 2),
    "BACK":      (4, 0),
    "MENU":      (4, 8),
    "HOME":      (4, 15),
    "SMARTCAST":  (4, 3),
    "EXIT":      (9, 0),
    "INFO":      (4, 6),
    "CC":        (4, 4),
    "VOL_UP":    (5, 1),
    "VOL_DOWN":  (5, 0),
    "MUTE":      (5, 4),
    "POWER":     (11, 2),
    "PLAY":      (2, 3),
    "PAUSE":     (2, 2),
    "SEEK_FWD":  (2, 0),
    "SEEK_BACK": (2, 1),
    "CH_UP":     (8, 1),
    "CH_DOWN":   (8, 0),
    "INPUT":     (7, 1),
    "PIC_MODE":  (6, 0),
}


class VizioAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"AUTH": AUTH_TOKEN})
        self.session.verify = False

    def _url(self, path):
        return f"{BASE_URL}{path}"

    def key_press(self, name):
        codeset, code = KEYS[name]
        payload = {"KEYLIST": [{"CODESET": codeset, "CODE": code, "ACTION": "KEYPRESS"}]}
        try:
            self.session.put(self._url("/key_command/"), json=payload, timeout=3)
        except requests.RequestException:
            pass

    def get_power(self):
        try:
            r = self.session.get(self._url("/state/device/power_mode"), timeout=3)
            items = r.json().get("ITEMS", [])
            if items:
                return items[0].get("VALUE", 0)
        except Exception:
            pass
        return None

    def get_audio(self):
        try:
            r = self.session.get(
                self._url("/menu_native/dynamic/tv_settings/audio"), timeout=3
            )
            data = r.json()
            volume = None
            muted = None
            for item in data.get("ITEMS", []):
                name = item.get("CNAME", "")
                if name == "volume":
                    volume = item.get("VALUE")
                elif name == "mute":
                    muted = item.get("VALUE", "Off")
            return volume, muted
        except Exception:
            return None, None

    def get_current_input(self):
        try:
            r = self.session.get(
                self._url("/menu_native/dynamic/tv_settings/devices/current_input"),
                timeout=3,
            )
            items = r.json().get("ITEMS", [])
            if items:
                return items[0].get("VALUE", "?")
        except Exception:
            pass
        return None

    def get_input_list(self):
        """Returns list of (name, hashval) for available inputs."""
        try:
            r = self.session.get(
                self._url("/menu_native/dynamic/tv_settings/devices/name_input"),
                timeout=3,
            )
            inputs = []
            for item in r.json().get("ITEMS", []):
                name = item.get("NAME", item.get("CNAME", "?"))
                hashval = item.get("HASHVAL")
                inputs.append((name, hashval))
            return inputs
        except Exception:
            return []

    def set_input(self, name):
        """Switch to input by name. Fetches fresh hashval first (one-time token)."""
        try:
            r = self.session.get(
                self._url("/menu_native/dynamic/tv_settings/devices/current_input"),
                timeout=3,
            )
            hashval = r.json()["ITEMS"][0]["HASHVAL"]
            payload = {
                "REQUEST": "MODIFY",
                "VALUE": name,
                "HASHVAL": hashval,
            }
            self.session.put(
                self._url("/menu_native/dynamic/tv_settings/devices/current_input"),
                json=payload, timeout=3,
            )
        except Exception:
            pass


class WorkerSignals(QObject):
    finished = pyqtSignal()


class APIWorker(QRunnable):
    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.signals = WorkerSignals()

    def run(self):
        self.fn(*self.args)
        self.signals.finished.emit()


class StatusSignals(QObject):
    result = pyqtSignal(object, object, object, object)


class StatusWorker(QRunnable):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.signals = StatusSignals()

    def run(self):
        power = self.api.get_power()
        volume, muted = self.api.get_audio()
        inp = self.api.get_current_input()
        self.signals.result.emit(power, volume, muted, inp)


DARK_STYLE = """
QMainWindow { background-color: #1a1a2e; }
QWidget { background-color: #1a1a2e; color: #e0e0e0; font-family: sans-serif; }
QLabel#status { background-color: #16213e; border-radius: 6px; padding: 8px;
    font-size: 13px; color: #a0d2db; }
QPushButton {
    background-color: #0f3460; color: #e0e0e0; border: none; border-radius: 8px;
    padding: 12px 8px; font-size: 13px; font-weight: bold; min-width: 56px; min-height: 36px;
}
QPushButton:hover { background-color: #1a4f8a; }
QPushButton:pressed { background-color: #533483; }
QPushButton#power { background-color: #b91c1c; }
QPushButton#power:hover { background-color: #dc2626; }
QPushButton#ok { background-color: #533483; min-width: 52px; min-height: 52px;
    border-radius: 26px; font-size: 15px; }
QPushButton#dpad { background-color: #16213e; min-width: 48px; min-height: 48px; }
QPushButton#dpad:hover { background-color: #1a4f8a; }
QSlider::groove:horizontal { height: 6px; background: #16213e; border-radius: 3px; }
QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0;
    background: #533483; border-radius: 9px; }
QSlider::sub-page:horizontal { background: #0f3460; border-radius: 3px; }
"""


class RemoteWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api = VizioAPI()
        self.pool = QThreadPool()
        self.setWindowTitle("Vizio Remote")
        self.setFixedSize(340, 620)
        self.setStyleSheet(DARK_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 10, 12, 10)

        # Status bar
        self.status_label = QLabel("Connecting...")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Power / Input row
        row = QHBoxLayout()
        row.addWidget(self._btn("Power", "POWER", obj_name="power"))
        row.addStretch()
        self.input_btn = QPushButton("Input")
        self.input_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.input_btn.clicked.connect(self._show_input_menu)
        row.addWidget(self.input_btn)
        layout.addLayout(row)

        # Vol/Ch block
        grid = QGridLayout()
        grid.setSpacing(4)
        grid.addWidget(self._btn("Vol+", "VOL_UP"), 0, 0)
        grid.addWidget(self._btn("Ch+", "CH_UP"), 0, 2)
        grid.addWidget(self._btn("Mute", "MUTE"), 1, 0)
        grid.addWidget(self._btn("Info", "INFO"), 1, 2)
        grid.addWidget(self._btn("Vol-", "VOL_DOWN"), 2, 0)
        grid.addWidget(self._btn("Ch-", "CH_DOWN"), 2, 2)
        layout.addLayout(grid)

        # D-pad
        dpad = QGridLayout()
        dpad.setSpacing(2)
        dpad.addWidget(self._btn("\u25B2", "UP", obj_name="dpad"), 0, 1)
        dpad.addWidget(self._btn("\u25C0", "LEFT", obj_name="dpad"), 1, 0)
        dpad.addWidget(self._btn("OK", "OK", obj_name="ok"), 1, 1)
        dpad.addWidget(self._btn("\u25B6", "RIGHT", obj_name="dpad"), 1, 2)
        dpad.addWidget(self._btn("\u25BC", "DOWN", obj_name="dpad"), 2, 1)
        layout.addLayout(dpad)

        # Nav row
        nav = QHBoxLayout()
        for label, key in [("Back", "BACK"), ("Home", "HOME"), ("Menu", "MENU"), ("Exit", "EXIT")]:
            nav.addWidget(self._btn(label, key))
        layout.addLayout(nav)

        # Media row
        media = QHBoxLayout()
        for label, key in [("\u23EA", "SEEK_BACK"), ("\u25B6", "PLAY"), ("\u23F8", "PAUSE"), ("\u23E9", "SEEK_FWD")]:
            media.addWidget(self._btn(label, key))
        layout.addLayout(media)

        # Bottom row
        bottom = QHBoxLayout()
        for label, key in [("Smart", "SMARTCAST"), ("CC", "CC"), ("PicMode", "PIC_MODE")]:
            bottom.addWidget(self._btn(label, key))
        layout.addLayout(bottom)

        # Volume slider
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Vol"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.sliderReleased.connect(self._on_slider)
        slider_row.addWidget(self.vol_slider)
        layout.addLayout(slider_row)

        # Status polling
        self.timer = QTimer()
        self.timer.timeout.connect(self._poll_status)
        self.timer.start(3000)
        self._poll_status()

    def _btn(self, label, key, obj_name=None):
        b = QPushButton(label)
        if obj_name:
            b.setObjectName(obj_name)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        b.clicked.connect(partial(self._send_key, key))
        return b

    def _show_input_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #16213e; color: #e0e0e0; border: 1px solid #0f3460; }"
            "QMenu::item:selected { background-color: #533483; }"
        )
        inputs = self.api.get_input_list()
        for name, hashval in inputs:
            action = menu.addAction(name)
            action.triggered.connect(partial(self._switch_input, name))
        menu.exec_(self.input_btn.mapToGlobal(self.input_btn.rect().bottomLeft()))

    def _switch_input(self, name):
        worker = APIWorker(self.api.set_input, name)
        self.pool.start(worker)

    def _send_key(self, key):
        worker = APIWorker(self.api.key_press, key)
        self.pool.start(worker)

    def _on_slider(self):
        target = self.vol_slider.value()
        # Volume set requires repeated key presses or direct API; use key approach
        # For simplicity, just send the current volume info
        # The SmartCast API doesn't have a direct volume set — we'd need to use
        # the settings endpoint. For now the slider just shows current level.
        pass

    def _poll_status(self):
        worker = StatusWorker(self.api)
        worker.signals.result.connect(self._update_status)
        self.pool.start(worker)

    def _update_status(self, power, volume, muted, inp):
        parts = []
        if power is not None:
            parts.append("ON" if power == 1 else "STANDBY")
        else:
            parts.append("--")
        if inp:
            parts.append(str(inp))
        if volume is not None:
            parts.append(f"Vol: {volume}")
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(int(volume))
            self.vol_slider.blockSignals(False)
        if muted and muted != "Off":
            parts.append("MUTED")
        self.status_label.setText("  |  ".join(parts))

    def keyPressEvent(self, event):
        key = event.key()
        mapping = {
            Qt.Key_Up: "UP", Qt.Key_Down: "DOWN",
            Qt.Key_Left: "LEFT", Qt.Key_Right: "RIGHT",
            Qt.Key_Return: "OK", Qt.Key_Enter: "OK",
            Qt.Key_Escape: "BACK",
            Qt.Key_Plus: "VOL_UP", Qt.Key_Equal: "VOL_UP",
            Qt.Key_Minus: "VOL_DOWN",
            Qt.Key_M: "MUTE",
            Qt.Key_H: "HOME",
            Qt.Key_Space: "PLAY",
        }
        cmd = mapping.get(key)
        if cmd:
            self._send_key(cmd)
        else:
            super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    window = RemoteWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
