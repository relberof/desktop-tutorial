# saonix.py
# Saonix Macro Recorder — single-file fixed build
# - Fixes: indentation, __init__/__name__, Windows path strings, duplicate methods, missing methods,
#   settings/apply/current_settings, hotkey rebuild, safe shutdown, safer locale detection, safer CTk theme usage.
# - Requires: customtkinter, pynput

import os
import json
import time
import threading
import traceback
import locale as pylocale
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Callable

import customtkinter as ctk
from tkinter import messagebox, filedialog

from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, KeyCode, Controller as KeyboardController


# =========================================================
# Paths
# =========================================================

APP_NAME = "Saonix"

def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path

def get_root_dir() -> str:
    base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    root = os.path.join(base, APP_NAME)
    try:
        ensure_dir(root)
        test = os.path.join(root, "_rw.tmp")
        with open(test, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test)
        return root
    except Exception:
        here = os.path.abspath(os.path.dirname(__file__))
        return ensure_dir(os.path.join(here, APP_NAME))

ROOT = get_root_dir()
DIR_APP = ensure_dir(os.path.join(ROOT, "app"))
DIR_DATA = ensure_dir(os.path.join(ROOT, "data"))
DIR_LOGS = ensure_dir(os.path.join(ROOT, "logs"))
DIR_LOCALES = ensure_dir(os.path.join(ROOT, "locales"))

DB_FILE = os.path.join(DIR_DATA, "macros_db.json")
CFG_FILE = os.path.join(DIR_DATA, "config.json")
LOG_FILE = os.path.join(DIR_LOGS, "app.log")
CRASH_FILE = os.path.join(DIR_LOGS, "crash_log.txt")


# =========================================================
# Utils
# =========================================================

def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def safe_int(v: str, default: int) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default

