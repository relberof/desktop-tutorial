# saonix.py
# Single-file: loader (GitHub update + cached downloads) + app (themes/glow/i18n/hotkeys/library/record)
# Build without console: pyinstaller --noconsole --onefile --name Saonix saonix.py

import os
import sys
import json
import time
import ctypes
import queue
import shutil
import hashlib
import zipfile
import threading
import traceback
import locale as pylocale
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Callable

import customtkinter as ctk
from tkinter import messagebox, filedialog

from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, KeyCode, Controller as KeyboardController


# ============================================================
# Update / Loader config
# ============================================================

APP_NAME = "Saonix"

# Put a manifest.json in your GitHub repo, example format:
# {
#   "version": "1.0.3",
#   "bundle_url": "https://github.com/<user>/<repo>/releases/download/v1.0.3/saonix_bundle.zip",
#   "bundle_sha256": "<optional sha256>",
#   "notes": "optional"
# }
UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/relberof/desktop-tutorial/main/saonix_manifest.json"

# Optional online icon (cached via ETag/Last-Modified, not re-downloaded if unchanged)
ICON_PNG_URL = "https://raw.githubusercontent.com/relberof/desktop-tutorial/69cec69713c6f91563ba3c2c87c6215042e67ee5/icon.png"

SUPPORT_DISCORD = "Relberof"


# ============================================================
# Paths
# ============================================================

def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p

def _writable_programdata_root() -> str:
    base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    root = os.path.join(base, APP_NAME)
    try:
        _ensure_dir(root)
        test_path = os.path.join(root, "_rw_test.tmp")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        return root
    except Exception:
        here = os.path.abspath(os.path.dirname(sys.argv[0] if sys.argv else __file__))
        return _ensure_dir(os.path.join(here, APP_NAME))

ROOT = _writable_programdata_root()
DIR_APP = _ensure_dir(os.path.join(ROOT, "app"))
DIR_DATA = _ensure_dir(os.path.join(ROOT, "data"))
DIR_CACHE = _ensure_dir(os.path.join(ROOT, "cache"))
DIR_LOGS = _ensure_dir(os.path.join(ROOT, "logs"))
DIR_LOCALES = _ensure_dir(os.path.join(ROOT, "locales"))

DB_FILE = os.path.join(DIR_DATA, "macros.json")
SETTINGS_FILE = os.path.join(DIR_DATA, "settings.json")
LOCAL_VERSION_FILE = os.path.join(DIR_DATA, "local_version.json")
LOG_FILE = os.path.join(DIR_LOGS, "saonix.log")

CACHED_MANIFEST_FILE = os.path.join(DIR_CACHE, "manifest_cached.json")
CACHED_MANIFEST_META = os.path.join(DIR_CACHE, "manifest_meta.json")

CACHED_ICON_FILE = os.path.join(DIR_CACHE, "icon.png")
CACHED_ICON_META = os.path.join(DIR_CACHE, "icon_meta.json")


# ============================================================
# Utils
# ============================================================

def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _safe_int(s: Any, d: int) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return d

def _safe_float(s: Any, d: float) -> float:
    try:
        return float(str(s).strip())
    except Exception:
        return d

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _atomic_write_json(path: str, data: Any):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ============================================================
# Logger
# ============================================================

class Logger:
    def __init__(self):
        self._lock = threading.Lock()
        self._sink: Optional[Callable[[str], None]] = None

    def set_sink(self, sink: Optional[Callable[[str], None]]):
        self._sink = sink

    def _write(self, level: str, msg: str):
        line = f"[{_ts()}] [{level}] {msg}"
        with self._lock:
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass
        try:
            if self._sink:
                self._sink(line + "\n")
        except Exception:
            pass

    def info(self, msg: str): self._write("INFO", msg)
    def warn(self, msg: str): self._write("WARN", msg)
    def error(self, msg: str): self._write("ERROR", msg)

log = Logger()


# ============================================================
# Locale / i18n
# ============================================================

def _system_lang_guess() -> str:
    # Windows UI language (preferred)
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        primary = lang_id & 0x3FF
        mapping_primary = {
            0x19: "ru",  # Russian
            0x09: "en",  # English
        }
        v = mapping_primary.get(primary)
        if v:
            return v
    except Exception:
        pass

    try:
        loc = pylocale.getdefaultlocale()[0] or ""
        loc = loc.split("_")[0].lower()
        if loc in ("ru", "en"):
            return loc
    except Exception:
        pass
    return "en"

class I18N:
    SUPPORTED = ["en", "ru"]

    EN = {
        "app_title": "Saonix",
        "nav_record": "● Record",
        "nav_library": "📚 Library",
        "nav_settings": "⚙ Settings",
        "status_ready": "Ready",
        "status_recording": "● Recording…",
        "status_playing": "▶ Playing…",
        "style": "Style",
        "theme": "Theme",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "glow": "Glow",
        "language": "Language",
        "support": "Support",
        "support_text": "Questions / issues / suggestions:\nDiscord: Relberof",

        "page_record": "Record",
        "page_library": "Library",
        "page_settings": "Settings",

        "rec_controls": "Controls",
        "rec_start": "● Start recording",
        "rec_stop": "■ Stop recording",
        "rec_play_loaded": "▶ Play loaded",
        "rec_stop_play": "⏹ Stop",
        "rec_save_label": "Save to library:",
        "rec_save_btn": "💾 Save",
        "rec_clear_log": "Clear log (window)",
        "rec_tips": "Tips",

        "lib_title": "Library",
        "search_ph": "Search…",
        "btn_load": "Load",
        "btn_delete": "Delete",
        "btn_rename": "Rename",
        "btn_clone": "Clone",
        "btn_export": "Export JSON",
        "btn_import": "Import JSON",
        "bind": "Bind:",
        "bind_ph": "F6 or Ctrl+Alt+F6",
        "bind_set": "Set",
        "bind_remove": "Remove",
        "play_selected": "▶ Play selected",

        "settings_playback": "Playback",
        "repeat": "Repeat (times)",
        "loop": "Loop (sec, 0=off)",
        "speed": "Speed",
        "delay": "Start delay (sec)",
        "apply": "Apply",
        "reset": "Reset",
        "base_hotkeys": "Base hotkeys",
        "hk_rec": "Start record",
        "hk_stoprec": "Stop record",
        "hk_play": "Play loaded",
        "hk_stop": "Stop playing",
        "hk_apply": "Apply hotkeys",

        "save_name_warn": "Enter macro name.",
        "no_events_warn": "No events. Record a macro first.",
        "overwrite_q": "Macro exists. Overwrite?",
        "select_macro_warn": "Select a macro.",
        "delete_q": "Delete macro?",
        "invalid_hotkey": "Invalid hotkey. Example: F6 or Ctrl+Alt+F6",

        "empty": "(empty)",
        "binds_none": "(no binds)",
        "saved": "Saved",
        "loaded": "Loaded",
        "deleted": "Deleted",
        "renamed": "Renamed",
        "cloned": "Cloned",
        "imported": "Imported",
        "exported": "Exported",
    }

    RU = {
        "app_title": "Saonix",
        "nav_record": "● Запись",
        "nav_library": "📚 Библиотека",
        "nav_settings": "⚙ Настройки",
        "status_ready": "Готово",
        "status_recording": "● Запись…",
        "status_playing": "▶ Воспроизведение…",
        "style": "Стиль",
        "theme": "Тема",
        "theme_dark": "Тёмная",
        "theme_light": "Светлая",
        "glow": "Glow",
        "language": "Язык",
        "support": "Поддержка",
        "support_text": "Вопросы / проблемы / предложения:\nDiscord: Relberof",

        "page_record": "Запись",
        "page_library": "Библиотека",
        "page_settings": "Настройки",

        "rec_controls": "Управление",
        "rec_start": "● Начать запись",
        "rec_stop": "■ Остановить запись",
        "rec_play_loaded": "▶ Запустить (загруженный)",
        "rec_stop_play": "⏹ Остановить",
        "rec_save_label": "Сохранить в библиотеку:",
        "rec_save_btn": "💾 Сохранить",
        "rec_clear_log": "Очистить лог (в окне)",
        "rec_tips": "Подсказки",

        "lib_title": "Библиотека",
        "search_ph": "Поиск…",
        "btn_load": "Загрузить",
        "btn_delete": "Удалить",
        "btn_rename": "Переименовать",
        "btn_clone": "Клонировать",
        "btn_export": "Экспорт JSON",
        "btn_import": "Импорт JSON",
        "bind": "Бинд:",
        "bind_ph": "F6 или Ctrl+Alt+F6",
        "bind_set": "Назначить",
        "bind_remove": "Снять",
        "play_selected": "▶ Запустить выбранный",

        "settings_playback": "Воспроизведение",
        "repeat": "Повтор (раз)",
        "loop": "Цикл (сек, 0=выкл)",
        "speed": "Скорость",
        "delay": "Задержка старта (сек)",
        "apply": "Применить",
        "reset": "Сброс",
        "base_hotkeys": "Базовые хоткеи",
        "hk_rec": "Старт записи",
        "hk_stoprec": "Стоп записи",
        "hk_play": "Пуск загруженного",
        "hk_stop": "Стоп воспроизведения",
        "hk_apply": "Применить хоткеи",

        "save_name_warn": "Введи имя макроса.",
        "no_events_warn": "Нет событий. Сначала запиши макрос.",
        "overwrite_q": "Макрос уже существует. Перезаписать?",
        "select_macro_warn": "Выбери макрос.",
        "delete_q": "Удалить макрос?",
        "invalid_hotkey": "Неверный формат. Пример: F6 или Ctrl+Alt+F6",

        "empty": "(пусто)",
        "binds_none": "(биндов нет)",
        "saved": "Сохранено",
        "loaded": "Загружено",
        "deleted": "Удалено",
        "renamed": "Переименовано",
        "cloned": "Клонировано",
        "imported": "Импортировано",
        "exported": "Экспортировано",
    }

    def __init__(self, lang: str):
        self.lang = "en"
        self.dict: Dict[str, str] = dict(self.EN)
        self.load(lang)

    def load(self, lang: str):
        lang = (lang or "auto").strip().lower()
        if lang == "auto":
            lang = _system_lang_guess()
        if lang not in self.SUPPORTED:
            lang = "en"
        base = dict(self.EN)
        if lang == "ru":
            base.update(self.RU)

        # optional external override file locales/<lang>.json
        ext_path = os.path.join(DIR_LOCALES, f"{lang}.json")
        if os.path.exists(ext_path):
            try:
                j = _read_json(ext_path, {})
                if isinstance(j, dict):
                    base.update({str(k): str(v) for k, v in j.items()})
            except Exception:
                pass

        self.lang = lang
        self.dict = base

    def t(self, key: str) -> str:
        return self.dict.get(key, key)


