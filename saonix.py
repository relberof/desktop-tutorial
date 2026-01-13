# saonix.py
# Saonix Macro Recorder (ProgramData-based, i18n, themes, safer playback)

import json
import os
import sys
import time
import threading
import random
import traceback
import ctypes
import subprocess
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Callable, Tuple

import customtkinter as ctk
from tkinter import messagebox, filedialog

from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, KeyCode, Controller as KeyboardController


# =========================
# App constants / paths
# =========================
APP_NAME = "Saonix"
APP_VENDOR_DIR = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), APP_NAME)

LOG_DIR = os.path.join(APP_VENDOR_DIR, "logs")
DATA_DIR = os.path.join(APP_VENDOR_DIR, "data")
LOCALES_DIR = os.path.join(APP_VENDOR_DIR, "locales")

DB_FILE = os.path.join(DATA_DIR, "macros_db.json")
CFG_FILE = os.path.join(DATA_DIR, "config.json")
LOG_FILE = os.path.join(LOG_DIR, "app.log")


def ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOCALES_DIR, exist_ok=True)


def resource_path(rel: str) -> str:
    """PyInstaller onefile: sys._MEIPASS; normal: current folder"""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel)


def copy_tree(src: str, dst: str):
    if not os.path.isdir(src):
        return
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        sp = os.path.join(src, name)
        dp = os.path.join(dst, name)
        if os.path.isdir(sp):
            copy_tree(sp, dp)
        else:
            try:
                with open(sp, "rb") as fsrc:
                    data = fsrc.read()
                with open(dp, "wb") as fdst:
                    fdst.write(data)
            except Exception:
                pass


def seed_locales_if_missing():
    """
    If ProgramData locales are missing, try to seed from bundled ./locales (PyInstaller) or local folder.
    """
    ensure_dirs()
    try:
        has_any = any(fn.endswith(".json") for fn in os.listdir(LOCALES_DIR))
    except Exception:
        has_any = False
    if has_any:
        return

    # try bundled locales folder
    bundled = resource_path("locales")
    if os.path.isdir(bundled):
        copy_tree(bundled, LOCALES_DIR)
        return

    # try local ./locales
    local = os.path.join(os.path.abspath("."), "locales")
    if os.path.isdir(local):
        copy_tree(local, LOCALES_DIR)


# =========================
# Helpers
# =========================
def safe_int(s: str, default: int) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default


def safe_float(s: str, default: float) -> float:
    try:
        return float(str(s).strip())
    except Exception:
        return default


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# =========================
# Logging
# =========================
class Logger:
    def __init__(self, ui_append_fn: Callable[[str], None]):
        self.ui_append = ui_append_fn
        ensure_dirs()
        self._lock = threading.Lock()

    def _write_file(self, line: str):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _log(self, level: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        with self._lock:
            self._write_file(line)
        self.ui_append(line + "\n")

    def info(self, msg: str):
        self._log("INFO", msg)

    def warn(self, msg: str):
        self._log("WARNING", msg)

    def error(self, msg: str):
        self._log("ERROR", msg)


# =========================
# i18n
# =========================
SUPPORTED_LANGS = ["en", "ru", "zh-CN", "ja", "ko", "id", "fr", "pt-BR", "vi", "pl"]


def get_windows_ui_lang_tag() -> str:
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        langid_map = {
            0x0409: "en",
            0x0809: "en",
            0x0419: "ru",
            0x0804: "zh-CN",
            0x0411: "ja",
            0x0412: "ko",
            0x0421: "id",
            0x040C: "fr",
            0x0416: "pt-BR",  # closest
            0x042A: "vi",
            0x0415: "pl",
        }
        return langid_map.get(int(lid), "en")
    except Exception:
        return "en"


# Minimal built-in fallback strings (so UI never becomes "empty")
FALLBACK_EN = {
    "app_name": "Saonix",
    "nav_record": "● Record",
    "nav_library": "📚 Library",
    "nav_settings": "⚙ Settings",
    "status_ready": "Ready",
    "status_recording": "● Recording…",
    "status_playing": "▶ Playing…",
    "record_title": "Controls",
    "record_start": "● Start recording",
    "record_stop": "■ Stop recording",
    "record_play_loaded": "▶ Play (loaded)",
    "record_stop_play": "⏹ Stop",
    "record_save_label": "Save to library:",
    "record_save_btn": "💾 Save",
    "hotkeys_title": "Hotkeys",
    "hotkeys_hint": "If the target app is running as Admin, run Saonix as Admin too.",
    "log_title": "Log",
    "log_clear": "Clear log (window)",
    "lib_title": "Library",
    "search_placeholder": "Search…",
    "btn_load": "Load",
    "btn_delete": "Delete",
    "btn_rename": "Rename",
    "btn_clone": "Clone",
    "btn_export": "Export JSON",
    "btn_import": "Import JSON",
    "preview_none": "—",
    "bind_label": "Bind:",
    "bind_placeholder": "F6 or Ctrl+Alt+F6",
    "btn_bind": "Bind",
    "btn_unbind": "Unbind",
    "btn_play_selected": "▶ Play selected",
    "settings_title": "Playback settings",
    "repeat": "Repeat (times)",
    "loop": "Loop (sec)",
    "speed": "Speed",
    "delay": "Start delay (sec)",
    "apply": "Apply",
    "reset": "Reset",
    "appearance": "Appearance",
    "theme": "Theme",
    "language": "Language",
    "ignore_win": "Ignore Win key (recommended)",
    "base_hotkeys": "Base hotkeys",
    "hk_record": "Record",
    "hk_stop_record": "Stop rec",
    "hk_play_loaded": "Play loaded",
    "hk_stop_play": "Stop play",
    "danger_stop": "Stop",
}

# RU fallback (small)
FALLBACK_RU = {
    "nav_record": "● Запись",
    "nav_library": "📚 Библиотека",
    "nav_settings": "⚙ Настройки",
    "status_ready": "Готово",
    "status_recording": "● Запись…",
    "status_playing": "▶ Воспроизведение…",
    "record_title": "Управление",
    "record_start": "● Начать запись",
    "record_stop": "■ Остановить запись",
    "record_play_loaded": "▶ Воспроизвести (загруженный)",
    "record_stop_play": "⏹ Остановить",
    "record_save_label": "Сохранить в библиотеку:",
    "record_save_btn": "💾 Сохранить",
    "hotkeys_title": "Горячие клавиши",
    "hotkeys_hint": "Если целевое приложение запущено от Админа — запускай Saonix от Админа.",
    "log_title": "Лог",
    "log_clear": "Очистить лог (в окне)",
    "lib_title": "Библиотека",
    "search_placeholder": "Поиск…",
    "btn_load": "Загрузить",
    "btn_delete": "Удалить",
    "btn_rename": "Переименовать",
    "btn_clone": "Клонировать",
    "btn_export": "Экспорт JSON",
    "btn_import": "Импорт JSON",
    "bind_label": "Бинд:",
    "btn_bind": "Назначить",
    "btn_unbind": "Снять",
    "btn_play_selected": "▶ Воспроизвести выбранный",
    "settings_title": "Настройки воспроизведения",
    "repeat": "Повтор (раз)",
    "loop": "Цикл (сек)",
    "speed": "Скорость",
    "delay": "Задержка старта (сек)",
    "apply": "Применить",
    "reset": "Сбросить",
    "appearance": "Тема",
    "theme": "Стиль",
    "language": "Язык",
    "ignore_win": "Игнорировать Win (рекомендуется)",
    "base_hotkeys": "Базовые хоткеи",
    "hk_record": "Запись",
    "hk_stop_record": "Стоп запись",
    "hk_play_loaded": "Пуск (загруж.)",
    "hk_stop_play": "Стоп",
    "danger_stop": "Остановить",
}


class I18N:
    def __init__(self, lang_tag: str):
        self.lang = lang_tag if lang_tag in SUPPORTED_LANGS else "en"
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self):
        seed_locales_if_missing()
        path = os.path.join(LOCALES_DIR, f"{self.lang}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            self.data = obj if isinstance(obj, dict) else {}
        except Exception:
            self.data = {}

    def t(self, key: str, fallback: Optional[str] = None) -> str:
        # allow nested JSON, but treat only simple strings as valid
        v = self.data.get(key, None)
        if isinstance(v, str):
            return v
        # fallback dicts
        if self.lang == "ru" and key in FALLBACK_RU:
            return FALLBACK_RU[key]
        if key in FALLBACK_EN:
            return FALLBACK_EN[key]
        return fallback if fallback is not None else key


# =========================
# Config
# =========================
DEFAULT_CONFIG: Dict[str, Any] = {
    "lang": "auto",                 # auto or explicit tag
    "appearance": "Dark",           # Dark/Light
    "theme": "Calm",                # Calm/Aurora/Rose
    "glow": 2,                      # 0..3
    "ignore_win_key": True,         # helps prevent "stuck Win/Fn-like" behavior
    "base_hotkeys": {
        "record": "Ctrl+Alt+1",
        "stop_record": "Ctrl+Alt+2",
        "play_loaded": "Ctrl+Alt+3",
        "stop_play": "Ctrl+Alt+4",
    },
}


def load_config() -> Dict[str, Any]:
    ensure_dirs()
    if not os.path.exists(CFG_FILE):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CFG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return json.loads(json.dumps(DEFAULT_CONFIG))
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged.update(cfg)
        merged["base_hotkeys"] = {**DEFAULT_CONFIG["base_hotkeys"], **cfg.get("base_hotkeys", {})}
        merged["glow"] = int(clamp(safe_int(merged.get("glow", 2), 2), 0, 3))
        merged["appearance"] = "Light" if str(merged.get("appearance", "Dark")).lower().startswith("l") else "Dark"
        if merged.get("theme") not in ("Calm", "Aurora", "Rose"):
            merged["theme"] = "Calm"
        if merged.get("lang") not in (["auto"] + SUPPORTED_LANGS):
            merged["lang"] = "auto"
        merged["ignore_win_key"] = bool(merged.get("ignore_win_key", True))
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: Dict[str, Any]):
    ensure_dirs()
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =========================
# Data
# =========================
@dataclass
class Event:
    t: float
    device: str
    type: str
    data: Dict[str, Any]