def safe_float(v: str, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default

def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# =========================================================
# Logger
# =========================================================

class Logger:
    def __init__(self, ui_append: Optional[Callable[[str], None]] = None):
        self.ui_append = ui_append
        self._lock = threading.Lock()

    def _write_file(self, line: str):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _emit_ui(self, line: str):
        if not self.ui_append:
            return
        try:
            self.ui_append(line + "\n")
        except Exception:
            pass

    def _log(self, level: str, msg: str):
        line = f"[{ts()}] [{level}] {msg}"
        with self._lock:
            self._write_file(line)
        self._emit_ui(line)

    def info(self, msg: str): self._log("INFO", msg)
    def warn(self, msg: str): self._log("WARN", msg)
    def error(self, msg: str): self._log("ERROR", msg)


# =========================================================
# i18n
# =========================================================

def system_lang_guess() -> str:
    # Avoid ctypes hard-dependency; keep it portable.
    try:
        loc = pylocale.getdefaultlocale()[0] or ""
        loc = loc.replace("_", "-")
        if loc.lower().startswith("pt-br"):
            return "pt-BR"
        if loc:
            return loc.split("-")[0].lower()
    except Exception:
        pass
    return "en"

class I18N:
    SUPPORTED = ["en", "ru", "zh", "ja", "ko", "id", "fr", "pt-BR", "vi", "pl"]

    BUILTIN_EN = {
        "app_title": "Saonix",
        "nav_record": "● Record",
        "nav_library": "📚 Library",
        "nav_settings": "⚙ Settings",
        "style": "Style",
        "theme": "Theme",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "glow": "Glow",
        "language": "Language",
        "status_ready": "Ready",
        "status_recording": "● Recording…",
        "status_playing": "▶ Playing…",

        "page_record": "Record",
        "page_library": "Library",
        "page_settings": "Settings",

        "rec_controls": "Controls",
        "rec_start": "● Start recording",
        "rec_stop": "■ Stop recording",
        "rec_play_loaded": "▶ Play (loaded)",
        "rec_stop_play": "⏹ Stop",
        "rec_save_label": "Save to library:",
        "rec_save_btn": "💾 Save",

        "hotkeys_title": "Hotkeys",
        "hint_admin": "If your game/app runs as Admin, run Saonix as Admin too.",
        "hint_defaults": "Default: Ctrl+Alt+1 record | Ctrl+Alt+2 stop rec | Ctrl+Alt+3 play loaded | Ctrl+Alt+4 stop",

        "log_title": "Log",
        "log_clear": "Clear log (window)",

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

        "settings_playback": "Playback settings",
        "repeat": "Repeat (times)",
        "loop": "Loop (sec)",
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
        "overwrite_q": "Macro already exists. Overwrite?",
        "select_macro_warn": "Select a macro.",
        "delete_q": "Delete macro?",
        "invalid_hotkey": "Invalid format. Example: F6 or Ctrl+Alt+F6",

        "star": "✦",
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

    BUILTIN_RU = {
        "app_title": "Saonix",
        "nav_record": "● Запись",
        "nav_library": "📚 Библиотека",
        "nav_settings": "⚙ Настройки",
        "style": "Стиль",
        "theme": "Тема",
        "theme_dark": "Тёмная",
        "theme_light": "Светлая",
        "glow": "Подсветка (Glow)",
        "language": "Язык",
        "status_ready": "Готово",
        "status_recording": "● Запись…",
        "status_playing": "▶ Воспроизведение…",

        "page_record": "Запись",
        "page_library": "Библиотека",
        "page_settings": "Настройки",

        "rec_controls": "Управление",
        "rec_start": "● Начать запись",
        "rec_stop": "■ Остановить запись",
        "rec_play_loaded": "▶ Воспроизвести (загруженный)",
        "rec_stop_play": "⏹ Остановить",
        "rec_save_label": "Сохранить в библиотеку:",
        "rec_save_btn": "💾 Сохранить",

        "hotkeys_title": "Горячие клавиши",
        "hint_admin": "Если игра/программа запущена от Админа — запускай Saonix от Админа.",
        "hint_defaults": "По умолчанию: Ctrl+Alt+1 запись | Ctrl+Alt+2 стоп | Ctrl+Alt+3 пуск | Ctrl+Alt+4 стоп",

        "log_title": "Лог",
        "log_clear": "Очистить лог (в окне)",

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
        "play_selected": "▶ Воспроизвести выбранный",

        "settings_playback": "Настройки воспроизведения",
        "repeat": "Повтор (раз)",
        "loop": "Цикл (сек)",
        "speed": "Скорость",
        "delay": "Задержка старта (сек)",
        "apply": "Применить",
        "reset": "Сбросить",

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

        "star": "✦",
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
        self.dict: Dict[str, str] = dict(self.BUILTIN_EN)
        self.load(lang)

    def load(self, lang: str):
        lang = (lang or "en").strip()
        if lang == "auto":
            lang = system_lang_guess()

        if lang not in self.SUPPORTED:
            base = lang.split("-")[0]
            lang = base if base in self.SUPPORTED else "en"

        base_dict = dict(self.BUILTIN_EN)
        if lang == "ru":
            base_dict.update(self.BUILTIN_RU)

        # Optional external override
        path = os.path.join(DIR_LOCALES, f"{lang}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    ext = json.load(f)
                if isinstance(ext, dict):
                    base_dict.update({k: str(v) for k, v in ext.items()})
            except Exception:
                pass

        self.lang = lang
        self.dict = base_dict

    def t(self, key: str) -> str:
        return self.dict.get(key, key)


# =========================================================
# DB
# =========================================================

class MacroDB:
    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 4, "macros": {}, "binds": {}, "settings": {}}
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data.update(d)
                self.data.setdefault("macros", {})
                self.data.setdefault("binds", {})
                self.data.setdefault("settings", {})
        except Exception:
            pass

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def names(self) -> List[str]:
        return sorted(self.data.get("macros", {}).keys(), key=lambda x: x.lower())

    def exists(self, name: str) -> bool:
        return name in self.data.get("macros", {})

    def get(self, name: str) -> Optional[dict]:
        return self.data.get("macros", {}).get(name)

    def put(self, name: str, events: List[dict], settings: Dict[str, Any]):
        self.data.setdefault("macros", {})
        self.data["macros"][name] = {
            "created": int(time.time()),
            "events": events,
            "settings": settings,
        }
        self.save()

    def delete(self, name: str):
        if name in self.data.get("macros", {}):
            del self.data["macros"][name]
        # remove binds targeting this macro
        binds = self.data.get("binds", {})
        dead = [hk for hk, mn in binds.items() if mn == name]
        for hk in dead:
            del binds[hk]
        self.save()

    def rename(self, old: str, new: str) -> bool:
        if old not in self.data.get("macros", {}):
            return False
        if new in self.data.get("macros", {}):
            return False
        self.data["macros"][new] = self.data["macros"].pop(old)
        for hk, mn in list(self.data.get("binds", {}).items()):
            if mn == old:
                self.data["binds"][hk] = new
        self.save()
        return True

    def clone(self, src: str, dst: str) -> bool:
        if src not in self.data.get("macros", {}):
            return False
        if dst in self.data.get("macros", {}):
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


# =========================================================
# Hotkey parsing (GlobalHotKeys format)
# =========================================================

def normalize_hotkey(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None
    t = t.replace("<", "").replace(">", "")

    # Single F1..F24
    if t.startswith("f") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 24:
            return f"<f{n}>"
        return None

    parts = t.split("+")
    mods: List[str] = []
    key: Optional[str] = None

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

    # Key normalize
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


# =========================================================
# Engine
# =========================================================

@dataclass
class Event:
    t: float
    device: str
    type: str
    data: Dict[str, Any]

class MacroEngine:
    """
    - No FN/WIN blocking: pynput keyboard.Listener(suppress=False)
    """
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

        # Throttle mouse moves
        self._last_move: Optional[tuple] = None
        self._last_move_time = 0.0
        self._min_move_interval = 0.01  # 100 Hz max

        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._kb_listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
        )

        self._mouse_listener.start()
        self._kb_listener.start()
        self.log.info("Engine ready.")

    def shutdown(self):
        try:
            self._mouse_listener.stop()
        except Exception:
            pass
        try:
            self._kb_listener.stop()
        except Exception:
            pass

    def now(self) -> float:
        return time.perf_counter()

    def rel_time(self) -> float:
        return 0.0 if self._t0 is None else (self.now() - self._t0)

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

    # ---------- record handlers ----------
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
        btn_name = button.name if hasattr(button, "name") else str(button)
        self._add("mouse", "click", {
            "x": int(x), "y": int(y),
            "button": btn_name,
            "pressed": bool(pressed),
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

    # ---------- playback ----------
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
                self.log.warn("Already playing.")
                return
            if not self.events:
                self.log.warn("No events.")
                return

            self.playing = True
            self._stop_play.clear()

        def play_once():
            base = self.now()
            sp = max(float(speed), 0.05)
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
                    self.log.info(f"Start in {start_delay:.2f}s…")
                    end = time.time() + float(start_delay)
                    while time.time() < end and not self._stop_play.is_set():
                        time.sleep(0.01)

                if loop_seconds > 0:
                    self.log.info(f"=== Loop {loop_seconds}s speed={speed} ===")
                    started = time.time()
                    while not self._stop_play.is_set() and (time.time() - started) < loop_seconds:
                        play_once()
                else:
                    r = max(int(repeat), 1)
                    self.log.info(f"=== Repeat {r} speed={speed} ===")
                    for i in range(r):
                        if self._stop_play.is_set():
                            break
                        self.log.info(f"Pass {i+1}/{r}")
                        play_once()

                self.log.info("=== Playback finished ===")
            except Exception as e:
                self.log.error(f"Playback error: {e}")
                self.log.error(traceback.format_exc())
            finally:
                with self._play_lock:
                    self.playing = False
                    self._stop_play.set()

        threading.Thread(target=run, daemon=True).start()


# =========================================================
# Styles
# =========================================================

class StylePack:
    def __init__(self, name: str, dark: Dict[str, str], light: Dict[str, str]):
        self.name = name
        self.dark = dark
        self.light = light

def style_get(s: StylePack) -> Dict[str, str]:
    return s.dark if ctk.get_appearance_mode() == "Dark" else s.light

STYLES = {
    "Calm": StylePack(
        "Calm",
        dark=dict(
            bg="#0d1118", panel="#121826", card="#141d2e",
            text="#e9eef7", muted="#a7b4cc",
            accent="#5aa7ff", accent2="#7c66ff",
            danger="#ff4a4a", border="#23314a",
        ),
        light=dict(
            bg="#f3f5f9", panel="#ffffff", card="#f7f9fc",
            text="#101828", muted="#475467",
            accent="#2563eb", accent2="#7c3aed",
            danger="#dc2626", border="#d0d5dd",
        )
    ),
    "Aurora": StylePack(
        "Aurora",
        dark=dict(
            bg="#071216", panel="#0b1a20", card="#0d222a",
            text="#e9fffb", muted="#a3d6ce",
            accent="#49f1b8", accent2="#56a8ff",
            danger="#ff4a4a", border="#14343a",
        ),
        light=dict(
            bg="#f1fbfa", panel="#ffffff", card="#f6fffe",
            text="#06201e", muted="#1f6f67",
            accent="#0ea5e9", accent2="#22c55e",
            danger="#dc2626", border="#cde8e4",
        )
    )
}


# =========================================================
# Hotkey Manager
# =========================================================

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


# =========================================================
# App
# =========================================================

class SaonixApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # must exist early
        self._active_page = "record"

        # load DB/settings
        self.db = MacroDB(DB_FILE)
        saved = self.db.get_settings()

        # i18n
        self.lang_choice = saved.get("lang", "auto")
        self.i18n = I18N(self.lang_choice)

        # theme
        theme = saved.get("appearance", "Dark")
        if theme not in ("Dark", "Light"):
            theme = "Dark"
        ctk.set_appearance_mode(theme)

        # style + glow
        style_name = saved.get("style", "Calm")
        self.current_style = STYLES.get(style_name, STYLES["Calm"])
        self.glow_var = ctk.IntVar(value=int(saved.get("glow", 2)))

        # playback defaults
        self.repeat_var = ctk.StringVar(value=str(saved.get("repeat", 1)))
        self.loop_var = ctk.StringVar(value=str(saved.get("loop_seconds", 0)))
        self.speed_var = ctk.StringVar(value=str(saved.get("speed", 1.0)))
        self.delay_var = ctk.StringVar(value=str(saved.get("start_delay", 0.0)))

        # base hotkeys (editable)
        self.hk_rec_var = ctk.StringVar(value=str(saved.get("hk_rec", "Ctrl+Alt+1")))
        self.hk_stoprec_var = ctk.StringVar(value=str(saved.get("hk_stoprec", "Ctrl+Alt+2")))
        self.hk_play_var = ctk.StringVar(value=str(saved.get("hk_play", "Ctrl+Alt+3")))
        self.hk_stop_var = ctk.StringVar(value=str(saved.get("hk_stop", "Ctrl+Alt+4")))

        # window
        self.title(self.i18n.t("app_title"))
        self.geometry("1180x720")
        self.minsize(1000, 640)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # logger/engine/hotkeys
        self.log_box: Optional[ctk.CTkTextbox] = None
        self.logger = Logger(self._append_log_ui)
        self.engine = MacroEngine(self.logger)
        self.hk = HotkeyManager(self.logger)

        # UI skeleton
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=18)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=14, pady=14)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(99, weight=1)

        self.lbl_brand = ctk.CTkLabel(
            self.sidebar,
            text=self.i18n.t("app_title"),
            font=ctk.CTkFont(family="Times New Roman", size=26, weight="bold")
        )
        self.lbl_brand.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        self.lbl_tag = ctk.CTkLabel(self.sidebar, text="Macro Recorder", font=ctk.CTkFont(size=14))
        self.lbl_tag.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")

        self.btn_record = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_record"), command=lambda: self.show_page("record"))
        self.btn_library = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_library"), command=lambda: self.show_page("library"))
        self.btn_settings = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_settings"), command=lambda: self.show_page("settings"))
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
        self.mode_menu = ctk.CTkOptionMenu(self.sidebar, values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")], command=self.set_mode)
        self.mode_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))
        self.mode_menu.grid(row=9, column=0, padx=16, pady=6, sticky="ew")

        self.lbl_lang = ctk.CTkLabel(self.sidebar, text=self.i18n.t("language"), font=ctk.CTkFont(weight="bold"))
        self.lbl_lang.grid(row=10, column=0, padx=16, pady=(10, 4), sticky="w")
        self.lang_menu = ctk.CTkOptionMenu(self.sidebar, values=["auto"] + I18N.SUPPORTED, command=self.set_lang)
        self.lang_menu.set(self.lang_choice if self.lang_choice in (["auto"] + I18N.SUPPORTED) else "auto")
        self.lang_menu.grid(row=11, column=0, padx=16, pady=6, sticky="ew")

        self.lbl_glow = ctk.CTkLabel(self.sidebar, text=self.i18n.t("glow"), font=ctk.CTkFont(weight="bold"))
        self.lbl_glow.grid(row=12, column=0, padx=16, pady=(14, 4), sticky="w")
        self.glow_slider = ctk.CTkSlider(self.sidebar, from_=0, to=3, number_of_steps=3, command=self._on_glow)
        self.glow_slider.set(int(self.glow_var.get()))
        self.glow_slider.grid(row=13, column=0, padx=16, pady=(0, 10), sticky="ew")

        self.star_symbol = ctk.CTkLabel(
            self.sidebar,
            text=self.i18n.t("star"),
            font=ctk.CTkFont(family="Times New Roman", size=78, weight="bold")
        )
        self.star_symbol.place(relx=0.82, rely=0.92, anchor="center")

        # main area
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

        # build pages
        self.build_record_page()
        self.build_library_page()
        self.build_settings_page()

        # apply UI
        self.apply_texts()
        self.apply_style()
        self.show_page("record", restyle_only=True)

        # hotkeys + tick
        self.rebuild_hotkeys()
        self.after(200, self.tick)

        self.logger.info("Started.")
        self.logger.info(self.i18n.t("hint_defaults"))

    # ----------------- core settings -----------------

    def current_play_settings(self) -> Dict[str, Any]:
        repeat = clamp(safe_int(self.repeat_var.get(), 1), 1, 9999)
        loop_seconds = clamp(safe_int(self.loop_var.get(), 0), 0, 24 * 3600)
        speed = clamp(safe_float(self.speed_var.get(), 1.0), 0.05, 5.0)
        delay = clamp(safe_float(self.delay_var.get(), 0.0), 0.0, 60.0)
        return {"repeat": repeat, "loop_seconds": loop_seconds, "speed": speed, "start_delay": delay}

    # compat aliases (so no NameError anywhere)
    def current_settings(self) -> Dict[str, Any]:
        return self.current_play_settings()

    def apply_settings(self, s: Dict[str, Any]):
        # Apply saved macro settings to UI vars
        if not isinstance(s, dict):
            return
        self.repeat_var.set(str(s.get("repeat", self.repeat_var.get())))
        self.loop_var.set(str(s.get("loop_seconds", self.loop_var.get())))
        self.speed_var.set(str(s.get("speed", self.speed_var.get())))
        self.delay_var.set(str(s.get("start_delay", self.delay_var.get())))

    def persist_settings(self):
        s = self.db.get_settings()
        s.update({
            "appearance": ctk.get_appearance_mode(),
            "style": self.style_menu.get(),
            "lang": self.lang_menu.get(),
            "glow": int(self.glow_var.get()),
        })
        s.update(self.current_play_settings())
        s.update({
            "hk_rec": self.hk_rec_var.get(),
            "hk_stoprec": self.hk_stoprec_var.get(),
            "hk_play": self.hk_play_var.get(),
            "hk_stop": self.hk_stop_var.get(),
        })
        self.db.set_settings(s)

    # ----------------- window lifecycle -----------------

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
        self.destroy()

    # ----------------- log sink -----------------

    def _append_log_ui(self, text: str):
        try:
            if self.log_box is None:
                return
            self.log_box.insert("end", text)
            self.log_box.see("end")
        except Exception:
            pass

    # ----------------- status tick -----------------

    def tick(self):
        if self.engine.recording:
            self.status_var.set(self.i18n.t("status_recording"))
        elif self.engine.playing:
            self.status_var.set(self.i18n.t("status_playing"))
        else:
            self.status_var.set(self.i18n.t("status_ready"))
        self.after(200, self.tick)

    # ----------------- theme/style/lang/glow -----------------

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
        # theme strings may change due to language; keep menu coherent
        self.mode_menu.configure(values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")])
        self.mode_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))

    def set_lang(self, lang: str):
        self.lang_choice = lang
        self.i18n.load(lang)
        self.title(self.i18n.t("app_title"))
        self.mode_menu.configure(values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")])
        self.mode_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))
        self.persist_settings()
        self.apply_texts()
        self.apply_style()

    def _on_glow(self, _=None):
        self.glow_var.set(int(round(float(self.glow_slider.get()))))
        self.persist_settings()
        self.apply_style()

    # ----------------- styling -----------------

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
                fg_color=s["card"], hover_color=s["border"],
                text_color=s["text"],
                border_width=2, border_color=s["accent"],
                corner_radius=14
            )
        else:
            btn.configure(
                fg_color=s["card"], hover_color=s["border"],
                text_color=s["text"],
                border_width=0,
                corner_radius=14
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
        self.star_symbol.configure(text_color=s["border"])

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
        self.card_hint.configure(fg_color=s["card"])
        self.apply_glow(self.card_ctrl, True)
        self.apply_glow(self.card_hint, True)
        self.rec_title.configure(text_color=s["text"])
        self.hint_title.configure(text_color=s["text"])
        self.hint_text.configure(text_color=s["muted"])

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

    # ----------------- localization -----------------

    def apply_texts(self):
        self.title(self.i18n.t("app_title"))
        self.lbl_brand.configure(text=self.i18n.t("app_title"))
        self.btn_record.configure(text=self.i18n.t("nav_record"))
        self.btn_library.configure(text=self.i18n.t("nav_library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings"))
        self.lbl_style.configure(text=self.i18n.t("style"))
        self.lbl_mode.configure(text=self.i18n.t("theme"))
        self.lbl_lang.configure(text=self.i18n.t("language"))
        self.lbl_glow.configure(text=self.i18n.t("glow"))
        self.star_symbol.configure(text=self.i18n.t("star"))

        if self._active_page == "record":
            self.h_title.configure(text=self.i18n.t("page_record"))
        elif self._active_page == "library":
            self.h_title.configure(text=self.i18n.t("page_library"))
        else:
            self.h_title.configure(text=self.i18n.t("page_settings"))

        # record page
        self.rec_title.configure(text=self.i18n.t("rec_controls"))
        self.btn_start.configure(text=self.i18n.t("rec_start"))
        self.btn_stop.configure(text=self.i18n.t("rec_stop"))
        self.btn_play.configure(text=self.i18n.t("rec_play_loaded"))
        self.btn_stopplay.configure(text=self.i18n.t("rec_stop_play"))
        self.save_label.configure(text=self.i18n.t("rec_save_label"))
        self.btn_save.configure(text=self.i18n.t("rec_save_btn"))
        self.hint_title.configure(text=self.i18n.t("hotkeys_title"))
        self.hint_text.configure(text=self.i18n.t("hint_defaults") + "\n\n" + self.i18n.t("hint_admin"))
        self.log_title.configure(text=self.i18n.t("log_title"))
        self.btn_clear_log.configure(text=self.i18n.t("log_clear"))

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
        self.btn_apply_hotkeys.configure(text=self.i18n.t("hk_apply"))

        self.set_labels[0].configure(text=self.i18n.t("repeat"))
        self.set_labels[1].configure(text=self.i18n.t("loop"))
        self.set_labels[2].configure(text=self.i18n.t("speed"))
        self.set_labels[3].configure(text=self.i18n.t("delay"))

        self.hk_title.configure(text=self.i18n.t("base_hotkeys"))
        self.hk_labels[0].configure(text=self.i18n.t("hk_rec"))
        self.hk_labels[1].configure(text=self.i18n.t("hk_stoprec"))
        self.hk_labels[2].configure(text=self.i18n.t("hk_play"))
        self.hk_labels[3].configure(text=self.i18n.t("hk_stop"))

        self.refresh_binds_box()
        self.refresh_library()
        self.preview_selected()

    # ----------------- navigation -----------------

    def show_page(self, which: str, restyle_only: bool = False):
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

        if not restyle_only:
            self.apply_texts()
        self.apply_style()

    # =================================================
    # Record page
    # =================================================

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

        self.card_hint = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_hint.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=(16, 10))

        self.hint_title = ctk.CTkLabel(self.card_hint, text="Hotkeys", font=ctk.CTkFont(size=16, weight="bold"))
        self.hint_title.pack(anchor="w", padx=16, pady=(16, 8))

        self.hint_text = ctk.CTkLabel(self.card_hint, text="", justify="left", wraplength=420)
        self.hint_text.pack(anchor="w", padx=16, pady=(0, 16))

        self.log_title = ctk.CTkLabel(self.page_record, text="Log", font=ctk.CTkFont(size=14, weight="bold"))
        self.log_title.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 6))

        self.log_box = ctk.CTkTextbox(self.page_record, height=220, corner_radius=18)
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 10))

        self.btn_clear_log = ctk.CTkButton(self.page_record, text="Clear", command=self.clear_log_ui)
        self.btn_clear_log.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

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
        self.persist_settings()
        self.logger.info(f"{self.i18n.t('saved')}: {name} (events: {len(events)})")
        self.refresh_library()
        self.show_page("library")

    # =================================================
    # Library page
    # =================================================

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

        self.macro_buttons: Dict[str, ctk.CTkButton] = {}
        self.selected_macro: Optional[str] = None

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

        # right panel
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
        s = style_get(self.current_style)
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
            empty = ctk.CTkLabel(self.macros_scroll, text=self.i18n.t("empty"), text_color=s["muted"])
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
        s = style_get(self.current_style)
        for name, btn in self.macro_buttons.items():
            if name == self.selected_macro:
                btn.configure(fg_color=s["panel"], hover_color=s["border"], text_color=s["text"], border_width=2, border_color=s["accent"])
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
        st = item.get("settings", {}) if isinstance(item.get("settings", {}), dict) else {}
        meta = f"Created: {created_str} | Events: {count} | repeat={st.get('repeat',1)} loop={st.get('loop_seconds',0)} speed={st.get('speed',1.0)}"
        if self.i18n.lang == "ru":
            meta = f"Создан: {created_str} | Событий: {count} | repeat={st.get('repeat',1)} loop={st.get('loop_seconds',0)} speed={st.get('speed',1.0)}"

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
        self.engine.events = [Event(**e) for e in item.get("events", []) if isinstance(e, dict)]
        self.apply_settings(item.get("settings", {}))
        self.logger.info(f"{self.i18n.t('loaded')}: {name} (events: {len(self.engine.events)})")
        self.show_page("record")

    def play_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", []) if isinstance(e, dict)]
        self.apply_settings(item.get("settings", {}))
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
        self.logger.info(f"{self.i18n.t('deleted')}: {name}")
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

        ctk.CTkLabel(frm, text=self.i18n.t("btn_rename"), font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
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
                messagebox.showerror(self.i18n.t("app_title"), "Name exists.")
                return
            self.logger.info(f"{self.i18n.t('renamed')}: {old} -> {new}")
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

        ctk.CTkLabel(frm, text=f"{self.i18n.t('btn_clone')}: {src}", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
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
                messagebox.showerror(self.i18n.t("app_title"), "Failed (name exists?)")
                return
            self.logger.info(f"{self.i18n.t('cloned')}: {src} -> {dst}")
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

        path = filedialog.asksaveasfilename(
            title=self.i18n.t("btn_export"),
            defaultextension=".json",
            initialfile=f"{name}.json",
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
            self.logger.info(f"{self.i18n.t('exported')}: {name} -> {path}")
        except Exception as e:
            self.logger.error(f"Export error: {e}")
            self.logger.error(traceback.format_exc())
            messagebox.showerror(self.i18n.t("app_title"), f"Error: {e}")

    def import_macro(self):
        path = filedialog.askopenfilename(
            title=self.i18n.t("btn_import"),
            filetypes=[("JSON", "*.json")]
        )
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
            self.logger.info(f"{self.i18n.t('imported')}: {name} (events: {len(ev_objs)})")
            self.selected_macro = name
            self.refresh_library()

        except Exception as e:
            self.logger.error(f"Import error: {e}")
            self.logger.error(traceback.format_exc())
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
            if not messagebox.askyesno(self.i18n.t("app_title"), f"{hk} already bound to '{binds[hk]}'. Override?"):
                return

        self.db.set_bind(hk, name)
        self.logger.info(f"Bind: {hk} -> {name}")
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    def unbind_selected(self):
        hk_raw = self.bind_var.get()
        hk = normalize_hotkey(hk_raw)
        if not hk:
            messagebox.showerror(self.i18n.t("app_title"), self.i18n.t("invalid_hotkey"))
            return
        self.db.remove_bind(hk)
        self.logger.info(f"Unbound: {hk}")
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    # =================================================
    # Settings page
    # =================================================

    def build_settings_page(self):
        self.page_settings.grid_columnconfigure(0, weight=1)
        self.page_settings.grid_rowconfigure(0, weight=1)

        self.set_wrap = ctk.CTkFrame(self.page_settings, corner_radius=18)
        self.set_wrap.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.set_wrap.grid_columnconfigure(0, weight=1)

        self.set_title = ctk.CTkLabel(self.set_wrap, text=self.i18n.t("settings_playback"), font=ctk.CTkFont(size=18, weight="bold"))
        self.set_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self.set_labels: List[ctk.CTkLabel] = []
        self.set_entries: List[ctk.CTkEntry] = []

        def add_row(r: int, label_text: str, var: ctk.StringVar, placeholder: str):
            row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
            row.grid(row=r, column=0, padx=16, pady=8, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            lab = ctk.CTkLabel(row, text=label_text, width=190, anchor="w")
            lab.grid(row=0, column=0, sticky="w")

            ent = ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder)
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))

            self.set_labels.append(lab)
            self.set_entries.append(ent)

        add_row(1, self.i18n.t("repeat"), self.repeat_var, "e.g. 5")
        add_row(2, self.i18n.t("loop"), self.loop_var, "e.g. 7200")
        add_row(3, self.i18n.t("speed"), self.speed_var, "0.5 / 1.0 / 2.0")
        add_row(4, self.i18n.t("delay"), self.delay_var, "e.g. 3")

        self.set_hint = ctk.CTkLabel(self.set_wrap, text="If Loop > 0, Repeat is ignored.", anchor="w")
        self.set_hint.grid(row=5, column=0, padx=16, pady=(4, 12), sticky="w")

        # base hotkeys section
        self.hk_title = ctk.CTkLabel(self.set_wrap, text=self.i18n.t("base_hotkeys"), font=ctk.CTkFont(weight="bold"))
        self.hk_title.grid(row=6, column=0, padx=16, pady=(6, 6), sticky="w")

        self.hk_labels: List[ctk.CTkLabel] = []
        self.hk_entries: List[ctk.CTkEntry] = []

        def hk_row(r: int, label: str, var: ctk.StringVar):
            row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
            row.grid(row=r, column=0, padx=16, pady=6, sticky="ew")
            row.grid_columnconfigure(1, weight=1)
            lab = ctk.CTkLabel(row, text=label, width=190, anchor="w")
            lab.grid(row=0, column=0, sticky="w")
            ent = ctk.CTkEntry(row, textvariable=var, placeholder_text="e.g. Ctrl+Alt+1 or F6")
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))
            self.hk_labels.append(lab)
            self.hk_entries.append(ent)

        hk_row(7, self.i18n.t("hk_rec"), self.hk_rec_var)
        hk_row(8, self.i18n.t("hk_stoprec"), self.hk_stoprec_var)
        hk_row(9, self.i18n.t("hk_play"), self.hk_play_var)
        hk_row(10, self.i18n.t("hk_stop"), self.hk_stop_var)

        btns = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        btns.grid(row=11, column=0, padx=16, pady=(12, 16), sticky="ew")

        self.btn_apply = ctk.CTkButton(btns, text=self.i18n.t("apply"), command=self.apply_settings_to_engine)
        self.btn_apply.pack(side="left", padx=6)

        self.btn_reset = ctk.CTkButton(btns, text=self.i18n.t("reset"), command=self.reset_settings)
        self.btn_reset.pack(side="left", padx=6)

        self.btn_apply_hotkeys = ctk.CTkButton(btns, text=self.i18n.t("hk_apply"), command=self.apply_hotkeys_from_ui)
        self.btn_apply_hotkeys.pack(side="left", padx=6)

    def reset_settings(self):
        self.repeat_var.set("1")
        self.loop_var.set("0")
        self.speed_var.set("1.0")
        self.delay_var.set("0")
        self.persist_settings()
        self.logger.info("Settings reset.")

    def apply_settings_to_engine(self):
        # Engine reads settings on play; here we just validate + persist
        s = self.current_play_settings()
        self.repeat_var.set(str(s["repeat"]))
        self.loop_var.set(str(s["loop_seconds"]))
        self.speed_var.set(str(s["speed"]))
        self.delay_var.set(str(s["start_delay"]))
        self.persist_settings()
        self.logger.info(f"Applied: repeat={s['repeat']} loop={s['loop_seconds']} speed={s['speed']} delay={s['start_delay']}")

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
        self.logger.info("Base hotkeys updated.")

    # =================================================
    # Hotkeys
    # =================================================

    def rebuild_hotkeys(self):
        def hk_norm(raw: str, fallback: str) -> str:
            v = normalize_hotkey(raw)
            fb = normalize_hotkey(fallback)
            return v if v else (fb if fb else "<f6>")

        base: Dict[str, Callable[[], None]] = {
            hk_norm(self.hk_rec_var.get(), "Ctrl+Alt+1"): self.engine.start_recording,
            hk_norm(self.hk_stoprec_var.get(), "Ctrl+Alt+2"): self.engine.stop_recording,
            hk_norm(self.hk_play_var.get(), "Ctrl+Alt+3"): self.play_from_ui,
            hk_norm(self.hk_stop_var.get(), "Ctrl+Alt+4"): self.engine.stop_playing,
        }

        binds = self.db.binds()
        for hk, macro_name in binds.items():
            if hk in base:
                self.logger.warn(f"Bind conflicts with base hotkey: {hk} (skipped)")
                continue

            def make_play(name=macro_name):
                def _f():
                    item = self.db.get(name)
                    if not item:
                        self.logger.warn(f"[bind] macro not found: {name}")
                        return
                    self.engine.events = [Event(**e) for e in item.get("events", []) if isinstance(e, dict)]
                    self.apply_settings(item.get("settings", {}))
                    s = self.current_play_settings()
                    self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])
                    self.logger.info(f"[bind] play: {name}")
                return _f

            base[hk] = make_play()

        self.hk.set(base)

# =========================================================
# Main
# =========================================================

def main():
    try:
        app = SaonixApp()
        app.mainloop()
    except Exception as e:
        try:
            with open(CRASH_FILE, "w", encoding="utf-8") as f:
                f.write(str(e) + "\n\n" + traceback.format_exc())
        except Exception:
            pass
        print("Error. See:", CRASH_FILE)
        raise

if __name__ == "__main__":
    main()