# ============================================================
# Styles / themes / glow
# ============================================================

class StylePack:
    def __init__(self, name: str, dark: Dict[str, str], light: Dict[str, str]):
        self.name = name
        self.dark = dark
        self.light = light

def style_get(pack: StylePack) -> Dict[str, str]:
    return pack.dark if ctk.get_appearance_mode() == "Dark" else pack.light

STYLES: Dict[str, StylePack] = {
    "Calm": StylePack(
        "Calm",
        dark=dict(bg="#0d1118", panel="#121826", card="#141d2e",
                  text="#e9eef7", muted="#a7b4cc",
                  accent="#5aa7ff", accent2="#7c66ff",
                  danger="#ff4a4a", border="#23314a"),
        light=dict(bg="#f3f5f9", panel="#ffffff", card="#f7f9fc",
                   text="#101828", muted="#475467",
                   accent="#2563eb", accent2="#7c3aed",
                   danger="#dc2626", border="#d0d5dd")
    ),
    "Aurora": StylePack(
        "Aurora",
        dark=dict(bg="#071216", panel="#0b1a20", card="#0d222a",
                  text="#e9fffb", muted="#a3d6ce",
                  accent="#49f1b8", accent2="#56a8ff",
                  danger="#ff4a4a", border="#14343a"),
        light=dict(bg="#f1fbfa", panel="#ffffff", card="#f6fffe",
                   text="#06201e", muted="#1f6f67",
                   accent="#0ea5e9", accent2="#22c55e",
                   danger="#dc2626", border="#cde8e4")
    ),
    "Forest": StylePack(
        "Forest",
        dark=dict(bg="#0b120e", panel="#101a14", card="#132017",
                  text="#eaf6ee", muted="#a7c2b1",
                  accent="#34d399", accent2="#60a5fa",
                  danger="#ff4a4a", border="#1f3327"),
        light=dict(bg="#f3faf6", panel="#ffffff", card="#f7fff9",
                   text="#0b1a12", muted="#335b45",
                   accent="#059669", accent2="#2563eb",
                   danger="#dc2626", border="#cfe7da")
    ),
    "Cherry": StylePack(
        "Cherry",
        dark=dict(bg="#130b10", panel="#1b1017", card="#23131d",
                  text="#f7eaf1", muted="#d1b3c3",
                  accent="#fb7185", accent2="#a78bfa",
                  danger="#ff4a4a", border="#3a2230"),
        light=dict(bg="#fff5f8", panel="#ffffff", card="#fff7fb",
                   text="#241018", muted="#7c2d45",
                   accent="#e11d48", accent2="#7c3aed",
                   danger="#dc2626", border="#f3c6d6")
    ),
}


# ============================================================
# DB
# ============================================================

class MacroDB:
    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 1, "macros": {}, "binds": {}, "settings": {}}
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        d = _read_json(self.path, None)
        if isinstance(d, dict):
            self.data.update(d)
            self.data.setdefault("macros", {})
            self.data.setdefault("binds", {})
            self.data.setdefault("settings", {})

    def save(self):
        _atomic_write_json(self.path, self.data)

    def names(self) -> List[str]:
        return sorted(self.data["macros"].keys(), key=lambda x: x.lower())

    def exists(self, name: str) -> bool:
        return name in self.data["macros"]

    def get(self, name: str):
        return self.data["macros"].get(name)

    def put(self, name: str, events: List[dict], settings: Dict[str, Any]):
        self.data["macros"][name] = {
            "created": int(time.time()),
            "events": events,
            "settings": settings
        }
        self.save()

    def delete(self, name: str):
        if name in self.data["macros"]:
            del self.data["macros"][name]
        dead = [hk for hk, mn in self.data["binds"].items() if mn == name]
        for hk in dead:
            del self.data["binds"][hk]
        self.save()

    def rename(self, old: str, new: str) -> bool:
        if old not in self.data["macros"]:
            return False
        if new in self.data["macros"]:
            return False
        self.data["macros"][new] = self.data["macros"].pop(old)
        for hk, mn in list(self.data["binds"].items()):
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

    def binds(self) -> Dict[str, str]:
        return dict(self.data.get("binds", {}))

    def set_bind(self, hk: str, macro: str):
        self.data.setdefault("binds", {})
        self.data["binds"][hk] = macro
        self.save()

    def remove_bind(self, hk: str):
        if hk in self.data.get("binds", {}):
            del self.data["binds"][hk]
            self.save()

    def get_settings(self) -> Dict[str, Any]:
        return dict(self.data.get("settings", {}))

    def set_settings(self, s: Dict[str, Any]):
        self.data["settings"] = dict(s)
        self.save()


# ============================================================
# Hotkey parsing
# ============================================================

def normalize_hotkey(text: str) -> Optional[str]:
    if not text:
        return None
    t = str(text).strip().lower().replace(" ", "")
    if not t:
        return None
    t = t.replace("<", "").replace(">", "")

    if t.startswith("f") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 24:
            return f"<f{n}>"

    parts = t.split("+")
    mods: List[str] = []
    key = None
    for p in parts:
        if p in ("ctrl", "control"):
            mods.append("<ctrl>")
        elif p == "alt":
            mods.append("<alt>")
        elif p == "shift":
            mods.append("<shift>")
        elif p in ("win", "windows", "cmd", "meta"):
            mods.append("<cmd>")
        else:
            key = p

    if key is None:
        return None

    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            key_fmt = f"<f{n}>"
        else:
            return None
    elif len(key) == 1 and key.isdigit():
        key_fmt = key
    elif len(key) == 1 and ("a" <= key <= "z"):
        key_fmt = key
    elif key in ("space", "spc"):
        key_fmt = "<space>"
    elif key == "tab":
        key_fmt = "<tab>"
    elif key in ("esc", "escape"):
        key_fmt = "<esc>"
    else:
        return None

    return "+".join(mods + [key_fmt])


# ============================================================
# Macro engine (no key suppression)
# ============================================================

@dataclass
class Event:
    t: float
    device: str
    type: str
    data: Dict[str, Any]