class MacroDB:
    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 2, "macros": {}, "binds": {}}
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("macros"), dict):
                self.data = d
                if "binds" not in self.data or not isinstance(self.data["binds"], dict):
                    self.data["binds"] = {}
        except Exception:
            pass

    def save(self):
        ensure_dirs()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def names(self) -> List[str]:
        return sorted(self.data["macros"].keys(), key=lambda x: x.lower())

    def exists(self, name: str) -> bool:
        return name in self.data["macros"]

    def get(self, name: str):
        return self.data["macros"].get(name)

    def put(self, name: str, events: List[Event], settings: Dict[str, Any]):
        self.data["macros"][name] = {
            "created": int(time.time()),
            "events": [asdict(e) for e in events],
            "settings": settings,
        }
        self.save()

    def delete(self, name: str):
        if name in self.data["macros"]:
            del self.data["macros"][name]
        dead = [hk for hk, mn in self.data.get("binds", {}).items() if mn == name]
        for hk in dead:
            del self.data["binds"][hk]
        self.save()

    def rename(self, old: str, new: str) -> bool:
        if old not in self.data["macros"] or new in self.data["macros"]:
            return False
        self.data["macros"][new] = self.data["macros"].pop(old)
        for hk, mn in list(self.data.get("binds", {}).items()):
            if mn == old:
                self.data["binds"][hk] = new
        self.save()
        return True

    def clone(self, src: str, dst: str) -> bool:
        if src not in self.data["macros"] or dst in self.data["macros"]:
            return False
        self.data["macros"][dst] = json.loads(json.dumps(self.data["macros"][src]))
        self.data["macros"][dst]["created"] = int(time.time())
        self.save()
        return True

    def set_bind(self, hotkey: str, macro_name: str):
        self.data.setdefault("binds", {})
        self.data["binds"][hotkey] = macro_name
        self.save()

    def remove_bind(self, hotkey: str):
        if hotkey in self.data.get("binds", {}):
            del self.data["binds"][hotkey]
            self.save()

    def binds(self) -> Dict[str, str]:
        return dict(self.data.get("binds", {}))


# =========================
# Hotkey parsing
# =========================
def normalize_hotkey(text: str) -> Optional[str]:
    """
    Convert human hotkey like: "Ctrl+Alt+F6", "F6", "Shift+Z" into pynput GlobalHotKeys format:
    "<ctrl>+<alt>+<f6>" , "<f6>", "<shift>+z"
    """
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None

    # allow already in GlobalHotKeys format
    if t.startswith("<") and t.endswith(">") and "+" not in t:
        return t

    parts = t.split("+")
    mods: List[str] = []
    key: Optional[str] = None

    for p in parts:
        if p in ("ctrl", "control"):
            if "<ctrl>" not in mods:
                mods.append("<ctrl>")
        elif p == "alt":
            if "<alt>" not in mods:
                mods.append("<alt>")
        elif p == "shift":
            if "<shift>" not in mods:
                mods.append("<shift>")
        elif p in ("win", "cmd", "meta"):
            if "<cmd>" not in mods:
                mods.append("<cmd>")
        else:
            key = p

    if key is None:
        return None

    # main key
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            key_fmt = f"<f{n}>"
        else:
            return None
    elif key in ("space", "spc"):
        key_fmt = "<space>"
    elif key in ("tab",):
        key_fmt = "<tab>"
    elif key in ("esc", "escape"):
        key_fmt = "<esc>"
    elif key in ("enter", "return"):
        key_fmt = "<enter>"
    elif len(key) == 1 and ("a" <= key <= "z" or key.isdigit()):
        key_fmt = key
    else:
        return None

    return "+".join(mods + [key_fmt])