class MacroEngine:
    def __init__(self, logger: Logger):
        self.log = logger
        self.events: List[Event] = []
        self.recording = False
        self.playing = False

        self._t0: Optional[float] = None
        self._stop_play = threading.Event()
        self._play_lock = threading.Lock()

        self.mouse_ctl = MouseController()
        self.kb_ctl = KeyboardController()

        self._last_move = None
        self._last_move_time = 0.0
        self._min_move_interval = 0.01

        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll
        )
        self._kb_listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False
        )

        self._mouse_listener.start()
        self._kb_listener.start()
        self.log.info("Engine ready.")

    def shutdown(self):
        try: self._mouse_listener.stop()
        except Exception: pass
        try: self._kb_listener.stop()
        except Exception: pass

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
                self.log.warn("Cannot record while playing.")
                return
            if self.recording:
                return
            self.events = []
            self._t0 = self.now()
            self.recording = True
            self.log.info("=== Recording started ===")

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.log.info(f"=== Recording stopped. Events: {len(self.events)} ===")

    def stop_playing(self):
        with self._play_lock:
            if not self.playing:
                return
            self._stop_play.set()
            self.playing = False
            self.log.info("=== Stopped ===")

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
            "pressed": bool(pressed)
        })

    def _on_scroll(self, x, y, dx, dy):
        if self.playing:
            return
        self._add("mouse", "scroll", {"x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)})

    def _on_press(self, key):
        if self.playing:
            return
        rep = self._key_to_repr(key)
        if rep:
            self._add("keyboard", "press", {"key": rep})

    def _on_release(self, key):
        if self.playing:
            return
        rep = self._key_to_repr(key)
        if rep:
            self._add("keyboard", "release", {"key": rep})

    def _apply_event(self, e: Event):
        if e.device == "mouse":
            if e.type == "move":
                self.mouse_ctl.position = (e.data["x"], e.data["y"])
            elif e.type == "click":
                self.mouse_ctl.position = (e.data["x"], e.data["y"])
                btn = getattr(Button, e.data.get("button", "left"), Button.left)
                if e.data.get("pressed"):
                    self.mouse_ctl.press(btn)
                else:
                    self.mouse_ctl.release(btn)
            elif e.type == "scroll":
                self.mouse_ctl.position = (e.data["x"], e.data["y"])
                self.mouse_ctl.scroll(e.data["dx"], e.data["dy"])
            return

        if e.device == "keyboard":
            key_obj = self._repr_to_key(e.data.get("key", {}))
            if key_obj is None:
                return
            if e.type == "press":
                self.kb_ctl.press(key_obj)
            elif e.type == "release":
                self.kb_ctl.release(key_obj)

    def play(self, repeat: int, loop_seconds: int, speed: float, start_delay: float):
        with self._play_lock:
            if self.recording:
                self.log.warn("Stop recording first.")
                return
            if self.playing:
                return
            if not self.events:
                self.log.warn("No events.")
                return

            self.playing = True
            self._stop_play.clear()

            def play_once():
                base = self.now()
                sp = max(speed, 0.05)
                for ev in self.events:
                    if self._stop_play.is_set():
                        return
                    target = base + (ev.t / sp)
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
                        while not self._stop_play.is_set() and (time.time() - started) < loop_seconds:
                            play_once()
                    else:
                        for _ in range(max(1, repeat)):
                            if self._stop_play.is_set():
                                break
                            play_once()
                except Exception as e:
                    self.log.error(f"Playback error: {e}")
                    self.log.error(traceback.format_exc())
                finally:
                    with self._play_lock:
                        self.playing = False
                        self._stop_play.set()

            threading.Thread(target=run, daemon=True).start()


# ============================================================
# Hotkey manager
# ============================================================

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


# ============================================================
# GitHub updater (manifest + bundle) with caching (ETag/Last-Modified)
# ============================================================

def _http_get(url: str, headers: Dict[str, str], timeout: int = 15):
    req = urllib.request.Request(url, headers=headers, method="GET")
    return urllib.request.urlopen(req, timeout=timeout)

def _http_read_json(url: str, cache_body_path: str, cache_meta_path: str) -> Dict[str, Any]:
    meta = _read_json(cache_meta_path, {})
    headers = {"User-Agent": f"{APP_NAME}/1.0"}
    etag = meta.get("etag")
    last = meta.get("last_modified")
    if etag:
        headers["If-None-Match"] = etag
    if last:
        headers["If-Modified-Since"] = last

    try:
        with _http_get(url, headers=headers, timeout=15) as resp:
            code = getattr(resp, "status", 200)
            if code == 304:
                cached = _read_json(cache_body_path, {})
                return cached if isinstance(cached, dict) else {}
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body else {}
            if isinstance(data, dict):
                _atomic_write_json(cache_body_path, data)
            new_meta = {
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "fetched_at": int(time.time())
            }
            _atomic_write_json(cache_meta_path, new_meta)
            return data if isinstance(data, dict) else {}
    except urllib.error.HTTPError as e:
        if e.code == 304:
            cached = _read_json(cache_body_path, {})
            return cached if isinstance(cached, dict) else {}
        cached = _read_json(cache_body_path, {})
        return cached if isinstance(cached, dict) else {}
    except Exception:
        cached = _read_json(cache_body_path, {})
        return cached if isinstance(cached, dict) else {}

def _http_download(url: str, dst: str, headers: Dict[str, str],
                   on_progress: Optional[Callable[[int, int], None]] = None,
                   timeout: int = 30) -> bool:
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = resp.headers.get("Content-Length")
            total_i = int(total) if total and total.isdigit() else -1
            _ensure_dir(os.path.dirname(dst))
            tmp = dst + ".tmp"
            got = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if on_progress:
                        on_progress(got, total_i)
            os.replace(tmp, dst)
        return True
    except Exception:
        try:
            if os.path.exists(dst + ".tmp"):
                os.remove(dst + ".tmp")
        except Exception:
            pass
        return False

def _cached_download_with_meta(url: str, dst: str, meta_path: str,
                               on_progress: Optional[Callable[[int, int], None]] = None) -> bool:
    meta = _read_json(meta_path, {})
    headers = {"User-Agent": f"{APP_NAME}/1.0"}
    if meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]

    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = getattr(resp, "status", 200)
            if code == 304 and os.path.exists(dst):
                return True

            total = resp.headers.get("Content-Length")
            total_i = int(total) if total and total.isdigit() else -1
            _ensure_dir(os.path.dirname(dst))
            tmp = dst + ".tmp"
            got = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if on_progress:
                        on_progress(got, total_i)
            os.replace(tmp, dst)

            new_meta = {
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "fetched_at": int(time.time())
            }
            _atomic_write_json(meta_path, new_meta)
            return True

    except urllib.error.HTTPError as e:
        if e.code == 304 and os.path.exists(dst):
            return True
        return os.path.exists(dst)
    except Exception:
        return os.path.exists(dst)

def _load_local_version() -> str:
    d = _read_json(LOCAL_VERSION_FILE, {})
    v = d.get("version")
    return str(v) if v else ""

def _save_local_version(v: str):
    _atomic_write_json(LOCAL_VERSION_FILE, {"version": str(v), "updated_at": int(time.time())})

def _extract_zip(zip_path: str, dst_dir: str):
    tmp_dir = dst_dir + ".__new__"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    _ensure_dir(tmp_dir)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(tmp_dir)

    # swap
    backup = dst_dir + ".__old__"
    if os.path.exists(backup):
        shutil.rmtree(backup, ignore_errors=True)
    if os.path.exists(dst_dir):
        os.replace(dst_dir, backup)
    os.replace(tmp_dir, dst_dir)
    if os.path.exists(backup):
        shutil.rmtree(backup, ignore_errors=True)

def check_and_update(progress_cb: Callable[[float, str], None]) -> str:
    """
    Returns status string: "ok" / "offline" / "updated"
    """
    progress_cb(0.05, "Checking updates…")
    manifest = _http_read_json(UPDATE_MANIFEST_URL, CACHED_MANIFEST_FILE, CACHED_MANIFEST_META)
    if not manifest or not isinstance(manifest, dict):
        progress_cb(0.25, "Offline mode (no manifest).")
        return "offline"

    remote_ver = str(manifest.get("version", "")).strip()
    bundle_url = str(manifest.get("bundle_url", "")).strip()
    bundle_sha = str(manifest.get("bundle_sha256", "")).strip().lower()

    if not remote_ver or not bundle_url:
        progress_cb(0.25, "Manifest invalid. Starting…")
        return "offline"

    local_ver = _load_local_version()
    if local_ver == remote_ver and os.path.exists(DIR_APP):
        progress_cb(0.35, f"No updates (v{remote_ver}).")
        return "ok"

    progress_cb(0.35, f"Downloading update (v{remote_ver})…")
    zip_path = os.path.join(DIR_CACHE, f"bundle_{remote_ver}.zip")

    def on_dl(got: int, total: int):
        if total > 0:
            p = 0.35 + 0.45 * (got / total)
            progress_cb(p, f"Downloading… {int(100 * got / total)}%")
        else:
            progress_cb(0.55, "Downloading…")

    ok = _http_download(bundle_url, zip_path, headers={"User-Agent": f"{APP_NAME}/1.0"}, on_progress=on_dl, timeout=60)
    if not ok:
        progress_cb(0.70, "Download failed. Starting…")
        return "offline"

    if bundle_sha and len(bundle_sha) >= 16:
        progress_cb(0.82, "Verifying package…")
        try:
            got = _sha256_file(zip_path).lower()
            if got != bundle_sha:
                progress_cb(0.86, "Verification failed. Starting…")
                return "offline"
        except Exception:
            progress_cb(0.86, "Verification failed. Starting…")
            return "offline"

    progress_cb(0.88, "Installing…")
    try:
        _extract_zip(zip_path, DIR_APP)
    except Exception:
        progress_cb(0.92, "Install failed. Starting…")
        return "offline"

    _save_local_version(remote_ver)
    progress_cb(0.98, "Update installed. Starting…")
    return "updated"


# ============================================================
# Icon handling (cached download + local load)
# ============================================================

def load_app_icon_photo(master: ctk.CTk) -> Optional[ctk.CTkImage]:
    try:
        # cache online icon once (ETag/Last-Modified)
        def _p(_got, _total): pass
        _cached_download_with_meta(ICON_PNG_URL, CACHED_ICON_FILE, CACHED_ICON_META, on_progress=_p)
    except Exception:
        pass

    try:
        if os.path.exists(CACHED_ICON_FILE):
            img = ctk.CTkImage(light_image=None, dark_image=None, size=(64, 64))
            # CTkImage wants PIL images normally; use Tk PhotoImage instead for iconphoto
            return None
    except Exception:
        pass
    return None

def apply_window_icon(root: ctk.CTk):
    # Tk iconphoto supports PNG via PhotoImage
    try:
        import tkinter as tk
        path = CACHED_ICON_FILE if os.path.exists(CACHED_ICON_FILE) else None
        if path:
            photo = tk.PhotoImage(file=path)
            root.iconphoto(True, photo)
            root._saonix_icon_ref = photo  # keep ref
    except Exception:
        pass


# ============================================================
# Loader (splash)
# ============================================================

class Loader(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("Dark")
        self.title(APP_NAME)
        self.geometry("520x260")
        self.resizable(False, False)

        apply_window_icon(self)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.wrap = ctk.CTkFrame(self, corner_radius=18)
        self.wrap.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.wrap.grid_columnconfigure(0, weight=1)

        self.lbl_title = ctk.CTkLabel(self.wrap, text=APP_NAME, font=ctk.CTkFont(size=28, weight="bold"))
        self.lbl_title.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 4))

        self.lbl_sub = ctk.CTkLabel(self.wrap, text="Loading…", font=ctk.CTkFont(size=13))
        self.lbl_sub.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))

        self.bar = ctk.CTkProgressBar(self.wrap)
        self.bar.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 8))
        self.bar.set(0.0)

        self.lbl_status = ctk.CTkLabel(self.wrap, text="Starting…", justify="left")
        self.lbl_status.grid(row=3, column=0, sticky="w", padx=18, pady=(6, 0))

        self.lbl_support = ctk.CTkLabel(self.wrap, text=f"Support: Discord {SUPPORT_DISCORD}", font=ctk.CTkFont(size=12))
        self.lbl_support.grid(row=4, column=0, sticky="w", padx=18, pady=(10, 18))

        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._done = False
        self._update_status = "ok"

        threading.Thread(target=self._worker, daemon=True).start()
        self.after(50, self._pump)

    def _set_ui(self, p: float, status: str):
        self.bar.set(_clamp(p, 0.0, 1.0))
        self.lbl_status.configure(text=status)

    def _worker(self):
        try:
            def progress_cb(p: float, msg: str):
                self._q.put(("p", p, msg))
            # cache icon once (no re-download if not changed)
            self._q.put(("p", 0.02, "Preparing…"))
            try:
                _cached_download_with_meta(ICON_PNG_URL, CACHED_ICON_FILE, CACHED_ICON_META)
            except Exception:
                pass
            self._update_status = check_and_update(progress_cb)
            self._q.put(("done",))
        except Exception:
            self._q.put(("p", 0.30, "Starting…"))
            self._q.put(("done",))

    def _pump(self):
        try:
            while True:
                item = self._q.get_nowait()
                if not item:
                    break
                if item[0] == "p":
                    _, p, msg = item
                    self._set_ui(float(p), str(msg))
                elif item[0] == "done":
                    self._done = True
        except queue.Empty:
            pass

        if self._done:
            self.after(200, self._start_app)
            return

        self.after(50, self._pump)

    def _start_app(self):
        try:
            self.destroy()
        except Exception:
            pass
        run_app()


# ============================================================
# Main app
# ============================================================

class SaonixApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.db = MacroDB(DB_FILE)
        saved = self.db.get_settings()

        # i18n
        lang = str(saved.get("lang", "auto"))
        self.i18n = I18N(lang)

        # appearance
        appearance = saved.get("appearance", "Dark")
        if appearance not in ("Dark", "Light"):
            appearance = "Dark"
        ctk.set_appearance_mode(appearance)

        # style + glow
        style_name = str(saved.get("style", "Calm"))
        self.current_style = STYLES.get(style_name, STYLES["Calm"])
        self.glow_var = ctk.IntVar(value=int(saved.get("glow", 2)))

        # playback
        self.repeat_var = ctk.StringVar(value=str(saved.get("repeat", 1)))
        self.loop_var = ctk.StringVar(value=str(saved.get("loop_seconds", 0)))
        self.speed_var = ctk.StringVar(value=str(saved.get("speed", 1.0)))
        self.delay_var = ctk.StringVar(value=str(saved.get("start_delay", 0.0)))

        # base hotkeys
        self.hk_rec_var = ctk.StringVar(value=str(saved.get("hk_rec", "Ctrl+Alt+1")))
        self.hk_stoprec_var = ctk.StringVar(value=str(saved.get("hk_stoprec", "Ctrl+Alt+2")))
        self.hk_play_var = ctk.StringVar(value=str(saved.get("hk_play", "Ctrl+Alt+3")))
        self.hk_stop_var = ctk.StringVar(value=str(saved.get("hk_stop", "Ctrl+Alt+4")))

        self._active_page = "record"
        self.selected_macro: Optional[str] = None
        self.macro_buttons: Dict[str, ctk.CTkButton] = {}

        self.title(self.i18n.t("app_title"))
        self.geometry("1180x720")
        self.minsize(1080, 680)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        apply_window_icon(self)

        # logger -> UI
        self.log_box: Optional[ctk.CTkTextbox] = None
        log.set_sink(self._append_log_ui)

        self.engine = MacroEngine(log)
        self.hk = HotkeyManager(log)

        # layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=18)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=14, pady=14)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(99, weight=1)

        self.lbl_brand = ctk.CTkLabel(self.sidebar, text=self.i18n.t("app_title"),
                                      font=ctk.CTkFont(family="Times New Roman", size=26, weight="bold"))
        self.lbl_brand.grid(row=0, column=0, padx=16, pady=(16, 2), sticky="w")

        self.lbl_tag = ctk.CTkLabel(self.sidebar, text="Macro Recorder", font=ctk.CTkFont(size=14))
        self.lbl_tag.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")

        self.btn_record = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_record"),
                                        command=lambda: self.show_page("record"))
        self.btn_library = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_library"),
                                         command=lambda: self.show_page("library"))
        self.btn_settings = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_settings"),
                                          command=lambda: self.show_page("settings"))
        self.btn_record.grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        self.btn_library.grid(row=3, column=0, padx=16, pady=8, sticky="ew")
        self.btn_settings.grid(row=4, column=0, padx=16, pady=8, sticky="ew")

        self.lbl_style = ctk.CTkLabel(self.sidebar, text=self.i18n.t("style"), font=ctk.CTkFont(weight="bold"))
        self.lbl_style.grid(row=6, column=0, padx=16, pady=(18, 4), sticky="w")
        self.style_menu = ctk.CTkOptionMenu(self.sidebar, values=list(STYLES.keys()), command=self.set_style)
        self.style_menu.set(style_name if style_name in STYLES else "Calm")
        self.style_menu.grid(row=7, column=0, padx=16, pady=6, sticky="ew")

        self.lbl_mode = ctk.CTkLabel(self.sidebar, text=self.i18n.t("theme"), font=ctk.CTkFont(weight="bold"))
        self.lbl_mode.grid(row=8, column=0, padx=16, pady=(10, 4), sticky="w")
        self.mode_menu = ctk.CTkOptionMenu(self.sidebar,
                                           values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")],
                                           command=self.set_mode)
        self.mode_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))
        self.mode_menu.grid(row=9, column=0, padx=16, pady=6, sticky="ew")

        self.lbl_lang = ctk.CTkLabel(self.sidebar, text=self.i18n.t("language"), font=ctk.CTkFont(weight="bold"))
        self.lbl_lang.grid(row=10, column=0, padx=16, pady=(10, 4), sticky="w")
        self.lang_menu = ctk.CTkOptionMenu(self.sidebar, values=["auto"] + I18N.SUPPORTED, command=self.set_lang)
        self.lang_menu.set(lang if lang in (["auto"] + I18N.SUPPORTED) else "auto")
        self.lang_menu.grid(row=11, column=0, padx=16, pady=6, sticky="ew")

        self.lbl_glow = ctk.CTkLabel(self.sidebar, text=self.i18n.t("glow"), font=ctk.CTkFont(weight="bold"))
        self.lbl_glow.grid(row=12, column=0, padx=16, pady=(14, 4), sticky="w")
        self.glow_slider = ctk.CTkSlider(self.sidebar, from_=0, to=3, number_of_steps=3, command=self._on_glow)
        self.glow_slider.set(int(self.glow_var.get()))
        self.glow_slider.grid(row=13, column=0, padx=16, pady=(0, 10), sticky="ew")

        # support info (one time, bottom-left)
        self.support_title = ctk.CTkLabel(self.sidebar, text=self.i18n.t("support"), font=ctk.CTkFont(weight="bold"))
        self.support_title.grid(row=98, column=0, padx=16, pady=(0, 4), sticky="w")
        self.support_text = ctk.CTkLabel(self.sidebar, text=self.i18n.t("support_text"), justify="left")
        self.support_text.grid(row=99, column=0, padx=16, pady=(0, 14), sticky="sw")

        # main
        self.main = ctk.CTkFrame(self, corner_radius=18)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkFrame(self.main, corner_radius=18, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        self.header.grid_columnconfigure(0, weight=1)

        self.h_title = ctk.CTkLabel(self.header, text=self.i18n.t("page_record"), font=ctk.CTkFont(size=18, weight="bold"))
        self.h_title.grid(row=0, column=0, padx=14, pady=12, sticky="w")

        self.status_var = ctk.StringVar(value=self.i18n.t("status_ready"))
        self.h_status = ctk.CTkLabel(self.header, textvariable=self.status_var)
        self.h_status.grid(row=0, column=1, padx=14, pady=12, sticky="e")

        self.content = ctk.CTkFrame(self.main, corner_radius=18, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=14, pady=(8, 14))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.page_record = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        self.page_library = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        self.page_settings = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid(row=0, column=0, sticky="nsew")
            p.grid_remove()

        # build
        self.build_record_page()
        self.build_library_page()
        self.build_settings_page()

        self.apply_texts()
        self.apply_style()

        self.show_page("record")
        self.rebuild_hotkeys()

        self.after(200, self.tick)

        log.info("Started.")

    # ---------------------------
    # Close
    # ---------------------------
    def on_close(self):
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
        self.destroy()

    # ---------------------------
    # Log sink
    # ---------------------------
    def _append_log_ui(self, text: str):
        try:
            if self.log_box is None:
                return
            self.log_box.insert("end", text)
            self.log_box.see("end")
        except Exception:
            pass

    # ---------------------------
    # Tick / status
    # ---------------------------
    def tick(self):
        if self.engine.recording:
            self.status_var.set(self.i18n.t("status_recording"))
        elif self.engine.playing:
            self.status_var.set(self.i18n.t("status_playing"))
        else:
            self.status_var.set(self.i18n.t("status_ready"))
        self.after(200, self.tick)

    # ---------------------------
    # Persist settings
    # ---------------------------
    def current_play_settings(self) -> Dict[str, Any]:
        repeat = _clamp(_safe_int(self.repeat_var.get(), 1), 1, 9999)
        loop_seconds = _clamp(_safe_int(self.loop_var.get(), 0), 0, 24 * 3600)
        speed = _clamp(_safe_float(self.speed_var.get(), 1.0), 0.05, 5.0)
        delay = _clamp(_safe_float(self.delay_var.get(), 0.0), 0.0, 60.0)
        return {"repeat": repeat, "loop_seconds": loop_seconds, "speed": speed, "start_delay": delay}

    def apply_play_settings_to_ui(self, s: Dict[str, Any]):
        self.repeat_var.set(str(s.get("repeat", 1)))
        self.loop_var.set(str(s.get("loop_seconds", 0)))
        self.speed_var.set(str(s.get("speed", 1.0)))
        self.delay_var.set(str(s.get("start_delay", 0.0)))

    def persist_settings(self):
        s = self.db.get_settings()
        s.update({
            "appearance": ctk.get_appearance_mode(),
            "style": self.style_menu.get(),
            "lang": self.lang_menu.get(),
            "glow": int(self.glow_var.get()),
            "hk_rec": self.hk_rec_var.get(),
            "hk_stoprec": self.hk_stoprec_var.get(),
            "hk_play": self.hk_play_var.get(),
            "hk_stop": self.hk_stop_var.get(),
        })
        s.update(self.current_play_settings())
        self.db.set_settings(s)

    # ---------------------------
    # Theme/style/lang/glow
    # ---------------------------
    def set_style(self, name: str):
        self.current_style = STYLES.get(name, STYLES["Calm"])
        self.persist_settings()
        self.apply_style()

    def set_mode(self, mode_text: str):
        if mode_text == self.i18n.t("theme_light"):
            ctk.set_appearance_mode("Light")
        else:
            ctk.set_appearance_mode("Dark")
        self.persist_settings()
        self.apply_style()

    def set_lang(self, lang: str):
        self.i18n.load(lang)
        self.title(self.i18n.t("app_title"))
        # refresh option labels for theme menu
        self.mode_menu.configure(values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")])
        self.mode_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))
        self.persist_settings()
        self.apply_texts()

    def _on_glow(self, _=None):
        self.glow_var.set(int(round(self.glow_slider.get())))
        self.persist_settings()
        self.apply_style()

    def apply_glow(self, frame: ctk.CTkFrame, active: bool = True):
        lvl = int(self.glow_var.get())
        col = style_get(self.current_style)["accent"]
        if (not active) or lvl <= 0:
            frame.configure(border_width=0)
            return
        frame.configure(border_width={1: 1, 2: 2, 3: 3}.get(lvl, 2), border_color=col)

    def _style_nav_button(self, btn: ctk.CTkButton, active: bool):
        s = style_get(self.current_style)
        if active:
            btn.configure(
                fg_color=s["card"], hover_color=s["border"], text_color=s["text"],
                border_width=2, border_color=s["accent"], corner_radius=14
            )
        else:
            btn.configure(
                fg_color=s["card"], hover_color=s["border"], text_color=s["text"],
                border_width=0, corner_radius=14
            )

    def apply_style(self):
        s = style_get(self.current_style)
        self.configure(fg_color=s["bg"])
        self.sidebar.configure(fg_color=s["panel"])
        self.main.configure(fg_color=s["bg"])

        self.lbl_brand.configure(text_color=s["text"])
        self.lbl_tag.configure(text_color=s["muted"])

        self.lbl_style.configure(text_color=s["text"])
        self.lbl_mode.configure(text_color=s["text"])
        self.lbl_lang.configure(text_color=s["text"])
        self.lbl_glow.configure(text_color=s["text"])
        self.support_title.configure(text_color=s["text"])
        self.support_text.configure(text_color=s["muted"])

        self.style_menu.configure(fg_color=s["card"], button_color=s["border"], button_hover_color=s["accent2"], text_color=s["text"])
        self.mode_menu.configure(fg_color=s["card"], button_color=s["border"], button_hover_color=s["accent2"], text_color=s["text"])
        self.lang_menu.configure(fg_color=s["card"], button_color=s["border"], button_hover_color=s["accent2"], text_color=s["text"])
        self.glow_slider.configure(progress_color=s["accent"])

        self._style_nav_button(self.btn_record, self._active_page == "record")
        self._style_nav_button(self.btn_library, self._active_page == "library")
        self._style_nav_button(self.btn_settings, self._active_page == "settings")

        self.h_title.configure(text_color=s["text"])
        self.h_status.configure(text_color=s["muted"])

        # record
        self.card_ctrl.configure(fg_color=s["card"])
        self.card_tips.configure(fg_color=s["card"])
        self.apply_glow(self.card_ctrl, True)
        self.apply_glow(self.card_tips, True)

        self.rec_title.configure(text_color=s["text"])
        self.tips_title.configure(text_color=s["text"])
        self.tips_text.configure(text_color=s["muted"])

        self.btn_start.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent"])
        self.btn_stop.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"])
        self.btn_play.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent2"])
        self.btn_stopplay.configure(fg_color=s["danger"], hover_color=s["danger"], text_color="#ffffff")
        self.btn_save.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent2"])

        self.save_label.configure(text_color=s["muted"])
        self.save_entry.configure(fg_color=s["panel"], text_color=s["text"], border_color=s["border"])

        self.log_title.configure(text_color=s["text"])
        self.log_box.configure(fg_color=s["panel"], text_color=s["text"])
        self.btn_clear_log.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent2"])

        # library
        self.lib_left.configure(fg_color=s["card"])
        self.lib_right.configure(fg_color=s["card"])
        self.apply_glow(self.lib_left, True)
        self.apply_glow(self.lib_right, True)

        self.lib_title.configure(text_color=s["text"])
        self.search_entry.configure(fg_color=s["panel"], text_color=s["text"], border_color=s["border"])
        self.macros_scroll.configure(fg_color=s["panel"])

        self.preview_title.configure(text_color=s["text"])
        self.preview_meta.configure(text_color=s["muted"])
        self.preview_box.configure(fg_color=s["panel"], text_color=s["text"])

        self.bind_label.configure(text_color=s["text"])
        self.bind_entry.configure(fg_color=s["panel"], text_color=s["text"], border_color=s["border"])
        self.binds_box.configure(fg_color=s["panel"], text_color=s["text"])

        for b in [self.btn_load, self.btn_rename, self.btn_clone, self.btn_export, self.btn_import, self.btn_bind]:
            b.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent2"])
        self.btn_delete.configure(fg_color=s["danger"], hover_color=s["danger"], text_color="#ffffff")
        self.btn_unbind.configure(fg_color=s["danger"], hover_color=s["danger"], text_color="#ffffff")
        self.btn_play_sel.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent"])
        self.btn_stop_sel.configure(fg_color=s["danger"], hover_color=s["danger"], text_color="#ffffff")

        # settings
        self.set_wrap.configure(fg_color=s["card"])
        self.apply_glow(self.set_wrap, True)
        self.set_title.configure(text_color=s["text"])
        self.set_hint.configure(text_color=s["muted"])

        for lab in self.set_labels:
            lab.configure(text_color=s["text"])
        for ent in self.set_entries:
            ent.configure(fg_color=s["panel"], text_color=s["text"], border_color=s["border"])
        for lab in self.hk_labels:
            lab.configure(text_color=s["text"])
        for ent in self.hk_entries:
            ent.configure(fg_color=s["panel"], text_color=s["text"], border_color=s["border"])

        self.btn_apply.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent"])
        self.btn_reset.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent2"])
        self.btn_apply_hotkeys.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent2"])

        self._restyle_macro_buttons()

    # ---------------------------
    # Texts
    # ---------------------------
    def apply_texts(self):
        self.lbl_brand.configure(text=self.i18n.t("app_title"))
        self.btn_record.configure(text=self.i18n.t("nav_record"))
        self.btn_library.configure(text=self.i18n.t("nav_library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings"))

        self.lbl_style.configure(text=self.i18n.t("style"))
        self.lbl_mode.configure(text=self.i18n.t("theme"))
        self.lbl_lang.configure(text=self.i18n.t("language"))
        self.lbl_glow.configure(text=self.i18n.t("glow"))

        self.support_title.configure(text=self.i18n.t("support"))
        self.support_text.configure(text=self.i18n.t("support_text"))

        if self._active_page == "record":
            self.h_title.configure(text=self.i18n.t("page_record"))
        elif self._active_page == "library":
            self.h_title.configure(text=self.i18n.t("page_library"))
        else:
            self.h_title.configure(text=self.i18n.t("page_settings"))

        # record
        self.rec_title.configure(text=self.i18n.t("rec_controls"))
        self.btn_start.configure(text=self.i18n.t("rec_start"))
        self.btn_stop.configure(text=self.i18n.t("rec_stop"))
        self.btn_play.configure(text=self.i18n.t("rec_play_loaded"))
        self.btn_stopplay.configure(text=self.i18n.t("rec_stop_play"))
        self.save_label.configure(text=self.i18n.t("rec_save_label"))
        self.btn_save.configure(text=self.i18n.t("rec_save_btn"))
        self.log_title.configure(text="Log")
        self.btn_clear_log.configure(text=self.i18n.t("rec_clear_log"))
        self.tips_title.configure(text=self.i18n.t("rec_tips"))

        # library
        self.lib_title.configure(text=self.i18n.t("lib_title"))
        self.search_entry.configure(placeholder_text=self.i18n.t("search_ph"))
        self.btn_load.configure(text=self.i18n.t("btn_load"))
        self.btn_delete.configure(text=self.i18n.t("btn_delete"))
        self.btn_rename.configure(text=self.i18n.t("btn_rename"))
        self.btn_clone.configure(text=self.i18n.t("btn_clone"))
        self.btn_export.configure(text=self.i18n.t("btn_export"))
        self.btn_import.configure(text=self.i18n.t("btn_import"))
        self.bind_label.configure(text=self.i18n.t("bind"))
        self.bind_entry.configure(placeholder_text=self.i18n.t("bind_ph"))
        self.btn_bind.configure(text=self.i18n.t("bind_set"))
        self.btn_unbind.configure(text=self.i18n.t("bind_remove"))
        self.btn_play_sel.configure(text=self.i18n.t("play_selected"))
        self.btn_stop_sel.configure(text=self.i18n.t("rec_stop_play"))

        # settings
        self.set_title.configure(text=self.i18n.t("settings_playback"))
        self.btn_apply.configure(text=self.i18n.t("apply"))
        self.btn_reset.configure(text=self.i18n.t("reset"))
        self.hk_title.configure(text=self.i18n.t("base_hotkeys"))
        self.btn_apply_hotkeys.configure(text=self.i18n.t("hk_apply"))

        self.set_labels[0].configure(text=self.i18n.t("repeat"))
        self.set_labels[1].configure(text=self.i18n.t("loop"))
        self.set_labels[2].configure(text=self.i18n.t("speed"))
        self.set_labels[3].configure(text=self.i18n.t("delay"))

        self.hk_labels[0].configure(text=self.i18n.t("hk_rec"))
        self.hk_labels[1].configure(text=self.i18n.t("hk_stoprec"))
        self.hk_labels[2].configure(text=self.i18n.t("hk_play"))
        self.hk_labels[3].configure(text=self.i18n.t("hk_stop"))

        self.refresh_binds_box()
        self.refresh_library()
        self.preview_selected()
        self.update_tip_text(force=True)

    # ---------------------------
    # Navigation (no animation)
    # ---------------------------
    def show_page(self, which: str):
        self._active_page = which
        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid_remove()

        if which == "record":
            self.page_record.grid()
            self.h_title.configure(text=self.i18n.t("page_record"))
        elif which == "library":
            self.page_library.grid()
            self.h_title.configure(text=self.i18n.t("page_library"))
        else:
            self.page_settings.grid()
            self.h_title.configure(text=self.i18n.t("page_settings"))

        self.apply_style()

    # ---------------------------
    # Record page + tips panel
    # ---------------------------
    def build_record_page(self):
        self.page_record.grid_columnconfigure(0, weight=1)
        self.page_record.grid_columnconfigure(1, weight=1)
        self.page_record.grid_rowconfigure(2, weight=1)

        self.card_ctrl = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_ctrl.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=(16, 10))

        self.rec_title = ctk.CTkLabel(self.card_ctrl, text="Controls", font=ctk.CTkFont(size=16, weight="bold"))
        self.rec_title.pack(anchor="w", padx=16, pady=(16, 8))

        row1 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=6)

        self.btn_start = ctk.CTkButton(row1, text="Start", command=self.engine.start_recording)
        self.btn_start.pack(side="left", padx=6)

        self.btn_stop = ctk.CTkButton(row1, text="Stop", command=self.engine.stop_recording)
        self.btn_stop.pack(side="left", padx=6)

        row2 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=6)

        self.btn_play = ctk.CTkButton(row2, text="Play", command=self.play_from_ui)
        self.btn_play.pack(side="left", padx=6)

        self.btn_stopplay = ctk.CTkButton(row2, text="Stop", command=self.engine.stop_playing)
        self.btn_stopplay.pack(side="left", padx=6)

        self.save_label = ctk.CTkLabel(self.card_ctrl, text="Save:", font=ctk.CTkFont(size=12))
        self.save_label.pack(anchor="w", padx=16, pady=(12, 4))

        self.save_name = ctk.StringVar(value="New macro")
        self.save_entry = ctk.CTkEntry(self.card_ctrl, textvariable=self.save_name)
        self.save_entry.pack(fill="x", padx=16, pady=6)

        self.btn_save = ctk.CTkButton(self.card_ctrl, text="Save", command=self.save_current_macro)
        self.btn_save.pack(fill="x", padx=16, pady=(6, 16))

        # tips panel (right)
        self.card_tips = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_tips.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=(16, 10))

        self.tips_title = ctk.CTkLabel(self.card_tips, text="Tips", font=ctk.CTkFont(size=16, weight="bold"))
        self.tips_title.pack(anchor="w", padx=16, pady=(16, 8))

        self.tips_text = ctk.CTkLabel(self.card_tips, text="", justify="left", wraplength=420)
        self.tips_text.pack(anchor="w", padx=16, pady=(0, 16))

        self._tips = [
            lambda: ("Run as Admin if your game/app is Admin." if self.i18n.lang == "en"
                     else "Запускай от Админа, если игра/программа запущена от Админа."),
            lambda: ("Hotkeys: set in Settings → Base hotkeys." if self.i18n.lang == "en"
                     else "Хоткеи: настраиваются в Настройки → Базовые хоткеи."),
            lambda: (f"Support: Discord {SUPPORT_DISCORD}" if self.i18n.lang == "en"
                     else f"Поддержка: Discord {SUPPORT_DISCORD}"),
            lambda: ("If binds conflict with base hotkeys, bind is skipped." if self.i18n.lang == "en"
                     else "Если бинд конфликтует с базовым хоткеем — он пропускается."),
            lambda: ("Use Loop to run for N seconds (Repeat ignored)." if self.i18n.lang == "en"
                     else "Loop запускает на N секунд (Repeat игнорируется)."),
        ]
        self._tip_i = 0

        self.log_title = ctk.CTkLabel(self.page_record, text="Log", font=ctk.CTkFont(size=14, weight="bold"))
        self.log_title.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 6))

        self.log_box = ctk.CTkTextbox(self.page_record, height=220, corner_radius=18)
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 10))

        self.btn_clear_log = ctk.CTkButton(self.page_record, text="Clear", command=self.clear_log_ui)
        self.btn_clear_log.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

        self.after(1200, self.update_tip_text)

    def update_tip_text(self, force: bool = False):
        if not self._tips:
            return
        if force:
            self._tip_i = 0
        try:
            txt = self._tips[self._tip_i % len(self._tips)]()
            self.tips_text.configure(text=txt)
            self._tip_i += 1
        except Exception:
            pass
        self.after(4500, self.update_tip_text)

    def clear_log_ui(self):
        try:
            self.log_box.delete("1.0", "end")
        except Exception:
            pass

    def play_from_ui(self):
        s = self.current_play_settings()
        self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])

    def save_current_macro(self):
        name = self.save_name.get().strip()
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("save_name_warn"))
            return
        if not self.engine.events:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("no_events_warn"))
            return
        if self.db.exists(name):
            if not messagebox.askyesno(self.i18n.t("app_title"), self.i18n.t("overwrite_q")):
                return

        settings = self.current_play_settings()
        events = [asdict(e) for e in self.engine.events]
        self.db.put(name, events, settings)
        log.info(f"{self.i18n.t('saved')}: {name} (events: {len(events)})")
        self.refresh_library()
        self.show_page("library")

    # ---------------------------
    # Library page
    # ---------------------------
    def build_library_page(self):
        self.page_library.grid_columnconfigure(0, weight=1)
        self.page_library.grid_columnconfigure(1, weight=2)
        self.page_library.grid_rowconfigure(0, weight=1)

        self.lib_left = ctk.CTkFrame(self.page_library, corner_radius=18)
        self.lib_left.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=16)
        self.lib_left.grid_rowconfigure(3, weight=1)
        self.lib_left.grid_columnconfigure(0, weight=1)

        self.lib_title = ctk.CTkLabel(self.lib_left, text="Library", font=ctk.CTkFont(size=16, weight="bold"))
        self.lib_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(self.lib_left, textvariable=self.search_var, placeholder_text="Search…")
        self.search_entry.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_library())

        self.macros_scroll = ctk.CTkScrollableFrame(self.lib_left, corner_radius=14)
        self.macros_scroll.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        actions = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)

        self.btn_load = ctk.CTkButton(actions, text="Load", command=self.load_selected)
        self.btn_load.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_delete = ctk.CTkButton(actions, text="Delete", command=self.delete_selected)
        self.btn_delete.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions2 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions2.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions2.grid_columnconfigure((0, 1), weight=1)

        self.btn_rename = ctk.CTkButton(actions2, text="Rename", command=self.rename_selected)
        self.btn_rename.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_clone = ctk.CTkButton(actions2, text="Clone", command=self.clone_selected)
        self.btn_clone.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions3 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions3.grid(row=6, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions3.grid_columnconfigure((0, 1), weight=1)

        self.btn_export = ctk.CTkButton(actions3, text="Export JSON", command=self.export_selected)
        self.btn_export.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_import = ctk.CTkButton(actions3, text="Import JSON", command=self.import_macro)
        self.btn_import.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        # right
        self.lib_right = ctk.CTkFrame(self.page_library, corner_radius=18)
        self.lib_right.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=16)
        self.lib_right.grid_rowconfigure(4, weight=1)
        self.lib_right.grid_columnconfigure(0, weight=1)

        self.preview_title = ctk.CTkLabel(self.lib_right, text="—", font=ctk.CTkFont(size=18, weight="bold"))
        self.preview_title.grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")

        self.preview_meta = ctk.CTkLabel(self.lib_right, text="—")
        self.preview_meta.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")

        bind_row = ctk.CTkFrame(self.lib_right, fg_color="transparent")
        bind_row.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="ew")
        bind_row.grid_columnconfigure(1, weight=1)

        self.bind_label = ctk.CTkLabel(bind_row, text="Bind:", width=90, anchor="w")
        self.bind_label.grid(row=0, column=0, sticky="w")

        self.bind_var = ctk.StringVar(value="F6")
        self.bind_entry = ctk.CTkEntry(bind_row, textvariable=self.bind_var, placeholder_text="F6 or Ctrl+Alt+F6")
        self.bind_entry.grid(row=0, column=1, sticky="ew", padx=(10, 10))

        self.btn_bind = ctk.CTkButton(bind_row, text="Set", width=110, command=self.bind_selected)
        self.btn_bind.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.btn_unbind = ctk.CTkButton(bind_row, text="Remove", width=90, command=self.unbind_selected)
        self.btn_unbind.grid(row=0, column=3, sticky="e")

        self.binds_box = ctk.CTkTextbox(self.lib_right, height=120, corner_radius=14)
        self.binds_box.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        self.preview_box = ctk.CTkTextbox(self.lib_right, corner_radius=14)
        self.preview_box.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="nsew")

        playbar = ctk.CTkFrame(self.lib_right, fg_color="transparent")
        playbar.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        playbar.grid_columnconfigure((0, 1), weight=1)

        self.btn_play_sel = ctk.CTkButton(playbar, text="Play selected", command=self.play_selected)
        self.btn_play_sel.grid(row=0, column=0, padx=6, sticky="ew")

        self.btn_stop_sel = ctk.CTkButton(playbar, text="Stop", command=self.engine.stop_playing)
        self.btn_stop_sel.grid(row=0, column=1, padx=6, sticky="ew")

        self.refresh_library()
        self.refresh_binds_box()

    def refresh_binds_box(self):
        self.binds_box.delete("1.0", "end")
        binds = self.db.binds()
        if not binds:
            self.binds_box.insert("end", self.i18n.t("binds_none") + "\n")
            return
        for hk, mn in sorted(binds.items(), key=lambda x: x[0]):
            self.binds_box.insert("end", f"{hk}  ->  {mn}\n")

    def refresh_library(self):
        q = self.search_var.get().strip().lower()

        for child in self.macros_scroll.winfo_children():
            try: child.destroy()
            except Exception: pass
        self.macro_buttons.clear()

        names = [n for n in self.db.names() if (not q or q in n.lower())]

        if not names:
            empty = ctk.CTkLabel(self.macros_scroll, text=self.i18n.t("empty"))
            empty.pack(anchor="w", padx=8, pady=8)
            self.selected_macro = None
            self.preview_clear()
            return

        if self.selected_macro not in names:
            self.selected_macro = names[0]

        for n in names:
            btn = ctk.CTkButton(self.macros_scroll, text=n, anchor="w",
                                corner_radius=12, command=lambda name=n: self.select_macro(name))
            btn.pack(fill="x", padx=6, pady=6)
            self.macro_buttons[n] = btn

        self._restyle_macro_buttons()
        self.preview_selected()

    def _restyle_macro_buttons(self):
        s = style_get(self.current_style)
        for name, btn in self.macro_buttons.items():
            if name == self.selected_macro:
                btn.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"],
                              border_width=2, border_color=s["accent"])
            else:
                btn.configure(fg_color=s["card"], hover_color=s["border"], text_color=s["text"], border_width=0)

    def select_macro(self, name: str):
        self.selected_macro = name
        self._restyle_macro_buttons()
        self.preview_selected()

    def preview_clear(self):
        self.preview_title.configure(text="—")
        self.preview_meta.configure(text="—")
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
        if self.i18n.lang == "ru":
            meta = f"Создан: {created_str} | Событий: {count} | repeat={st.get('repeat',1)} loop={st.get('loop_seconds',0)} speed={st.get('speed',1.0)}"
        else:
            meta = f"Created: {created_str} | Events: {count} | repeat={st.get('repeat',1)} loop={st.get('loop_seconds',0)} speed={st.get('speed',1.0)}"

        self.preview_title.configure(text=name)
        self.preview_meta.configure(text=meta)
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("end", json.dumps(st, ensure_ascii=False, indent=2))

    def load_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", [])]
        self.apply_play_settings_to_ui(item.get("settings", {}))
        log.info(f"{self.i18n.t('loaded')}: {name} (events: {len(self.engine.events)})")
        self.show_page("record")

    def play_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", [])]
        self.apply_play_settings_to_ui(item.get("settings", {}))
        s = self.current_play_settings()
        self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])

    def delete_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        if not messagebox.askyesno(self.i18n.t("app_title"), self.i18n.t("delete_q") + f" '{name}'?"):
            return
        self.db.delete(name)
        log.info(f"{self.i18n.t('deleted')}: {name}")
        self.selected_macro = None
        self.refresh_library()
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    def rename_selected(self):
        old = self.selected_macro
        if not old:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(self.i18n.t("btn_rename"))
        dialog.geometry("420x180")
        dialog.resizable(False, False)
        dialog.grab_set()

        frm = ctk.CTkFrame(dialog, corner_radius=18)
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(frm, text=self.i18n.t("btn_rename"),
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        var = ctk.StringVar(value=old)
        ent = ctk.CTkEntry(frm, textvariable=var)
        ent.pack(fill="x", padx=12, pady=6)
        ent.focus_set()

        def do():
            new = var.get().strip()
            if not new or new == old:
                dialog.destroy()
                return
            ok = self.db.rename(old, new)
            if not ok:
                messagebox.showerror(self.i18n.t("app_title"),
                                     "Name exists." if self.i18n.lang == "en" else "Имя уже занято.")
                return
            log.info(f"{self.i18n.t('renamed')}: {old} -> {new}")
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
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(self.i18n.t("btn_clone"))
        dialog.geometry("460x190")
        dialog.resizable(False, False)
        dialog.grab_set()

        frm = ctk.CTkFrame(dialog, corner_radius=18)
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(frm, text=f"{self.i18n.t('btn_clone')}: {src}",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        var = ctk.StringVar(value=f"{src} (copy)")
        ent = ctk.CTkEntry(frm, textvariable=var)
        ent.pack(fill="x", padx=12, pady=6)
        ent.focus_set()

        def do():
            dst = var.get().strip()
            if not dst:
                return
            ok = self.db.clone(src, dst)
            if not ok:
                messagebox.showerror(self.i18n.t("app_title"),
                                     "Failed (name exists?)" if self.i18n.lang == "en" else "Ошибка (имя занято?)")
                return
            log.info(f"{self.i18n.t('cloned')}: {src} -> {dst}")
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
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        item = self.db.get(name)
        if not item:
            return

        default_name = f"{name}.json"
        path = filedialog.asksaveasfilename(
            title=self.i18n.t("btn_export"),
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
            log.info(f"{self.i18n.t('exported')}: {name} -> {path}")
        except Exception as e:
            log.error(f"Export error: {e}")
            messagebox.showerror(self.i18n.t("app_title"), f"Error: {e}")

    def import_macro(self):
        path = filedialog.askopenfilename(title=self.i18n.t("btn_import"), filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict) or "events" not in payload:
                raise ValueError("Invalid file")

            name = str(payload.get("name", os.path.splitext(os.path.basename(path))[0])).strip() or "Imported macro"
            if self.db.exists(name):
                base = name
                i = 2
                while self.db.exists(f"{base} ({i})"):
                    i += 1
                name = f"{base} ({i})"

            settings = payload.get("settings", {})
            events = payload.get("events", [])

            ev_objs: List[Event] = []
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

            self.db.put(name, [asdict(x) for x in ev_objs], settings if isinstance(settings, dict) else {})
            log.info(f"{self.i18n.t('imported')}: {name} (events: {len(ev_objs)})")
            self.selected_macro = name
            self.refresh_library()
        except Exception as e:
            log.error(f"Import error: {e}")
            log.error(traceback.format_exc())
            messagebox.showerror(self.i18n.t("app_title"), f"Error: {e}")

    def bind_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        hk_raw = self.bind_var.get()
        hk = normalize_hotkey(hk_raw)
        if not hk:
            messagebox.showerror(self.i18n.t("app_title"), self.i18n.t("invalid_hotkey"))
            return

        binds = self.db.binds()
        if hk in binds and binds[hk] != name:
            if not messagebox.askyesno(self.i18n.t("app_title"),
                                       f"{hk} already bound to '{binds[hk]}'. Override?"):
                return

        self.db.set_bind(hk, name)
        log.info(f"Bind: {hk} -> {name}")
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    def unbind_selected(self):
        hk_raw = self.bind_var.get()
        hk = normalize_hotkey(hk_raw)
        if not hk:
            messagebox.showerror(self.i18n.t("app_title"), self.i18n.t("invalid_hotkey"))
            return
        self.db.remove_bind(hk)
        log.info(f"Unbound: {hk}")
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    # ---------------------------
    # Settings page
    # ---------------------------
    def build_settings_page(self):
        self.page_settings.grid_columnconfigure(0, weight=1)
        self.page_settings.grid_rowconfigure(0, weight=1)

        self.set_wrap = ctk.CTkFrame(self.page_settings, corner_radius=18)
        self.set_wrap.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.set_wrap.grid_columnconfigure(0, weight=1)

        self.set_title = ctk.CTkLabel(self.set_wrap, text="Playback", font=ctk.CTkFont(size=18, weight="bold"))
        self.set_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self.set_labels: List[ctk.CTkLabel] = []
        self.set_entries: List[ctk.CTkEntry] = []

        def add_row(r: int, label: str, var: ctk.StringVar, placeholder: str):
            row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
            row.grid(row=r, column=0, padx=16, pady=8, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            lab = ctk.CTkLabel(row, text=label, width=200, anchor="w")
            lab.grid(row=0, column=0, sticky="w")

            ent = ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder)
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))

            self.set_labels.append(lab)
            self.set_entries.append(ent)

        add_row(1, "Repeat", self.repeat_var, "e.g. 5")
        add_row(2, "Loop", self.loop_var, "e.g. 7200")
        add_row(3, "Speed", self.speed_var, "0.5 / 1.0 / 2.0")
        add_row(4, "Delay", self.delay_var, "e.g. 3")

        self.set_hint = ctk.CTkLabel(self.set_wrap, text="If Loop > 0, Repeat is ignored.", anchor="w")
        self.set_hint.grid(row=5, column=0, padx=16, pady=(4, 12), sticky="w")

        # base hotkeys
        self.hk_title = ctk.CTkLabel(self.set_wrap, text="Base hotkeys", font=ctk.CTkFont(weight="bold"))
        self.hk_title.grid(row=6, column=0, padx=16, pady=(10, 6), sticky="w")

        self.hk_labels: List[ctk.CTkLabel] = []
        self.hk_entries: List[ctk.CTkEntry] = []

        def hk_row(r: int, label: str, var: ctk.StringVar):
            row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
            row.grid(row=r, column=0, padx=16, pady=6, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            lab = ctk.CTkLabel(row, text=label, width=200, anchor="w")
            lab.grid(row=0, column=0, sticky="w")
            ent = ctk.CTkEntry(row, textvariable=var, placeholder_text="e.g. Ctrl+Alt+1 or F6")
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))

            self.hk_labels.append(lab)
            self.hk_entries.append(ent)

        hk_row(7, "Start record", self.hk_rec_var)
        hk_row(8, "Stop record", self.hk_stoprec_var)
        hk_row(9, "Play loaded", self.hk_play_var)
        hk_row(10, "Stop playing", self.hk_stop_var)

        btns = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        btns.grid(row=11, column=0, padx=16, pady=(10, 16), sticky="w")

        self.btn_apply = ctk.CTkButton(btns, text="Apply", command=self.apply_settings)
        self.btn_apply.pack(side="left", padx=6)

        self.btn_reset = ctk.CTkButton(btns, text="Reset", command=self.reset_settings)
        self.btn_reset.pack(side="left", padx=6)

        self.btn_apply_hotkeys = ctk.CTkButton(btns, text="Apply hotkeys", command=self.apply_hotkeys_from_ui)
        self.btn_apply_hotkeys.pack(side="left", padx=6)

    def reset_settings(self):
        self.repeat_var.set("1")
        self.loop_var.set("0")
        self.speed_var.set("1.0")
        self.delay_var.set("0")
        self.apply_settings()
        log.info("Settings reset.")

    def apply_settings(self):
        # apply + persist only (engine reads from UI at play time)
        self.persist_settings()
        s = self.current_play_settings()
        log.info(f"Applied: repeat={s['repeat']} loop={s['loop_seconds']} speed={s['speed']} delay={s['start_delay']}")

    def apply_hotkeys_from_ui(self):
        hk_rec = normalize_hotkey(self.hk_rec_var.get())
        hk_stoprec = normalize_hotkey(self.hk_stoprec_var.get())
        hk_play = normalize_hotkey(self.hk_play_var.get())
        hk_stop = normalize_hotkey(self.hk_stop_var.get())

        if not all([hk_rec, hk_stoprec, hk_play, hk_stop]):
            messagebox.showerror(self.i18n.t("app_title"), self.i18n.t("invalid_hotkey"))
            return

        self.persist_settings()
        self.rebuild_hotkeys()
        log.info("Base hotkeys updated.")

    # ---------------------------
    # Hotkeys rebuild (base + binds)
    # ---------------------------
    def rebuild_hotkeys(self):
        def hk_norm(raw: str, fallback: str) -> str:
            v = normalize_hotkey(raw)
            return v if v else (normalize_hotkey(fallback) or "<f6>")

        base = {
            hk_norm(self.hk_rec_var.get(), "Ctrl+Alt+1"): self.engine.start_recording,
            hk_norm(self.hk_stoprec_var.get(), "Ctrl+Alt+2"): self.engine.stop_recording,
            hk_norm(self.hk_play_var.get(), "Ctrl+Alt+3"): self.play_from_ui,
            hk_norm(self.hk_stop_var.get(), "Ctrl+Alt+4"): self.engine.stop_playing,
        }

        binds = self.db.binds()
        for hk, macro_name in binds.items():
            if hk in base:
                log.warn(f"Bind conflicts with base hotkey: {hk} (skipped)")
                continue

            def make_play(name=macro_name):
                def _f():
                    item = self.db.get(name)
                    if not item:
                        log.warn(f"[bind] macro not found: {name}")
                        return
                    self.engine.events = [Event(**e) for e in item.get("events", [])]
                    self.apply_play_settings_to_ui(item.get("settings", {}))
                    s = self.current_play_settings()
                    self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])
                    log.info(f"[bind] play: {name}")
                return _f

            base[hk] = make_play()

        self.hk.set(base)


# ============================================================
# Run app
# ============================================================

def run_app():
    app = SaonixApp()
    app.mainloop()


# ============================================================
# Main entry: show loader first
# ============================================================

def main():
    # loader first; then app
    l = Loader()
    l.mainloop()

if __name__ == "__main__":
    main()