# =========================
# Engine (safer playback to avoid stuck modifiers)
# =========================
class MacroEngine:
    def __init__(self, logger: Logger, ignore_win_key: bool = True):
        self.log = logger
        self.ignore_win_key = bool(ignore_win_key)

        self.events: List[Event] = []
        self.recording = False
        self.playing = False

        self._t0: Optional[float] = None
        self._stop_play = threading.Event()
        self._play_lock = threading.Lock()
        self._play_thread: Optional[threading.Thread] = None

        self.mouse_ctl = MouseController()
        self.kb_ctl = KeyboardController()

        # tracking to prevent "stuck Win/Fn-like" behavior
        self._pressed_keys_playback: set = set()
        self._pressed_mouse_playback: set = set()

        self._last_move = None
        self._last_move_time = 0.0
        self._min_move_interval = 0.01

        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._kb_listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,  # do NOT block user's keyboard
        )

        self._mouse_listener.start()
        self._kb_listener.start()

        self.log.info("Engine ready.")

    def shutdown(self):
        try:
            self.stop_playing()
        except Exception:
            pass
        try:
            self._mouse_listener.stop()
        except Exception:
            pass
        try:
            self._kb_listener.stop()
        except Exception:
            pass

    def set_ignore_win(self, v: bool):
        self.ignore_win_key = bool(v)

    def now(self) -> float:
        return time.perf_counter()

    def rel_time(self) -> float:
        return 0.0 if self._t0 is None else self.now() - self._t0

    def _add(self, device: str, etype: str, data: Dict[str, Any]):
        if not self.recording:
            return
        self.events.append(Event(t=self.rel_time(), device=device, type=etype, data=data))

    def start_recording(self):
        with self._play_lock:
            if self.playing:
                self.log.warn("Stop playback first.")
                return
            if self.recording:
                self.log.warn("Already recording.")
                return
            self.events = []
            self._t0 = self.now()
            self.recording = True
            self.log.info("=== Recording started ===")

    def stop_recording(self):
        if not self.recording:
            self.log.warn("Not recording.")
            return
        self.recording = False
        self.log.info(f"=== Recording stopped. Events: {len(self.events)} ===")

    def _release_all_playback(self):
        # release all keys we pressed during playback
        for k in list(self._pressed_keys_playback):
            try:
                self.kb_ctl.release(k)
            except Exception:
                pass
        self._pressed_keys_playback.clear()

        for b in list(self._pressed_mouse_playback):
            try:
                self.mouse_ctl.release(b)
            except Exception:
                pass
        self._pressed_mouse_playback.clear()

    def stop_playing(self):
        with self._play_lock:
            if not self.playing:
                return
            self._stop_play.set()
            self.playing = False
        # ensure release happens even if stop pressed mid-macro
        self._release_all_playback()
        self.log.info("=== Stopped ===")

    def _is_win_key(self, k) -> bool:
        return k in (Key.cmd, getattr(Key, "cmd_l", Key.cmd), getattr(Key, "cmd_r", Key.cmd))

    def _key_to_repr(self, k):
        if isinstance(k, Key):
            return {"kind": "special", "value": k.name}
        if hasattr(k, "char") and k.char is not None:
            return {"kind": "char", "value": k.char}
        if isinstance(k, KeyCode) and k.vk is not None:
            return {"kind": "vk", "value": int(k.vk)}
        return None

    def _repr_to_key(self, r):
        try:
            kind = r.get("kind")
            val = r.get("value")
            if kind == "special":
                return getattr(Key, val)
            if kind == "char":
                return val
            if kind == "vk":
                return KeyCode.from_vk(int(val))
        except Exception:
            return None
        return None

    # --- record listeners
    def _on_move(self, x, y):
        if self.playing:
            return
        now = self.now()
        pos = (int(x), int(y))
        if pos == self._last_move:
            return
        if now - self._last_move_time < self._min_move_interval:
            return
        self._last_move = pos
        self._last_move_time = now
        self._add("mouse", "move", {"x": pos[0], "y": pos[1]})

    def _on_click(self, x, y, button, pressed):
        if self.playing:
            return
        self._add("mouse", "click", {
            "x": int(x), "y": int(y),
            "button": button.name if hasattr(button, "name") else str(button),
            "pressed": bool(pressed),
        })

    def _on_scroll(self, x, y, dx, dy):
        if self.playing:
            return
        self._add("mouse", "scroll", {"x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)})

    def _on_press(self, key):
        if self.playing:
            return
        if self.ignore_win_key and self._is_win_key(key):
            return
        rep = self._key_to_repr(key)
        if rep:
            self._add("keyboard", "press", {"key": rep})

    def _on_release(self, key):
        if self.playing:
            return
        if self.ignore_win_key and self._is_win_key(key):
            return
        rep = self._key_to_repr(key)
        if rep:
            self._add("keyboard", "release", {"key": rep})

    # --- playback application
    def _apply_event(self, e: Event):
        if e.device == "mouse":
            if e.type == "move":
                self.mouse_ctl.position = (e.data["x"], e.data["y"])
            elif e.type == "click":
                self.mouse_ctl.position = (e.data["x"], e.data["y"])
                btn = getattr(Button, e.data.get("button", "left"), Button.left)
                if e.data.get("pressed"):
                    self.mouse_ctl.press(btn)
                    self._pressed_mouse_playback.add(btn)
                else:
                    self.mouse_ctl.release(btn)
                    self._pressed_mouse_playback.discard(btn)
            elif e.type == "scroll":
                self.mouse_ctl.position = (e.data["x"], e.data["y"])
                self.mouse_ctl.scroll(e.data["dx"], e.data["dy"])
            return

        if e.device == "keyboard":
            key_obj = self._repr_to_key(e.data.get("key", {}))
            if key_obj is None:
                return
            # prevent Win key messing with system state (default ON)
            if self.ignore_win_key and key_obj in (Key.cmd, getattr(Key, "cmd_l", Key.cmd), getattr(Key, "cmd_r", Key.cmd)):
                return
            if e.type == "press":
                self.kb_ctl.press(key_obj)
                self._pressed_keys_playback.add(key_obj)
            elif e.type == "release":
                self.kb_ctl.release(key_obj)
                self._pressed_keys_playback.discard(key_obj)

    def play(self, repeat: int, loop_seconds: int, speed: float, start_delay: float):
        with self._play_lock:
            if self.recording:
                self.log.warn("Stop recording first.")
                return
            if self.playing:
                self.log.warn("Already playing.")
                return
            if not self.events:
                self.log.warn("No events to play.")
                return

            self.playing = True
            self._stop_play.clear()
            self._pressed_keys_playback.clear()
            self._pressed_mouse_playback.clear()

            def play_once():
                base = self.now()
                for ev in self.events:
                    if self._stop_play.is_set():
                        return
                    target = base + (ev.t / max(0.05, speed))
                    while True:
                        if self._stop_play.is_set():
                            return
                        dt = target - self.now()
                        if dt <= 0:
                            break
                        time.sleep(min(dt, 0.01))
                    self._apply_event(ev)

            def run():
                try:
                    if start_delay > 0:
                        end = time.time() + start_delay
                        while time.time() < end and not self._stop_play.is_set():
                            time.sleep(0.01)

                    if loop_seconds > 0:
                        started = time.time()
                        loops = 0
                        while not self._stop_play.is_set() and (time.time() - started) < loop_seconds:
                            play_once()
                            loops += 1
                        self.log.info(f"Done. Loops: {loops}")
                    else:
                        for i in range(max(1, repeat)):
                            if self._stop_play.is_set():
                                break
                            play_once()

                    self.log.info("=== Playback finished ===")

                except Exception as e:
                    self.log.error(f"Playback error: {e}")
                    self.log.error(traceback.format_exc())
                finally:
                    with self._play_lock:
                        self.playing = False
                        self._stop_play.set()
                    self._release_all_playback()

            self._play_thread = threading.Thread(target=run, daemon=True)
            self._play_thread.start()


# =========================
# Snow (removed)
# =========================
# Notifications removed and snow removed per request.


# =========================
# Styles
# =========================
class ThemePack:
    def __init__(self, name: str,
                 dark_bg: str, dark_panel: str, dark_card: str, dark_text: str, dark_muted: str, dark_border: str,
                 light_bg: str, light_panel: str, light_card: str, light_text: str, light_muted: str, light_border: str,
                 accent: str, accent2: str, danger: str, good: str):
        self.name = name

        self.dark_bg = dark_bg
        self.dark_panel = dark_panel
        self.dark_card = dark_card
        self.dark_text = dark_text
        self.dark_muted = dark_muted
        self.dark_border = dark_border

        self.light_bg = light_bg
        self.light_panel = light_panel
        self.light_card = light_card
        self.light_text = light_text
        self.light_muted = light_muted
        self.light_border = light_border

        self.accent = accent
        self.accent2 = accent2
        self.danger = danger
        self.good = good

    def colors(self, appearance: str) -> Dict[str, str]:
        if appearance == "Light":
            return dict(
                bg=self.light_bg,
                panel=self.light_panel,
                card=self.light_card,
                text=self.light_text,
                muted=self.light_muted,
                border=self.light_border,
                accent=self.accent,
                accent2=self.accent2,
                danger=self.danger,
                good=self.good,
            )
        return dict(
            bg=self.dark_bg,
            panel=self.dark_panel,
            card=self.dark_card,
            text=self.dark_text,
            muted=self.dark_muted,
            border=self.dark_border,
            accent=self.accent,
            accent2=self.accent2,
            danger=self.danger,
            good=self.good,
        )


THEMES: Dict[str, ThemePack] = {
    "Calm": ThemePack(
        "Calm",
        dark_bg="#0d1118", dark_panel="#121826", dark_card="#141d2e", dark_text="#e9eef7", dark_muted="#a7b4cc", dark_border="#23314a",
        light_bg="#f5f7fb", light_panel="#ffffff", light_card="#f0f3fa", light_text="#121826", light_muted="#5b6b86", light_border="#d7deeb",
        accent="#4c8dff", accent2="#7b5cff", danger="#ff4a4a", good="#29d17d"
    ),
    "Aurora": ThemePack(
        "Aurora",
        dark_bg="#071216", dark_panel="#0b1a20", dark_card="#0d222a", dark_text="#e9fffb", dark_muted="#a3d6ce", dark_border="#14343a",
        light_bg="#f2fbf8", light_panel="#ffffff", light_card="#e8f6f2", light_text="#0b1a20", light_muted="#356b63", light_border="#cfe7e0",
        accent="#2ad8a6", accent2="#56a8ff", danger="#ff4a4a", good="#24c46b"
    ),
    "Rose": ThemePack(
        "Rose",
        dark_bg="#120912", dark_panel="#1a0e1a", dark_card="#221024", dark_text="#ffeef9", dark_muted="#d7b0c9", dark_border="#3a1b3c",
        light_bg="#fff6fb", light_panel="#ffffff", light_card="#ffe8f4", light_text="#1a0e1a", light_muted="#7a3b66", light_border="#f1cde2",
        accent="#ff4fa7", accent2="#7b5cff", danger="#ff3b30", good="#29d17d"
    ),
}


# =========================
# Hotkey Manager
# =========================
class HotkeyManager:
    def __init__(self, logger: Logger):
        self.log = logger
        self._listener = None

    def set(self, mapping: Dict[str, Callable[[], None]]):
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass

        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
            self.log.info(f"Hotkeys active: {len(mapping)}")
        except Exception as e:
            self.log.error(f"Hotkeys error: {e}")

    def shutdown(self):
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass


# =========================
# App
# =========================
class SaonixApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        seed_locales_if_missing()

        self.cfg = load_config()
        self.appearance = self.cfg["appearance"]
        self.theme_name = self.cfg["theme"]
        self.glow_level = int(self.cfg.get("glow", 2))
        self.ignore_win_key = bool(self.cfg.get("ignore_win_key", True))

        # language choice
        lang_cfg = self.cfg.get("lang", "auto")
        lang = get_windows_ui_lang_tag() if lang_cfg == "auto" else lang_cfg
        if lang not in SUPPORTED_LANGS:
            lang = "en"
        self.i18n = I18N(lang)

        ctk.set_appearance_mode(self.appearance)
        ctk.set_default_color_theme("blue")

        self.title(self.i18n.t("app_name", APP_NAME))
        self.geometry("1180x720")
        self.minsize(1180, 720)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.db = MacroDB(DB_FILE)

        self.log_box = None
        self.logger = Logger(self._append_log_ui)

        self.engine = MacroEngine(self.logger, ignore_win_key=self.ignore_win_key)
        self.hk = HotkeyManager(self.logger)

        # layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, corner_radius=18)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=14, pady=14)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(99, weight=1)

        self.brand = ctk.CTkLabel(
            self.sidebar,
            text=self.i18n.t("app_name", APP_NAME),
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        self.brand.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        # nav buttons
        self.btn_record = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_record"), command=lambda: self.show_page("record"))
        self.btn_library = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_library"), command=lambda: self.show_page("library"))
        self.btn_settings = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_settings"), command=lambda: self.show_page("settings"))

        self.btn_record.grid(row=2, column=0, padx=16, pady=(8, 8), sticky="ew")
        self.btn_library.grid(row=3, column=0, padx=16, pady=8, sticky="ew")
        self.btn_settings.grid(row=4, column=0, padx=16, pady=8, sticky="ew")

        # footer star only
        self.footer_star = ctk.CTkLabel(self.sidebar, text="✦", font=ctk.CTkFont(size=42, weight="bold"))
        self.footer_star.grid(row=100, column=0, padx=16, pady=(0, 12), sticky="sw")

        # Main
        self.main = ctk.CTkFrame(self, corner_radius=18)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkFrame(self.main, corner_radius=18, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        self.header.grid_columnconfigure(0, weight=1)

        self.h_title = ctk.CTkLabel(self.header, text=self.i18n.t("nav_record"), font=ctk.CTkFont(size=18, weight="bold"))
        self.h_title.grid(row=0, column=0, padx=14, pady=12, sticky="w")

        self.status_var = ctk.StringVar(value=self.i18n.t("status_ready"))
        self.h_status = ctk.CTkLabel(self.header, textvariable=self.status_var)
        self.h_status.grid(row=0, column=1, padx=14, pady=12, sticky="e")

        self.content = ctk.CTkFrame(self.main, corner_radius=18, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=14, pady=(8, 14))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # Pages
        self.page_record = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        self.page_library = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        self.page_settings = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid(row=0, column=0, sticky="nsew")
            p.grid_remove()

        # build pages
        self.build_record_page()
        self.build_library_page()
        self.build_settings_page()

        self._active_page = "record"
        self.show_page("record", animate=False)

        self.apply_theme()

        # hotkeys
        self.rebuild_hotkeys()

        self.after(200, self.tick)
        self.logger.info("Started.")
        self.logger.info("Tip: ignore Win key is ON by default to reduce stuck key issues.")

    # ---------- close ----------
    def on_close(self):
        try:
            self.logger.info("Closing…")
        except Exception:
            pass
        try:
            self.engine.stop_playing()
        except Exception:
            pass
        try:
            self.hk.shutdown()
        except Exception:
            pass
        try:
            self.engine.shutdown()
        except Exception:
            pass
        try:
            self.cfg["appearance"] = self.appearance
            self.cfg["theme"] = self.theme_name
            self.cfg["glow"] = int(self.glow_level)
            self.cfg["ignore_win_key"] = bool(self.ignore_win_key)
            save_config(self.cfg)
        except Exception:
            pass
        self.destroy()

    # ---------- UI log sink ----------
    def _append_log_ui(self, text: str):
        try:
            if self.log_box is None:
                return
            self.log_box.insert("end", text)
            self.log_box.see("end")
        except Exception:
            pass

    # ---------- status ----------
    def tick(self):
        if self.engine.recording:
            self.status_var.set(self.i18n.t("status_recording"))
        elif self.engine.playing:
            self.status_var.set(self.i18n.t("status_playing"))
        else:
            self.status_var.set(self.i18n.t("status_ready"))
        self.after(200, self.tick)

    # ---------- theme helpers ----------
    def current_colors(self) -> Dict[str, str]:
        tp = THEMES.get(self.theme_name, THEMES["Calm"])
        return tp.colors(self.appearance)

    def apply_glow(self, widget: ctk.CTkFrame, active: bool = True):
        lvl = int(self.glow_level)
        c = self.current_colors()
        if not active or lvl <= 0:
            widget.configure(border_width=0)
            return
        widget.configure(border_width={1: 1, 2: 2, 3: 3}.get(lvl, 2), border_color=c["accent"])

    def _style_nav_button(self, btn: ctk.CTkButton, active: bool):
        c = self.current_colors()
        if active:
            btn.configure(
                fg_color=c["card"],
                hover_color=c["border"],
                text_color=c["text"],
                corner_radius=14,
                border_width=2,
                border_color=c["accent"],
            )
        else:
            btn.configure(
                fg_color=c["panel"],
                hover_color=c["border"],
                text_color=c["text"],
                corner_radius=14,
                border_width=0,
            )

    def _highlight_nav(self):
        self._style_nav_button(self.btn_record, self._active_page == "record")
        self._style_nav_button(self.btn_library, self._active_page == "library")
        self._style_nav_button(self.btn_settings, self._active_page == "settings")

    def apply_theme(self):
        c = self.current_colors()

        self.configure(fg_color=c["bg"])
        self.sidebar.configure(fg_color=c["panel"])
        self.main.configure(fg_color=c["bg"])

        self.brand.configure(text_color=c["text"])
        self.footer_star.configure(text_color=c["border"])

        self.h_title.configure(text_color=c["text"])
        self.h_status.configure(text_color=c["muted"])

        self._highlight_nav()

        # record page
        self.card_ctrl.configure(fg_color=c["card"])
        self.card_hint.configure(fg_color=c["card"])
        self.apply_glow(self.card_ctrl, True)
        self.apply_glow(self.card_hint, True)

        self.rec_title.configure(text_color=c["text"])
        self.hint_title.configure(text_color=c["text"])
        self.hint_text.configure(text_color=c["muted"])

        # colored buttons (better design)
        self.btn_start.configure(fg_color=c["good"], hover_color=c["border"], text_color="#ffffff")
        self.btn_stop.configure(fg_color=c["danger"], hover_color=c["border"], text_color="#ffffff")
        self.btn_play.configure(fg_color=c["accent2"], hover_color=c["border"], text_color="#ffffff")
        self.btn_stopplay.configure(fg_color=c["danger"], hover_color=c["border"], text_color="#ffffff")
        self.btn_save.configure(fg_color=c["accent"], hover_color=c["border"], text_color="#ffffff")

        self.save_label.configure(text_color=c["muted"])
        self.save_entry.configure(fg_color=c["panel"], text_color=c["text"], border_color=c["border"])

        self.log_title.configure(text_color=c["text"])
        self.log_box.configure(fg_color=c["panel"], text_color=c["text"])
        self.btn_clear_log.configure(fg_color=c["panel"], hover_color=c["border"], text_color=c["text"])

        # library
        self.lib_left.configure(fg_color=c["card"])
        self.lib_right.configure(fg_color=c["card"])
        self.apply_glow(self.lib_left, True)
        self.apply_glow(self.lib_right, True)

        self.lib_title.configure(text_color=c["text"])
        self.search_entry.configure(fg_color=c["panel"], text_color=c["text"], border_color=c["border"])
        self.macros_scroll.configure(fg_color=c["panel"])

        self.preview_title.configure(text_color=c["text"])
        self.preview_meta.configure(text_color=c["muted"])
        self.preview_box.configure(fg_color=c["panel"], text_color=c["text"])

        # action buttons
        for b in [self.btn_load, self.btn_rename, self.btn_clone, self.btn_export, self.btn_import]:
            b.configure(fg_color=c["panel"], hover_color=c["border"], text_color=c["text"], border_width=2, border_color=c["accent2"])
        self.btn_delete.configure(fg_color=c["danger"], hover_color=c["border"], text_color="#ffffff")
        self.btn_play_sel.configure(fg_color=c["accent"], hover_color=c["border"], text_color="#ffffff")
        self.btn_stop_sel.configure(fg_color=c["danger"], hover_color=c["border"], text_color="#ffffff")

        self.bind_label.configure(text_color=c["text"])
        self.bind_entry.configure(fg_color=c["panel"], text_color=c["text"], border_color=c["border"])
        self.btn_bind.configure(fg_color=c["accent2"], hover_color=c["border"], text_color="#ffffff")
        self.btn_unbind.configure(fg_color=c["danger"], hover_color=c["border"], text_color="#ffffff")
        self.binds_box.configure(fg_color=c["panel"], text_color=c["text"])

        self._restyle_macro_buttons()

        # settings
        self.set_wrap.configure(fg_color=c["card"])
        self.apply_glow(self.set_wrap, True)
        self.set_title.configure(text_color=c["text"])
        self.set_hint.configure(text_color=c["muted"])

        for lab in self.set_labels:
            lab.configure(text_color=c["text"])
        for ent in self.set_entries:
            ent.configure(fg_color=c["panel"], text_color=c["text"], border_color=c["border"])

        self.btn_apply.configure(fg_color=c["accent"], hover_color=c["border"], text_color="#ffffff")
        self.btn_reset.configure(fg_color=c["panel"], hover_color=c["border"], text_color=c["text"], border_width=2, border_color=c["accent2"])

        self.appearance_menu.configure(fg_color=c["panel"], button_color=c["border"], button_hover_color=c["accent2"], text_color=c["text"])
        self.theme_menu.configure(fg_color=c["panel"], button_color=c["border"], button_hover_color=c["accent2"], text_color=c["text"])
        self.lang_menu.configure(fg_color=c["panel"], button_color=c["border"], button_hover_color=c["accent2"], text_color=c["text"])
        self.glow_slider.configure(progress_color=c["accent"])
        self.ignore_win_switch.configure(progress_color=c["accent2"], text_color=c["text"])

        # base hotkeys edits
        for lab in self.hk_labels:
            lab.configure(text_color=c["text"])
        for ent in self.hk_entries:
            ent.configure(fg_color=c["panel"], text_color=c["text"], border_color=c["border"])

        self.btn_apply_hotkeys.configure(fg_color=c["accent2"], hover_color=c["border"], text_color="#ffffff")

    # ---------- navigation ----------
    def show_page(self, which: str, animate: bool = True):
        self._active_page = which
        pages = {
            "record": (self.page_record, self.i18n.t("nav_record")),
            "library": (self.page_library, self.i18n.t("nav_library")),
            "settings": (self.page_settings, self.i18n.t("nav_settings")),
        }
        frame, title = pages[which]

        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid_remove()

        frame.grid()
        self.h_title.configure(text=title)
        self._highlight_nav()

    # =========================
    # i18n refresh
    # =========================
    def set_language(self, tag: str):
        # tag can be "auto" in UI but internal i18n needs real tag
        self.cfg["lang"] = tag
        save_config(self.cfg)

        lang = get_windows_ui_lang_tag() if tag == "auto" else tag
        if lang not in SUPPORTED_LANGS:
            lang = "en"
        self.i18n = I18N(lang)

        self.apply_texts()
        self.apply_theme()
        self.refresh_library()
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    def apply_texts(self):
        # window + sidebar
        self.title(self.i18n.t("app_name", APP_NAME))
        self.brand.configure(text=self.i18n.t("app_name", APP_NAME))

        self.btn_record.configure(text=self.i18n.t("nav_record"))
        self.btn_library.configure(text=self.i18n.t("nav_library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings"))

        # record
        self.rec_title.configure(text=self.i18n.t("record_title"))
        self.btn_start.configure(text=self.i18n.t("record_start"))
        self.btn_stop.configure(text=self.i18n.t("record_stop"))
        self.btn_play.configure(text=self.i18n.t("record_play_loaded"))
        self.btn_stopplay.configure(text=self.i18n.t("record_stop_play"))
        self.save_label.configure(text=self.i18n.t("record_save_label"))
        self.btn_save.configure(text=self.i18n.t("record_save_btn"))
        self.hint_title.configure(text=self.i18n.t("hotkeys_title"))

        # hint text: show current base hotkeys from config
        hk = self.cfg.get("base_hotkeys", DEFAULT_CONFIG["base_hotkeys"])
        hint = (
            f"{self.i18n.t('hotkeys_title')}\n"
            f"{hk.get('record','')} — {self.i18n.t('hk_record')}\n"
            f"{hk.get('stop_record','')} — {self.i18n.t('hk_stop_record')}\n"
            f"{hk.get('play_loaded','')} — {self.i18n.t('hk_play_loaded')}\n"
            f"{hk.get('stop_play','')} — {self.i18n.t('hk_stop_play')}\n\n"
            f"{self.i18n.t('hotkeys_hint')}"
        )
        self.hint_text.configure(text=hint)

        self.log_title.configure(text=self.i18n.t("log_title"))
        self.btn_clear_log.configure(text=self.i18n.t("log_clear"))

        # library
        self.lib_title.configure(text=self.i18n.t("lib_title"))
        self.search_entry.configure(placeholder_text=self.i18n.t("search_placeholder"))
        self.btn_load.configure(text=self.i18n.t("btn_load"))
        self.btn_delete.configure(text=self.i18n.t("btn_delete"))
        self.btn_rename.configure(text=self.i18n.t("btn_rename"))
        self.btn_clone.configure(text=self.i18n.t("btn_clone"))
        self.btn_export.configure(text=self.i18n.t("btn_export"))
        self.btn_import.configure(text=self.i18n.t("btn_import"))
        self.bind_label.configure(text=self.i18n.t("bind_label"))
        self.bind_entry.configure(placeholder_text=self.i18n.t("bind_placeholder"))
        self.btn_bind.configure(text=self.i18n.t("btn_bind"))
        self.btn_unbind.configure(text=self.i18n.t("btn_unbind"))
        self.btn_play_sel.configure(text=self.i18n.t("btn_play_selected"))
        self.btn_stop_sel.configure(text=self.i18n.t("danger_stop"))

        # settings
        self.set_title.configure(text=self.i18n.t("settings_title"))
        self.lab_repeat.configure(text=self.i18n.t("repeat"))
        self.lab_loop.configure(text=self.i18n.t("loop"))
        self.lab_speed.configure(text=self.i18n.t("speed"))
        self.lab_delay.configure(text=self.i18n.t("delay"))
        self.btn_apply.configure(text=self.i18n.t("apply"))
        self.btn_reset.configure(text=self.i18n.t("reset"))

        self.appearance_label.configure(text=self.i18n.t("appearance"))
        self.theme_label.configure(text=self.i18n.t("theme"))
        self.lang_label.configure(text=self.i18n.t("language"))
        self.ignore_win_switch.configure(text=self.i18n.t("ignore_win"))

        self.hk_title.configure(text=self.i18n.t("base_hotkeys"))
        self.hk_labels[0].configure(text=self.i18n.t("hk_record"))
        self.hk_labels[1].configure(text=self.i18n.t("hk_stop_record"))
        self.hk_labels[2].configure(text=self.i18n.t("hk_play_loaded"))
        self.hk_labels[3].configure(text=self.i18n.t("hk_stop_play"))
        self.btn_apply_hotkeys.configure(text=self.i18n.t("apply"))

    # =========================
    # Settings helpers
    # =========================
    def current_settings(self) -> Dict[str, Any]:
        repeat = max(1, safe_int(self.repeat_var.get(), 1))
        loop_seconds = max(0, safe_int(self.loop_var.get(), 0))
        speed = max(0.05, safe_float(self.speed_var.get(), 1.0))
        delay = max(0.0, safe_float(self.delay_var.get(), 0.0))

        repeat = min(repeat, 9999)
        loop_seconds = min(loop_seconds, 24 * 3600)
        speed = min(speed, 5.0)
        delay = min(delay, 60.0)

        return {"repeat": repeat, "loop_seconds": loop_seconds, "speed": speed, "start_delay": delay}

    def apply_settings(self, s: Dict[str, Any]):
        self.repeat_var.set(str(s.get("repeat", 1)))
        self.loop_var.set(str(s.get("loop_seconds", 0)))
        self.speed_var.set(str(s.get("speed", 1.0)))
        self.delay_var.set(str(s.get("start_delay", 0.0)))

    # =========================
    # Record page
    # =========================
    def build_record_page(self):
        self.page_record.grid_columnconfigure(0, weight=1)
        self.page_record.grid_columnconfigure(1, weight=1)
        self.page_record.grid_rowconfigure(2, weight=1)

        self.card_ctrl = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_ctrl.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=(16, 10))

        self.rec_title = ctk.CTkLabel(self.card_ctrl, text=self.i18n.t("record_title"), font=ctk.CTkFont(size=16, weight="bold"))
        self.rec_title.pack(anchor="w", padx=16, pady=(16, 8))

        row1 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=6)

        self.btn_start = ctk.CTkButton(row1, text=self.i18n.t("record_start"), command=self.engine.start_recording)
        self.btn_start.pack(side="left", padx=6)

        self.btn_stop = ctk.CTkButton(row1, text=self.i18n.t("record_stop"), command=self.engine.stop_recording)
        self.btn_stop.pack(side="left", padx=6)

        row2 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=6)

        self.btn_play = ctk.CTkButton(row2, text=self.i18n.t("record_play_loaded"), command=self.play_from_ui)
        self.btn_play.pack(side="left", padx=6)

        self.btn_stopplay = ctk.CTkButton(row2, text=self.i18n.t("record_stop_play"), command=self.engine.stop_playing)
        self.btn_stopplay.pack(side="left", padx=6)

        self.save_label = ctk.CTkLabel(self.card_ctrl, text=self.i18n.t("record_save_label"), font=ctk.CTkFont(size=12))
        self.save_label.pack(anchor="w", padx=16, pady=(12, 4))

        self.save_name = ctk.StringVar(value="New macro")
        self.save_entry = ctk.CTkEntry(self.card_ctrl, textvariable=self.save_name)
        self.save_entry.pack(fill="x", padx=16, pady=6)

        self.btn_save = ctk.CTkButton(self.card_ctrl, text=self.i18n.t("record_save_btn"), command=self.save_current_macro)
        self.btn_save.pack(fill="x", padx=16, pady=(6, 16))

        self.card_hint = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_hint.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=(16, 10))

        self.hint_title = ctk.CTkLabel(self.card_hint, text=self.i18n.t("hotkeys_title"), font=ctk.CTkFont(size=16, weight="bold"))
        self.hint_title.pack(anchor="w", padx=16, pady=(16, 8))

        self.hint_text = ctk.CTkLabel(self.card_hint, text="", justify="left", wraplength=420)
        self.hint_text.pack(anchor="w", padx=16, pady=(0, 16))

        self.log_title = ctk.CTkLabel(self.page_record, text=self.i18n.t("log_title"), font=ctk.CTkFont(size=14, weight="bold"))
        self.log_title.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 6))

        self.log_box = ctk.CTkTextbox(self.page_record, height=220, corner_radius=18)
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 10))

        self.btn_clear_log = ctk.CTkButton(self.page_record, text=self.i18n.t("log_clear"), command=self.clear_log_ui)
        self.btn_clear_log.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

        self.apply_texts()

    def clear_log_ui(self):
        try:
            self.log_box.delete("1.0", "end")
        except Exception:
            pass

    def play_from_ui(self):
        s = self.current_settings()
        self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])

    def save_current_macro(self):
        name = self.save_name.get().strip()
        if not name:
            messagebox.showwarning("Name", "Enter macro name.")
            return
        if not self.engine.events:
            messagebox.showwarning("Empty", "Record something first.")
            return

        if self.db.exists(name):
            if not messagebox.askyesno("Overwrite", f"Macro '{name}' exists. Overwrite?"):
                return

        settings = self.current_settings()
        self.db.put(name, self.engine.events, settings)
        self.logger.info(f"Saved: {name} (events: {len(self.engine.events)})")
        self.refresh_library()
        self.show_page("library")

    # =========================
    # Library page
    # =========================
    def build_library_page(self):
        self.page_library.grid_columnconfigure(0, weight=1)
        self.page_library.grid_columnconfigure(1, weight=2)
        self.page_library.grid_rowconfigure(0, weight=1)

        self.lib_left = ctk.CTkFrame(self.page_library, corner_radius=18)
        self.lib_left.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=16)
        self.lib_left.grid_rowconfigure(3, weight=1)
        self.lib_left.grid_columnconfigure(0, weight=1)

        self.lib_title = ctk.CTkLabel(self.lib_left, text=self.i18n.t("lib_title"), font=ctk.CTkFont(size=16, weight="bold"))
        self.lib_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(self.lib_left, textvariable=self.search_var, placeholder_text=self.i18n.t("search_placeholder"))
        self.search_entry.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_library())

        self.macros_scroll = ctk.CTkScrollableFrame(self.lib_left, corner_radius=14)
        self.macros_scroll.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")
        self.macro_buttons: Dict[str, ctk.CTkButton] = {}
        self.selected_macro: Optional[str] = None

        actions = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)

        self.btn_load = ctk.CTkButton(actions, text=self.i18n.t("btn_load"), command=self.load_selected)
        self.btn_load.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_delete = ctk.CTkButton(actions, text=self.i18n.t("btn_delete"), command=self.delete_selected)
        self.btn_delete.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions2 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions2.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions2.grid_columnconfigure((0, 1), weight=1)

        self.btn_rename = ctk.CTkButton(actions2, text=self.i18n.t("btn_rename"), command=self.rename_selected)
        self.btn_rename.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_clone = ctk.CTkButton(actions2, text=self.i18n.t("btn_clone"), command=self.clone_selected)
        self.btn_clone.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions3 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions3.grid(row=6, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions3.grid_columnconfigure((0, 1), weight=1)

        self.btn_export = ctk.CTkButton(actions3, text=self.i18n.t("btn_export"), command=self.export_selected)
        self.btn_export.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_import = ctk.CTkButton(actions3, text=self.i18n.t("btn_import"), command=self.import_macro)
        self.btn_import.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        # right panel
        self.lib_right = ctk.CTkFrame(self.page_library, corner_radius=18)
        self.lib_right.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=16)
        self.lib_right.grid_rowconfigure(4, weight=1)
        self.lib_right.grid_columnconfigure(0, weight=1)

        self.preview_title = ctk.CTkLabel(self.lib_right, text=self.i18n.t("preview_none"), font=ctk.CTkFont(size=18, weight="bold"))
        self.preview_title.grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")

        self.preview_meta = ctk.CTkLabel(self.lib_right, text=self.i18n.t("preview_none"))
        self.preview_meta.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")

        bind_row = ctk.CTkFrame(self.lib_right, fg_color="transparent")
        bind_row.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="ew")
        bind_row.grid_columnconfigure(1, weight=1)

        self.bind_label = ctk.CTkLabel(bind_row, text=self.i18n.t("bind_label"), width=90, anchor="w")
        self.bind_label.grid(row=0, column=0, sticky="w")

        self.bind_var = ctk.StringVar(value="F6")
        self.bind_entry = ctk.CTkEntry(bind_row, textvariable=self.bind_var, placeholder_text=self.i18n.t("bind_placeholder"))
        self.bind_entry.grid(row=0, column=1, sticky="ew", padx=(10, 10))

        self.btn_bind = ctk.CTkButton(bind_row, text=self.i18n.t("btn_bind"), width=110, command=self.bind_selected)
        self.btn_bind.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.btn_unbind = ctk.CTkButton(bind_row, text=self.i18n.t("btn_unbind"), width=90, command=self.unbind_selected)
        self.btn_unbind.grid(row=0, column=3, sticky="e")

        self.binds_box = ctk.CTkTextbox(self.lib_right, height=120, corner_radius=14)
        self.binds_box.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        self.preview_box = ctk.CTkTextbox(self.lib_right, corner_radius=14)
        self.preview_box.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="nsew")

        playbar = ctk.CTkFrame(self.lib_right, fg_color="transparent")
        playbar.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        playbar.grid_columnconfigure((0, 1), weight=1)

        self.btn_play_sel = ctk.CTkButton(playbar, text=self.i18n.t("btn_play_selected"), command=self.play_selected)
        self.btn_play_sel.grid(row=0, column=0, padx=6, sticky="ew")

        self.btn_stop_sel = ctk.CTkButton(playbar, text=self.i18n.t("danger_stop"), command=self.engine.stop_playing)
        self.btn_stop_sel.grid(row=0, column=1, padx=6, sticky="ew")

        self.refresh_library()
        self.refresh_binds_box()

    def refresh_binds_box(self):
        self.binds_box.delete("1.0", "end")
        binds = self.db.binds()
        if not binds:
            self.binds_box.insert("end", "(no binds)\n")
            return
        for hk, mn in sorted(binds.items(), key=lambda x: x[0]):
            self.binds_box.insert("end", f"{hk}  ->  {mn}\n")

    def refresh_library(self):
        c = self.current_colors()
        q = self.search_var.get().strip().lower()

        for child in self.macros_scroll.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self.macro_buttons.clear()

        names = []
        for n in self.db.names():
            if q and q not in n.lower():
                continue
            names.append(n)

        if not names:
            empty = ctk.CTkLabel(self.macros_scroll, text="(empty)", text_color=c["muted"])
            empty.pack(anchor="w", padx=8, pady=8)
            self.selected_macro = None
            self.preview_clear()
            return

        if self.selected_macro not in names:
            self.selected_macro = names[0]

        for n in names:
            btn = ctk.CTkButton(
                self.macros_scroll,
                text=n,
                anchor="w",
                corner_radius=12,
                command=lambda name=n: self.select_macro(name),
            )
            btn.pack(fill="x", padx=6, pady=6)
            self.macro_buttons[n] = btn

        self._restyle_macro_buttons()
        self.preview_selected()

    def _restyle_macro_buttons(self):
        if not hasattr(self, "macro_buttons"):
            return
        c = self.current_colors()
        for name, btn in self.macro_buttons.items():
            if name == self.selected_macro:
                btn.configure(fg_color=c["panel"], hover_color=c["border"], text_color=c["text"], border_width=2, border_color=c["accent"])
            else:
                btn.configure(fg_color=c["card"], hover_color=c["border"], text_color=c["text"], border_width=0)

    def select_macro(self, name: str):
        self.selected_macro = name
        self._restyle_macro_buttons()
        self.preview_selected()

    def preview_clear(self):
        self.preview_title.configure(text=self.i18n.t("preview_none"))
        self.preview_meta.configure(text=self.i18n.t("preview_none"))
        self.preview_box.delete("1.0", "end")

    def preview_selected(self):
        name = self.selected_macro
        if not name:
            self.preview_clear()
            return
        item = self.db.get(name)
        if not item:
            self.preview_clear()
            return

        created = item.get("created", 0)
        created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created)) if created else "—"
        count = len(item.get("events", []))
        st = item.get("settings", {})
        meta = f"Created: {created_str} | Events: {count} | repeat={st.get('repeat',1)} loop={st.get('loop_seconds',0)} speed={st.get('speed',1.0)}"

        self.preview_title.configure(text=name)
        self.preview_meta.configure(text=meta)
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("end", json.dumps(st, ensure_ascii=False, indent=2))

    def load_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning("Select", "Pick a macro.")
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", [])]
        self.apply_settings(item.get("settings", {}))
        self.logger.info(f"Loaded: {name} (events: {len(self.engine.events)})")
        self.show_page("record")

    def play_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning("Select", "Pick a macro.")
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", [])]
        self.apply_settings(item.get("settings", {}))
        s = self.current_settings()
        self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])

    def delete_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning("Select", "Pick a macro.")
            return
        if not messagebox.askyesno("Delete", f"Delete '{name}'?"):
            return
        self.db.delete(name)
        self.logger.info(f"Deleted: {name}")
        self.selected_macro = None
        self.refresh_library()
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    def rename_selected(self):
        old = self.selected_macro
        if not old:
            messagebox.showwarning("Select", "Pick a macro.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Rename")
        dialog.geometry("420x180")
        dialog.resizable(False, False)
        dialog.grab_set()

        frm = ctk.CTkFrame(dialog, corner_radius=18)
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(frm, text="New name:", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        var = ctk.StringVar(value=old)
        ent = ctk.CTkEntry(frm, textvariable=var)
        ent.pack(fill="x", padx=12, pady=6)
        ent.focus_set()

        def do():
            new = var.get().strip()
            if not new:
                messagebox.showwarning("Name", "Empty.")
                return
            if new == old:
                dialog.destroy()
                return
            ok = self.db.rename(old, new)
            if not ok:
                messagebox.showerror("Error", "Name already exists.")
                return
            self.logger.info(f"Renamed: {old} -> {new}")
            dialog.destroy()
            self.selected_macro = new
            self.refresh_library()
            self.refresh_binds_box()
            self.rebuild_hotkeys()

        btns = ctk.CTkFrame(frm, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(10, 12))
        ctk.CTkButton(btns, text="OK", command=do).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)

    def clone_selected(self):
        src = self.selected_macro
        if not src:
            messagebox.showwarning("Select", "Pick a macro.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Clone")
        dialog.geometry("460x190")
        dialog.resizable(False, False)
        dialog.grab_set()

        frm = ctk.CTkFrame(dialog, corner_radius=18)
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(frm, text=f"Clone macro: {src}", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        var = ctk.StringVar(value=f"{src} (copy)")
        ent = ctk.CTkEntry(frm, textvariable=var)
        ent.pack(fill="x", padx=12, pady=6)
        ent.focus_set()

        def do():
            dst = var.get().strip()
            if not dst:
                messagebox.showwarning("Name", "Empty.")
                return
            ok = self.db.clone(src, dst)
            if not ok:
                messagebox.showerror("Error", "Failed (name taken?)")
                return
            self.logger.info(f"Cloned: {src} -> {dst}")
            dialog.destroy()
            self.selected_macro = dst
            self.refresh_library()

        btns = ctk.CTkFrame(frm, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(10, 12))
        ctk.CTkButton(btns, text="OK", command=do).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)

    def export_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning("Export", "Pick a macro.")
            return
        item = self.db.get(name)
        if not item:
            return

        default_name = f"{name}.json"
        path = filedialog.asksaveasfilename(
            title="Export macro",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON", "*.json")]
        )
        if not path:
            return

        try:
            payload = {
                "format": "saonix_macro_v1",
                "name": name,
                "created": item.get("created", int(time.time())),
                "settings": item.get("settings", {}),
                "events": item.get("events", []),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Exported: {name} -> {path}")
        except Exception as e:
            self.logger.error(f"Export error: {e}")
            messagebox.showerror("Export", f"Error: {e}")

    def import_macro(self):
        path = filedialog.askopenfilename(
            title="Import macro",
            filetypes=[("JSON", "*.json")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            if not isinstance(payload, dict) or "events" not in payload:
                raise ValueError("Bad file format")

            name = str(payload.get("name", os.path.splitext(os.path.basename(path))[0])).strip()
            if not name:
                name = "Imported macro"

            if self.db.exists(name):
                if not messagebox.askyesno("Import", f"Macro '{name}' exists. Overwrite?"):
                    base = name
                    i = 2
                    while self.db.exists(f"{base} ({i})"):
                        i += 1
                    name = f"{base} ({i})"

            settings = payload.get("settings", {})
            events = payload.get("events", [])

            ev_objs = []
            for e in events:
                if not isinstance(e, dict):
                    continue
                if not all(k in e for k in ("t", "device", "type", "data")):
                    continue
                ev_objs.append(Event(
                    t=float(e["t"]),
                    device=str(e["device"]),
                    type=str(e["type"]),
                    data=dict(e["data"]) if isinstance(e["data"], dict) else {}
                ))

            self.db.put(name, ev_objs, settings if isinstance(settings, dict) else {})
            self.logger.info(f"Imported: {name} (events: {len(ev_objs)})")
            self.selected_macro = name
            self.refresh_library()

        except Exception as e:
            self.logger.error(f"Import error: {e}")
            self.logger.error(traceback.format_exc())
            messagebox.showerror("Import", f"Error: {e}")

    def bind_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning("Bind", "Pick a macro.")
            return
        hk_raw = self.bind_var.get()
        hk = normalize_hotkey(hk_raw)
        if not hk:
            messagebox.showerror("Bind", "Bad format. Example: F6 or Ctrl+Alt+F6")
            return

        binds = self.db.binds()
        if hk in binds and binds[hk] != name:
            if not messagebox.askyesno("Conflict", f"{hk} already bound to '{binds[hk]}'. Replace?"):
                return

        self.db.set_bind(hk, name)
        self.logger.info(f"Bind: {hk} -> {name}")
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    def unbind_selected(self):
        hk_raw = self.bind_var.get()
        hk = normalize_hotkey(hk_raw)
        if not hk:
            messagebox.showerror("Unbind", "Enter hotkey, e.g. F6")
            return
        self.db.remove_bind(hk)
        self.logger.info(f"Unbound: {hk}")
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    # =========================
    # Settings page
    # =========================
    def build_settings_page(self):
        self.page_settings.grid_columnconfigure(0, weight=1)
        self.page_settings.grid_rowconfigure(0, weight=1)

        self.set_wrap = ctk.CTkFrame(self.page_settings, corner_radius=18)
        self.set_wrap.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.set_wrap.grid_columnconfigure(0, weight=1)

        self.set_title = ctk.CTkLabel(self.set_wrap, text=self.i18n.t("settings_title"), font=ctk.CTkFont(size=18, weight="bold"))
        self.set_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        # appearance/theme/lang row
        top = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        top.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        top.grid_columnconfigure((0, 1, 2), weight=1)

        self.appearance_label = ctk.CTkLabel(top, text=self.i18n.t("appearance"), anchor="w")
        self.appearance_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.appearance_menu = ctk.CTkOptionMenu(top, values=["Dark", "Light"], command=self.on_appearance)
        self.appearance_menu.set(self.appearance)
        self.appearance_menu.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        self.theme_label = ctk.CTkLabel(top, text=self.i18n.t("theme"), anchor="w")
        self.theme_label.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.theme_menu = ctk.CTkOptionMenu(top, values=list(THEMES.keys()), command=self.on_theme)
        self.theme_menu.set(self.theme_name)
        self.theme_menu.grid(row=1, column=1, sticky="ew", padx=(8, 8))

        self.lang_label = ctk.CTkLabel(top, text=self.i18n.t("language"), anchor="w")
        self.lang_label.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        lang_values = ["auto"] + SUPPORTED_LANGS
        self.lang_menu = ctk.CTkOptionMenu(top, values=lang_values, command=self.set_language)
        self.lang_menu.set(self.cfg.get("lang", "auto"))
        self.lang_menu.grid(row=1, column=2, sticky="ew", padx=(8, 0))

        # glow + ignore win
        mid = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        mid.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="ew")
        mid.grid_columnconfigure(0, weight=1)

        self.glow_slider = ctk.CTkSlider(mid, from_=0, to=3, number_of_steps=3, command=self.on_glow)
        self.glow_slider.set(self.glow_level)
        self.glow_slider.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.ignore_win_switch = ctk.CTkSwitch(mid, text=self.i18n.t("ignore_win"), command=self.on_ignore_win)
        self.ignore_win_switch.select() if self.ignore_win_key else self.ignore_win_switch.deselect()
        self.ignore_win_switch.grid(row=1, column=0, sticky="w", pady=(8, 0))

        # playback settings form
        self.repeat_var = ctk.StringVar(value="1")
        self.loop_var = ctk.StringVar(value="0")
        self.speed_var = ctk.StringVar(value="1.0")
        self.delay_var = ctk.StringVar(value="0")

        self.set_labels = []
        self.set_entries = []

        def add_row(r: int, label_widget_name: str, var: ctk.StringVar, placeholder: str):
            row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
            row.grid(row=r, column=0, padx=16, pady=8, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            lab = ctk.CTkLabel(row, text=self.i18n.t(label_widget_name), width=190, anchor="w")
            lab.grid(row=0, column=0, sticky="w")
            ent = ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder)
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))

            self.set_labels.append(lab)
            self.set_entries.append(ent)
            return lab

        self.lab_repeat = add_row(3, "repeat", self.repeat_var, "e.g. 5")
        self.lab_loop = add_row(4, "loop", self.loop_var, "e.g. 7200")
        self.lab_speed = add_row(5, "speed", self.speed_var, "0.5 / 1.0 / 2.0")
        self.lab_delay = add_row(6, "delay", self.delay_var, "e.g. 3")

        self.set_hint = ctk.CTkLabel(self.set_wrap, text="If Loop > 0, Repeat is ignored.", anchor="w")
        self.set_hint.grid(row=7, column=0, padx=16, pady=(4, 12), sticky="w")

        btns = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        btns.grid(row=8, column=0, padx=16, pady=(0, 16), sticky="ew")

        self.btn_apply = ctk.CTkButton(btns, text=self.i18n.t("apply"), command=self.apply_settings_to_engine)
        self.btn_apply.pack(side="left", padx=6)

        self.btn_reset = ctk.CTkButton(btns, text=self.i18n.t("reset"), command=self.reset_settings)
        self.btn_reset.pack(side="left", padx=6)

        # base hotkeys block
        self.hk_title = ctk.CTkLabel(self.set_wrap, text=self.i18n.t("base_hotkeys"), font=ctk.CTkFont(size=16, weight="bold"))
        self.hk_title.grid(row=9, column=0, padx=16, pady=(0, 8), sticky="w")

        self.hk_labels = []
        self.hk_entries = []
        self.hk_vars = {}

        def add_hk_row(r: int, key_name: str, label_key: str):
            row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
            row.grid(row=r, column=0, padx=16, pady=6, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            lab = ctk.CTkLabel(row, text=self.i18n.t(label_key), width=190, anchor="w")
            lab.grid(row=0, column=0, sticky="w")
            var = ctk.StringVar(value=self.cfg.get("base_hotkeys", {}).get(key_name, DEFAULT_CONFIG["base_hotkeys"][key_name]))
            ent = ctk.CTkEntry(row, textvariable=var, placeholder_text="Ctrl+Alt+1 / F6 / Shift+Z")
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))

            self.hk_labels.append(lab)
            self.hk_entries.append(ent)
            self.hk_vars[key_name] = var

        add_hk_row(10, "record", "hk_record")
        add_hk_row(11, "stop_record", "hk_stop_record")
        add_hk_row(12, "play_loaded", "hk_play_loaded")
        add_hk_row(13, "stop_play", "hk_stop_play")

        self.btn_apply_hotkeys = ctk.CTkButton(self.set_wrap, text=self.i18n.t("apply"), command=self.apply_base_hotkeys)
        self.btn_apply_hotkeys.grid(row=14, column=0, padx=16, pady=(6, 16), sticky="w")

    def reset_settings(self):
        self.repeat_var.set("1")
        self.loop_var.set("0")
        self.speed_var.set("1.0")
        self.delay_var.set("0")
        self.apply_settings_to_engine()
        self.logger.info("Settings reset.")

    def apply_settings_to_engine(self):
        s = self.current_settings()
        self.logger.info(f"Applied: repeat={s['repeat']} loop={s['loop_seconds']} speed={s['speed']} delay={s['start_delay']}")

    def on_appearance(self, mode: str):
        self.appearance = "Light" if mode == "Light" else "Dark"
        ctk.set_appearance_mode(self.appearance)
        self.cfg["appearance"] = self.appearance
        save_config(self.cfg)
        self.apply_theme()

    def on_theme(self, name: str):
        self.theme_name = name if name in THEMES else "Calm"
        self.cfg["theme"] = self.theme_name
        save_config(self.cfg)
        self.apply_theme()

    def on_glow(self, _=None):
        self.glow_level = int(round(float(self.glow_slider.get())))
        self.cfg["glow"] = int(self.glow_level)
        save_config(self.cfg)
        self.apply_theme()

    def on_ignore_win(self):
        self.ignore_win_key = bool(self.ignore_win_switch.get())
        self.engine.set_ignore_win(self.ignore_win_key)
        self.cfg["ignore_win_key"] = bool(self.ignore_win_key)
        save_config(self.cfg)
        self.logger.info(f"Ignore Win key: {self.ignore_win_key}")

    def apply_base_hotkeys(self):
        # validate and normalize
        new_map = {}
        for k in ("record", "stop_record", "play_loaded", "stop_play"):
            raw = self.hk_vars[k].get().strip()
            nk = normalize_hotkey(raw)
            if not nk:
                messagebox.showerror("Hotkeys", f"Bad hotkey format: {raw}")
                return
            new_map[k] = raw  # keep user-friendly in config
        self.cfg["base_hotkeys"] = new_map
        save_config(self.cfg)
        self.rebuild_hotkeys()
        self.apply_texts()
        self.logger.info("Base hotkeys updated.")

    # =========================
    # Hotkeys
    # =========================
    def rebuild_hotkeys(self):
        base = self.cfg.get("base_hotkeys", DEFAULT_CONFIG["base_hotkeys"])

        mapping: Dict[str, Callable[[], None]] = {}
        # base hotkeys
        hk_record = normalize_hotkey(base.get("record", "Ctrl+Alt+1"))
        hk_stop_record = normalize_hotkey(base.get("stop_record", "Ctrl+Alt+2"))
        hk_play_loaded = normalize_hotkey(base.get("play_loaded", "Ctrl+Alt+3"))
        hk_stop_play = normalize_hotkey(base.get("stop_play", "Ctrl+Alt+4"))

        if hk_record: mapping[hk_record] = self.engine.start_recording
        if hk_stop_record: mapping[hk_stop_record] = self.engine.stop_recording
        if hk_play_loaded: mapping[hk_play_loaded] = self.play_from_ui
        if hk_stop_play: mapping[hk_stop_play] = self.engine.stop_playing

        # macro binds
        binds = self.db.binds()
        for hk, macro_name in binds.items():
            if hk in mapping:
                self.logger.warn(f"Bind conflicts with base hotkey, skipped: {hk}")
                continue

            def make_play(name=macro_name):
                def _f():
                    item = self.db.get(name)
                    if not item:
                        self.logger.warn(f"[bind] macro not found: {name}")
                        return
                    self.engine.events = [Event(**e) for e in item.get("events", [])]
                    self.apply_settings(item.get("settings", {}))
                    s = self.current_settings()
                    self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])
                    self.logger.info(f"[bind] play: {name}")
                return _f

            mapping[hk] = make_play()

        self.hk.set(mapping)

    # =========================
    # misc
    # =========================
    def clear_log_ui(self):
        try:
            self.log_box.delete("1.0", "end")
        except Exception:
            pass


def main():
    try:
        app = SaonixApp()
        app.mainloop()
    except Exception as e:
        ensure_dirs()
        try:
            with open(os.path.join(LOG_DIR, "crash_log.txt"), "w", encoding="utf-8") as f:
                f.write(str(e) + "\n\n" + traceback.format_exc())
        except Exception:
            pass
        print("Crash. See logs/crash_log.txt")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
