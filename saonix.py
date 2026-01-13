# saonix.py
# Saonix Macro Recorder (CustomTkinter + pynput) — fixed single-file build
# Fixes you asked for:
# 1) GitHub icon: downloads once, cached on disk, no endless re-download; safe fallback if offline.
# 2) Languages: stable switch (RU/EN + auto), all UI texts refresh correctly.
# 3) Page switching: NO animations; no “дерганое” переключение.
# 4) Thread-safe logging (no Tkinter calls from background threads).
#
# Requires: customtkinter, pynput
# Optional: none (uses urllib for icon)

import os
import json
import time
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


# =========================================================
# Paths / Files
# =========================================================

APP_NAME = "Saonix"

def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path

def get_root_dir() -> str:
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    root = os.path.join(programdata, APP_NAME)
    try:
        ensure_dir(root)
        test = os.path.join(root, "_rw_test.tmp")
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
LOG_FILE = os.path.join(DIR_LOGS, "app.log")
CRASH_FILE = os.path.join(DIR_LOGS, "crash_log.txt")

# Icon cache (download ONCE, then reuse)
ICON_URL = "https://raw.githubusercontent.com/<YOUR_USER>/<YOUR_REPO>/main/icon.png"
ICON_PATH = os.path.join(DIR_APP, "app_icon.png")
ICON_META = os.path.join(DIR_APP, "app_icon_meta.json")


# =========================================================
# Utilities
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
# Icon download/cache (NO endless downloads)
# =========================================================

def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _write_json(path: str, d: dict):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def ensure_icon_cached(logger: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """
    Downloads icon ONLY if:
      - file missing, or
      - server says it changed (ETag / Last-Modified)
    If URL placeholder not replaced, it will skip safely.
    """
    if "<YOUR_USER>" in ICON_URL or "<YOUR_REPO>" in ICON_URL:
        # user didn't set URL; just skip
        return ICON_PATH if os.path.exists(ICON_PATH) else None

    meta = _read_json(ICON_META)
    etag = meta.get("etag")
    last_mod = meta.get("last_modified")

    headers = {
        "User-Agent": "Saonix/1.0",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_mod:
        headers["If-Modified-Since"] = last_mod

    req = urllib.request.Request(ICON_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            # 200 -> new content; 304 -> handled by exception below in urllib? (No, urllib raises HTTPError for 304 sometimes)
            data = resp.read()
            if data:
                with open(ICON_PATH, "wb") as f:
                    f.write(data)
                new_etag = resp.headers.get("ETag")
                new_lm = resp.headers.get("Last-Modified")
                _write_json(ICON_META, {"etag": new_etag, "last_modified": new_lm, "saved_at": int(time.time())})
                if logger:
                    logger(f"[icon] updated: {ICON_PATH}")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            # Not modified -> keep existing file
            return ICON_PATH if os.path.exists(ICON_PATH) else None
        if logger:
            logger(f"[icon] download HTTPError {e.code}")
    except Exception as e:
        if logger:
            logger(f"[icon] download failed: {e}")

    return ICON_PATH if os.path.exists(ICON_PATH) else None


# =========================================================
# Logger (thread-safe for Tk)
# =========================================================

class Logger:
    def __init__(self, tk_after: Optional[Callable[[int, Callable], None]] = None,
                 ui_append: Optional[Callable[[str], None]] = None):
        self._lock = threading.Lock()
        self._after = tk_after
        self._ui_append = ui_append

    def _write_file(self, line: str):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _emit_ui(self, line: str):
        if not self._ui_append or not self._after:
            return
        def _do():
            try:
                self._ui_append(line + "\n")
            except Exception:
                pass
        self._after(0, _do)

    def _log(self, level: str, msg: str):
        line = f"[{ts()}] [{level}] {msg}"
        with self._lock:
            self._write_file(line)
        self._emit_ui(line)

    def info(self, msg: str): self._log("INFO", msg)
    def warn(self, msg: str): self._log("WARN", msg)
    def error(self, msg: str): self._log("ERROR", msg)


# =========================================================
# i18n (RU/EN + auto) — stable refresh
# =========================================================

def system_lang_guess() -> str:
    try:
        loc = pylocale.getdefaultlocale()[0] or ""
        loc = loc.replace("_", "-").lower()
        if loc.startswith("ru"):
            return "ru"
        return "en"
    except Exception:
        return "en"

class I18N:
    SUPPORTED = ["auto", "ru", "en"]

    EN = {
        "app_title": "Saonix",
        "nav_record": "● Record",
        "nav_library": "📚 Library",
        "nav_settings": "⚙ Settings",
        "theme": "Theme",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "language": "Language",
        "status_ready": "Ready",
        "status_recording": "● Recording…",
        "status_playing": "▶ Playing…",
        "page_record": "Record",
        "page_library": "Library",
        "page_settings": "Settings",
        "controls": "Controls",
        "rec_start": "● Start recording",
        "rec_stop": "■ Stop recording",
        "rec_play_loaded": "▶ Play (loaded)",
        "rec_stop_play": "⏹ Stop",
        "save_label": "Save to library:",
        "save_btn": "💾 Save",
        "log": "Log",
        "log_clear": "Clear log",
        "hint": "Hotkeys",
        "hint_text": "Default: Ctrl+Alt+1 record | Ctrl+Alt+2 stop rec | Ctrl+Alt+3 play loaded | Ctrl+Alt+4 stop\n\nIf your app runs as Admin, run Saonix as Admin too.",
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
        "warn_name": "Enter macro name.",
        "warn_noevents": "No events. Record first.",
        "q_overwrite": "Macro exists. Overwrite?",
        "warn_select": "Select a macro.",
        "q_delete": "Delete macro?",
        "invalid_hotkey": "Invalid hotkey. Example: F6 or Ctrl+Alt+F6",
        "empty": "(empty)",
        "binds_none": "(no binds)",
    }

    RU = {
        "app_title": "Saonix",
        "nav_record": "● Запись",
        "nav_library": "📚 Библиотека",
        "nav_settings": "⚙ Настройки",
        "theme": "Тема",
        "theme_dark": "Тёмная",
        "theme_light": "Светлая",
        "language": "Язык",
        "status_ready": "Готово",
        "status_recording": "● Запись…",
        "status_playing": "▶ Воспроизведение…",
        "page_record": "Запись",
        "page_library": "Библиотека",
        "page_settings": "Настройки",
        "controls": "Управление",
        "rec_start": "● Начать запись",
        "rec_stop": "■ Остановить запись",
        "rec_play_loaded": "▶ Воспроизвести (загруженный)",
        "rec_stop_play": "⏹ Стоп",
        "save_label": "Сохранить в библиотеку:",
        "save_btn": "💾 Сохранить",
        "log": "Лог",
        "log_clear": "Очистить лог",
        "hint": "Хоткеи",
        "hint_text": "По умолчанию: Ctrl+Alt+1 запись | Ctrl+Alt+2 стоп | Ctrl+Alt+3 пуск | Ctrl+Alt+4 стоп\n\nЕсли игра/прога запущена от Админа — запускай Saonix от Админа.",
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
        "reset": "Сброс",
        "base_hotkeys": "Базовые хоткеи",
        "hk_rec": "Старт записи",
        "hk_stoprec": "Стоп записи",
        "hk_play": "Пуск загруженного",
        "hk_stop": "Стоп воспроизведения",
        "hk_apply": "Применить хоткеи",
        "warn_name": "Введи имя макроса.",
        "warn_noevents": "Нет событий. Сначала запиши.",
        "q_overwrite": "Макрос уже есть. Перезаписать?",
        "warn_select": "Выбери макрос.",
        "q_delete": "Удалить макрос?",
        "invalid_hotkey": "Неверный хоткей. Пример: F6 или Ctrl+Alt+F6",
        "empty": "(пусто)",
        "binds_none": "(биндов нет)",
    }

    def __init__(self, lang: str):
        self.lang = "en"
        self.dict = dict(self.EN)
        self.set(lang)

    def set(self, lang: str):
        lang = (lang or "auto").strip().lower()
        if lang == "auto":
            lang = system_lang_guess()
        self.lang = "ru" if lang == "ru" else "en"
        self.dict = dict(self.RU if self.lang == "ru" else self.EN)

    def t(self, key: str) -> str:
        return self.dict.get(key, key)


# =========================================================
# Macro DB
# =========================================================

class MacroDB:
    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 1, "macros": {}, "binds": {}, "settings": {}}
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
# Hotkey parsing (pynput GlobalHotKeys format)
# =========================================================

def normalize_hotkey(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None
    t = t.replace("<", "").replace(">", "")

    # Single function key: F1..F24
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
        try: self._mouse_listener.stop()
        except Exception: pass
        try: self._kb_listener.stop()
        except Exception: pass

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

    # record handlers
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
        self._add("mouse", "click", {"x": int(x), "y": int(y), "button": btn_name, "pressed": bool(pressed)})

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

    # playback
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
            if self.recording or self.playing or not self.events:
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
                    end = time.time() + float(start_delay)
                    while time.time() < end and not self._stop_play.is_set():
                        time.sleep(0.01)

                if loop_seconds > 0:
                    started = time.time()
                    while not self._stop_play.is_set() and (time.time() - started) < loop_seconds:
                        play_once()
                else:
                    r = max(int(repeat), 1)
                    for _ in range(r):
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
# App (NO animations, stable switch)
# =========================================================

class SaonixApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.db = MacroDB(DB_FILE)
        saved = self.db.get_settings()

        # language
        self.lang_var = ctk.StringVar(value=str(saved.get("lang", "auto")))
        self.i18n = I18N(self.lang_var.get())

        # theme
        appearance = saved.get("appearance", "Dark")
        if appearance not in ("Dark", "Light"):
            appearance = "Dark"
        ctk.set_appearance_mode(appearance)

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

        # window
        self.title(self.i18n.t("app_title"))
        self.geometry("1180x720")
        self.minsize(1000, 640)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # icon (cached, no spam)
        self.log_box = None
        self.logger = Logger(self.after, self._append_log_ui)
        icon_path = ensure_icon_cached(lambda s: self.logger.info(s))
        if icon_path:
            try:
                self.iconphoto(False, ctk.CTkImage(light_image=None, dark_image=None))  # safe no-op for CTk
            except Exception:
                pass
            # Tk icon bitmap/photo works with .ico best; for .png use iconphoto with PhotoImage
            try:
                import tkinter as tk
                img = tk.PhotoImage(file=icon_path)
                self.iconphoto(True, img)
                self._icon_keepalive = img
                self.logger.info(f"[icon] loaded: {icon_path}")
            except Exception as e:
                self.logger.warn(f"[icon] cannot set window icon: {e}")

        # engine/hotkeys
        self.engine = MacroEngine(self.logger)
        self.hk = HotkeyManager(self.logger)

        # layout
        self._active_page = "record"
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=18)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=14, pady=14)
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.main = ctk.CTkFrame(self, corner_radius=18)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        # sidebar controls
        self.lbl_brand = ctk.CTkLabel(self.sidebar, text=self.i18n.t("app_title"), font=ctk.CTkFont(size=24, weight="bold"))
        self.lbl_brand.grid(row=0, column=0, padx=16, pady=(16, 10), sticky="w")

        self.btn_record = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_record"), command=lambda: self.show_page("record"))
        self.btn_library = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_library"), command=lambda: self.show_page("library"))
        self.btn_settings = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_settings"), command=lambda: self.show_page("settings"))
        self.btn_record.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        self.btn_library.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        self.btn_settings.grid(row=3, column=0, padx=16, pady=6, sticky="ew")

        self.lbl_theme = ctk.CTkLabel(self.sidebar, text=self.i18n.t("theme"), font=ctk.CTkFont(weight="bold"))
        self.lbl_theme.grid(row=4, column=0, padx=16, pady=(16, 4), sticky="w")
        self.theme_menu = ctk.CTkOptionMenu(self.sidebar, values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")], command=self.set_mode)
        self.theme_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))
        self.theme_menu.grid(row=5, column=0, padx=16, pady=6, sticky="ew")

        self.lbl_lang = ctk.CTkLabel(self.sidebar, text=self.i18n.t("language"), font=ctk.CTkFont(weight="bold"))
        self.lbl_lang.grid(row=6, column=0, padx=16, pady=(12, 4), sticky="w")
        self.lang_menu = ctk.CTkOptionMenu(self.sidebar, values=I18N.SUPPORTED, variable=self.lang_var, command=self.set_lang)
        self.lang_menu.grid(row=7, column=0, padx=16, pady=(0, 16), sticky="ew")

        # header
        self.header = ctk.CTkFrame(self.main, corner_radius=18, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        self.header.grid_columnconfigure(0, weight=1)

        self.h_title = ctk.CTkLabel(self.header, text=self.i18n.t("page_record"), font=ctk.CTkFont(size=18, weight="bold"))
        self.h_title.grid(row=0, column=0, padx=14, pady=12, sticky="w")

        self.status_var = ctk.StringVar(value=self.i18n.t("status_ready"))
        self.h_status = ctk.CTkLabel(self.header, textvariable=self.status_var)
        self.h_status.grid(row=0, column=1, padx=14, pady=12, sticky="e")

        # pages container
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

        # build pages (no animations anywhere)
        self._build_record_page()
        self._build_library_page()
        self._build_settings_page()

        self.show_page("record")
        self.rebuild_hotkeys()

        self.after(200, self._tick_status)
        self.logger.info("Started.")

    # ---------------- settings persistence ----------------

    def persist_settings(self):
        s = self.db.get_settings()
        s.update({
            "lang": self.lang_var.get(),
            "appearance": ctk.get_appearance_mode(),
            "repeat": safe_int(self.repeat_var.get(), 1),
            "loop_seconds": safe_int(self.loop_var.get(), 0),
            "speed": safe_float(self.speed_var.get(), 1.0),
            "start_delay": safe_float(self.delay_var.get(), 0.0),
            "hk_rec": self.hk_rec_var.get(),
            "hk_stoprec": self.hk_stoprec_var.get(),
            "hk_play": self.hk_play_var.get(),
            "hk_stop": self.hk_stop_var.get(),
        })
        self.db.set_settings(s)

    def current_play_settings(self) -> Dict[str, Any]:
        return {
            "repeat": clamp(safe_int(self.repeat_var.get(), 1), 1, 9999),
            "loop_seconds": clamp(safe_int(self.loop_var.get(), 0), 0, 24 * 3600),
            "speed": clamp(safe_float(self.speed_var.get(), 1.0), 0.05, 5.0),
            "start_delay": clamp(safe_float(self.delay_var.get(), 0.0), 0.0, 60.0),
        }

    # ---------------- UI helpers ----------------

    def _append_log_ui(self, text: str):
        if not self.log_box:
            return
        try:
            self.log_box.insert("end", text)
            self.log_box.see("end")
        except Exception:
            pass

    def _tick_status(self):
        if self.engine.recording:
            self.status_var.set(self.i18n.t("status_recording"))
        elif self.engine.playing:
            self.status_var.set(self.i18n.t("status_playing"))
        else:
            self.status_var.set(self.i18n.t("status_ready"))
        self.after(200, self._tick_status)

    def on_close(self):
        try:
            self.persist_settings()
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

    # ---------------- sidebar controls ----------------

    def set_mode(self, mode_text: str):
        if mode_text == self.i18n.t("theme_light"):
            ctk.set_appearance_mode("Light")
        else:
            ctk.set_appearance_mode("Dark")
        self.persist_settings()

    def set_lang(self, lang: str):
        self.i18n.set(lang)
        self.title(self.i18n.t("app_title"))
        # refresh menus text
        self.btn_record.configure(text=self.i18n.t("nav_record"))
        self.btn_library.configure(text=self.i18n.t("nav_library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings"))
        self.lbl_theme.configure(text=self.i18n.t("theme"))
        self.lbl_lang.configure(text=self.i18n.t("language"))
        self.theme_menu.configure(values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")])
        self.theme_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))

        # refresh page texts
        self._apply_texts_all()
        self.persist_settings()

    # ---------------- navigation (NO animation) ----------------

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
        self._apply_texts_all()

    # =========================================================
    # Record page
    # =========================================================

    def _build_record_page(self):
        self.page_record.grid_columnconfigure(0, weight=1)
        self.page_record.grid_columnconfigure(1, weight=1)
        self.page_record.grid_rowconfigure(2, weight=1)

        self.card_ctrl = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_ctrl.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=(16, 10))

        self.lbl_ctrl = ctk.CTkLabel(self.card_ctrl, text=self.i18n.t("controls"), font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_ctrl.pack(anchor="w", padx=16, pady=(16, 8))

        row1 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=6)
        self.btn_start = ctk.CTkButton(row1, text=self.i18n.t("rec_start"), command=self.engine.start_recording)
        self.btn_start.pack(side="left", padx=6)
        self.btn_stop = ctk.CTkButton(row1, text=self.i18n.t("rec_stop"), command=self.engine.stop_recording)
        self.btn_stop.pack(side="left", padx=6)

        row2 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=6)
        self.btn_play = ctk.CTkButton(row2, text=self.i18n.t("rec_play_loaded"), command=self._play_loaded_from_ui)
        self.btn_play.pack(side="left", padx=6)
        self.btn_stopplay = ctk.CTkButton(row2, text=self.i18n.t("rec_stop_play"), command=self.engine.stop_playing)
        self.btn_stopplay.pack(side="left", padx=6)

        self.save_label = ctk.CTkLabel(self.card_ctrl, text=self.i18n.t("save_label"))
        self.save_label.pack(anchor="w", padx=16, pady=(12, 4))
        self.save_name = ctk.StringVar(value="New macro")
        self.save_entry = ctk.CTkEntry(self.card_ctrl, textvariable=self.save_name)
        self.save_entry.pack(fill="x", padx=16, pady=6)
        self.btn_save = ctk.CTkButton(self.card_ctrl, text=self.i18n.t("save_btn"), command=self._save_current_macro)
        self.btn_save.pack(fill="x", padx=16, pady=(6, 16))

        self.card_hint = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_hint.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=(16, 10))

        self.lbl_hint = ctk.CTkLabel(self.card_hint, text=self.i18n.t("hint"), font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_hint.pack(anchor="w", padx=16, pady=(16, 8))
        self.txt_hint = ctk.CTkLabel(self.card_hint, text=self.i18n.t("hint_text"), justify="left", wraplength=420)
        self.txt_hint.pack(anchor="w", padx=16, pady=(0, 16))

        self.lbl_log = ctk.CTkLabel(self.page_record, text=self.i18n.t("log"), font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_log.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 6))

        self.log_box = ctk.CTkTextbox(self.page_record, height=220, corner_radius=18)
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 10))

        self.btn_clear_log = ctk.CTkButton(self.page_record, text=self.i18n.t("log_clear"), command=self._clear_log_ui)
        self.btn_clear_log.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

    def _clear_log_ui(self):
        try:
            self.log_box.delete("1.0", "end")
        except Exception:
            pass

    def _play_loaded_from_ui(self):
        s = self.current_play_settings()
        self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])

    def _save_current_macro(self):
        name = self.save_name.get().strip()
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_name"))
            return
        if not self.engine.events:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_noevents"))
            return
        if self.db.exists(name):
            if not messagebox.askyesno(self.i18n.t("app_title"), self.i18n.t("q_overwrite")):
                return

        events = [asdict(e) for e in self.engine.events]
        settings = self.current_play_settings()
        self.db.put(name, events, settings)
        self.persist_settings()
        self.logger.info(f"Saved: {name} (events: {len(events)})")
        self._refresh_library()
        self.show_page("library")

    # =========================================================
    # Library page
    # =========================================================

    def _build_library_page(self):
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
        self.search_entry = ctk.CTkEntry(self.lib_left, textvariable=self.search_var, placeholder_text=self.i18n.t("search_ph"))
        self.search_entry.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda e: self._refresh_library())

        self.macros_scroll = ctk.CTkScrollableFrame(self.lib_left, corner_radius=14)
        self.macros_scroll.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        self.macro_buttons: Dict[str, ctk.CTkButton] = {}
        self.selected_macro: Optional[str] = None

        actions = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)

        self.btn_load = ctk.CTkButton(actions, text=self.i18n.t("btn_load"), command=self._load_selected)
        self.btn_load.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.btn_delete = ctk.CTkButton(actions, text=self.i18n.t("btn_delete"), command=self._delete_selected)
        self.btn_delete.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions2 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions2.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions2.grid_columnconfigure((0, 1), weight=1)

        self.btn_rename = ctk.CTkButton(actions2, text=self.i18n.t("btn_rename"), command=self._rename_selected)
        self.btn_rename.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.btn_clone = ctk.CTkButton(actions2, text=self.i18n.t("btn_clone"), command=self._clone_selected)
        self.btn_clone.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions3 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions3.grid(row=6, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions3.grid_columnconfigure((0, 1), weight=1)

        self.btn_export = ctk.CTkButton(actions3, text=self.i18n.t("btn_export"), command=self._export_selected)
        self.btn_export.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.btn_import = ctk.CTkButton(actions3, text=self.i18n.t("btn_import"), command=self._import_macro)
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

        self.bind_label = ctk.CTkLabel(bind_row, text=self.i18n.t("bind"), width=90, anchor="w")
        self.bind_label.grid(row=0, column=0, sticky="w")

        self.bind_var = ctk.StringVar(value="F6")
        self.bind_entry = ctk.CTkEntry(bind_row, textvariable=self.bind_var, placeholder_text=self.i18n.t("bind_ph"))
        self.bind_entry.grid(row=0, column=1, sticky="ew", padx=(10, 10))

        self.btn_bind = ctk.CTkButton(bind_row, text=self.i18n.t("bind_set"), width=110, command=self._bind_selected)
        self.btn_bind.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.btn_unbind = ctk.CTkButton(bind_row, text=self.i18n.t("bind_remove"), width=90, command=self._unbind_selected)
        self.btn_unbind.grid(row=0, column=3, sticky="e")

        self.binds_box = ctk.CTkTextbox(self.lib_right, height=120, corner_radius=14)
        self.binds_box.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        self.preview_box = ctk.CTkTextbox(self.lib_right, corner_radius=14)
        self.preview_box.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="nsew")

        playbar = ctk.CTkFrame(self.lib_right, fg_color="transparent")
        playbar.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        playbar.grid_columnconfigure((0, 1), weight=1)

        self.btn_play_sel = ctk.CTkButton(playbar, text=self.i18n.t("play_selected"), command=self._play_selected)
        self.btn_play_sel.grid(row=0, column=0, padx=6, sticky="ew")
        self.btn_stop_sel = ctk.CTkButton(playbar, text=self.i18n.t("rec_stop_play"), command=self.engine.stop_playing)
        self.btn_stop_sel.grid(row=0, column=1, padx=6, sticky="ew")

        self._refresh_library()
        self._refresh_binds_box()

    def _refresh_binds_box(self):
        self.binds_box.delete("1.0", "end")
        binds = self.db.binds()
        if not binds:
            self.binds_box.insert("end", self.i18n.t("binds_none") + "\n")
            return
        for hk, mn in sorted(binds.items(), key=lambda x: x[0]):
            self.binds_box.insert("end", f"{hk}  ->  {mn}\n")

    def _refresh_library(self):
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
            self._preview_clear()
            return

        if self.selected_macro not in names:
            self.selected_macro = names[0]

        for n in names:
            btn = ctk.CTkButton(self.macros_scroll, text=n, anchor="w", corner_radius=12, command=lambda name=n: self._select_macro(name))
            btn.pack(fill="x", padx=6, pady=6)
            self.macro_buttons[n] = btn

        self._preview_selected()

    def _select_macro(self, name: str):
        self.selected_macro = name
        self._preview_selected()

    def _preview_clear(self):
        self.preview_title.configure(text="—")
        self.preview_meta.configure(text="—")
        self.preview_box.delete("1.0", "end")

    def _preview_selected(self):
        name = self.selected_macro
        if not name:
            self._preview_clear()
            return
        item = self.db.get(name)
        if not item:
            self._preview_clear()
            return

        created = item.get("created", 0)
        created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created)) if created else "—"
        count = len(item.get("events", []))
        st = item.get("settings", {}) if isinstance(item.get("settings", {}), dict) else {}
        meta = f"{created_str} | events={count} | repeat={st.get('repeat',1)} loop={st.get('loop_seconds',0)} speed={st.get('speed',1.0)}"
        self.preview_title.configure(text=name)
        self.preview_meta.configure(text=meta)
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("end", json.dumps(st, ensure_ascii=False, indent=2))

    def _load_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_select"))
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", []) if isinstance(e, dict)]
        st = item.get("settings", {}) if isinstance(item.get("settings", {}), dict) else {}
        self._apply_settings_to_ui(st)
        self.logger.info(f"Loaded: {name} (events: {len(self.engine.events)})")
        self.show_page("record")

    def _play_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_select"))
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", []) if isinstance(e, dict)]
        st = item.get("settings", {}) if isinstance(item.get("settings", {}), dict) else {}
        self._apply_settings_to_ui(st)
        self._play_loaded_from_ui()

    def _delete_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_select"))
            return
        if not messagebox.askyesno(self.i18n.t("app_title"), f"{self.i18n.t('q_delete')} '{name}'?"):
            return
        self.db.delete(name)
        self.selected_macro = None
        self._refresh_library()
        self._refresh_binds_box()
        self.rebuild_hotkeys()

    def _rename_selected(self):
        old = self.selected_macro
        if not old:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_select"))
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
            dialog.destroy()
            self.selected_macro = new
            self._refresh_library()
            self._refresh_binds_box()
            self.rebuild_hotkeys()

        btns = ctk.CTkFrame(frm, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(10, 12))
        ctk.CTkButton(btns, text="OK", command=do).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)

    def _clone_selected(self):
        src = self.selected_macro
        if not src:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_select"))
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
            dialog.destroy()
            self.selected_macro = dst
            self._refresh_library()

        btns = ctk.CTkFrame(frm, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(10, 12))
        ctk.CTkButton(btns, text="OK", command=do).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)

    def _export_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_select"))
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

        payload = {
            "format": "saonix_macro_v1",
            "name": name,
            "created": item.get("created", int(time.time())),
            "settings": item.get("settings", {}),
            "events": item.get("events", []),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Exported: {name} -> {path}")
        except Exception as e:
            messagebox.showerror(self.i18n.t("app_title"), f"Error: {e}")

    def _import_macro(self):
        path = filedialog.askopenfilename(title=self.i18n.t("btn_import"), filetypes=[("JSON", "*.json")])
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict) or "events" not in payload:
                raise ValueError("Invalid file")

            name = str(payload.get("name", os.path.splitext(os.path.basename(path))[0])).strip() or "Imported"
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
            self.selected_macro = name
            self._refresh_library()
            self.logger.info(f"Imported: {name} (events: {len(ev_objs)})")

        except Exception as e:
            messagebox.showerror(self.i18n.t("app_title"), f"Error: {e}")

    def _bind_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("warn_select"))
            return
        hk = normalize_hotkey(self.bind_var.get())
        if not hk:
            messagebox.showerror(self.i18n.t("app_title"), self.i18n.t("invalid_hotkey"))
            return
        self.db.set_bind(hk, name)
        self._refresh_binds_box()
        self.rebuild_hotkeys()

    def _unbind_selected(self):
        hk = normalize_hotkey(self.bind_var.get())
        if not hk:
            messagebox.showerror(self.i18n.t("app_title"), self.i18n.t("invalid_hotkey"))
            return
        self.db.remove_bind(hk)
        self._refresh_binds_box()
        self.rebuild_hotkeys()

    def _apply_settings_to_ui(self, st: Dict[str, Any]):
        if not isinstance(st, dict):
            return
        if "repeat" in st: self.repeat_var.set(str(st["repeat"]))
        if "loop_seconds" in st: self.loop_var.set(str(st["loop_seconds"]))
        if "speed" in st: self.speed_var.set(str(st["speed"]))
        if "start_delay" in st: self.delay_var.set(str(st["start_delay"]))

    # =========================================================
    # Settings page
    # =========================================================

    def _build_settings_page(self):
        self.page_settings.grid_columnconfigure(0, weight=1)
        self.page_settings.grid_rowconfigure(0, weight=1)

        wrap = ctk.CTkFrame(self.page_settings, corner_radius=18)
        wrap.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        wrap.grid_columnconfigure(0, weight=1)

        self.set_title = ctk.CTkLabel(wrap, text=self.i18n.t("settings_playback"), font=ctk.CTkFont(size=18, weight="bold"))
        self.set_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        def row(r: int, label: str, var: ctk.StringVar, ph: str):
            fr = ctk.CTkFrame(wrap, fg_color="transparent")
            fr.grid(row=r, column=0, padx=16, pady=8, sticky="ew")
            fr.grid_columnconfigure(1, weight=1)
            lab = ctk.CTkLabel(fr, text=label, width=200, anchor="w")
            lab.grid(row=0, column=0, sticky="w")
            ent = ctk.CTkEntry(fr, textvariable=var, placeholder_text=ph)
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))
            return lab, ent

        self.lab_repeat, _ = row(1, self.i18n.t("repeat"), self.repeat_var, "e.g. 5")
        self.lab_loop, _ = row(2, self.i18n.t("loop"), self.loop_var, "e.g. 7200")
        self.lab_speed, _ = row(3, self.i18n.t("speed"), self.speed_var, "0.5 / 1.0 / 2.0")
        self.lab_delay, _ = row(4, self.i18n.t("delay"), self.delay_var, "e.g. 3")

        self.hk_title = ctk.CTkLabel(wrap, text=self.i18n.t("base_hotkeys"), font=ctk.CTkFont(weight="bold"))
        self.hk_title.grid(row=5, column=0, padx=16, pady=(14, 6), sticky="w")

        def hkrow(r: int, label: str, var: ctk.StringVar):
            fr = ctk.CTkFrame(wrap, fg_color="transparent")
            fr.grid(row=r, column=0, padx=16, pady=6, sticky="ew")
            fr.grid_columnconfigure(1, weight=1)
            lab = ctk.CTkLabel(fr, text=label, width=200, anchor="w")
            lab.grid(row=0, column=0, sticky="w")
            ent = ctk.CTkEntry(fr, textvariable=var, placeholder_text="e.g. Ctrl+Alt+1 or F6")
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))
            return lab, ent

        self.lab_hk_rec, _ = hkrow(6, self.i18n.t("hk_rec"), self.hk_rec_var)
        self.lab_hk_stoprec, _ = hkrow(7, self.i18n.t("hk_stoprec"), self.hk_stoprec_var)
        self.lab_hk_play, _ = hkrow(8, self.i18n.t("hk_play"), self.hk_play_var)
        self.lab_hk_stop, _ = hkrow(9, self.i18n.t("hk_stop"), self.hk_stop_var)

        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.grid(row=10, column=0, padx=16, pady=(14, 16), sticky="w")

        self.btn_apply = ctk.CTkButton(btns, text=self.i18n.t("apply"), command=self._apply_settings)
        self.btn_apply.pack(side="left", padx=6)
        self.btn_reset = ctk.CTkButton(btns, text=self.i18n.t("reset"), command=self._reset_settings)
        self.btn_reset.pack(side="left", padx=6)
        self.btn_apply_hotkeys = ctk.CTkButton(btns, text=self.i18n.t("hk_apply"), command=self._apply_hotkeys)
        self.btn_apply_hotkeys.pack(side="left", padx=6)

    def _apply_settings(self):
        s = self.current_play_settings()
        self.repeat_var.set(str(s["repeat"]))
        self.loop_var.set(str(s["loop_seconds"]))
        self.speed_var.set(str(s["speed"]))
        self.delay_var.set(str(s["start_delay"]))
        self.persist_settings()

    def _reset_settings(self):
        self.repeat_var.set("1")
        self.loop_var.set("0")
        self.speed_var.set("1.0")
        self.delay_var.set("0")
        self.persist_settings()

    def _apply_hotkeys(self):
        vals = [self.hk_rec_var.get(), self.hk_stoprec_var.get(), self.hk_play_var.get(), self.hk_stop_var.get()]
        norms = [normalize_hotkey(v) for v in vals]
        if not all(norms):
            messagebox.showerror(self.i18n.t("app_title"), self.i18n.t("invalid_hotkey"))
            return
        self.persist_settings()
        self.rebuild_hotkeys()

    # =========================================================
    # Hotkeys
    # =========================================================

    def rebuild_hotkeys(self):
        def hk_norm(raw: str, fallback: str) -> str:
            v = normalize_hotkey(raw)
            fb = normalize_hotkey(fallback)
            return v if v else (fb if fb else "<f6>")

        mapping: Dict[str, Callable[[], None]] = {
            hk_norm(self.hk_rec_var.get(), "Ctrl+Alt+1"): self.engine.start_recording,
            hk_norm(self.hk_stoprec_var.get(), "Ctrl+Alt+2"): self.engine.stop_recording,
            hk_norm(self.hk_play_var.get(), "Ctrl+Alt+3"): self._play_loaded_from_ui,
            hk_norm(self.hk_stop_var.get(), "Ctrl+Alt+4"): self.engine.stop_playing,
        }

        binds = self.db.binds()
        for hk, macro_name in binds.items():
            if hk in mapping:
                continue
            def make_play(name=macro_name):
                def _f():
                    item = self.db.get(name)
                    if not item:
                        return
                    self.engine.events = [Event(**e) for e in item.get("events", []) if isinstance(e, dict)]
                    st = item.get("settings", {}) if isinstance(item.get("settings", {}), dict) else {}
                    self._apply_settings_to_ui(st)
                    self._play_loaded_from_ui()
                    self.logger.info(f"[bind] play: {name}")
                return _f
            mapping[hk] = make_play()

        self.hk.set(mapping)

    # ---------------- refresh texts ----------------

    def _apply_texts_all(self):
        # sidebar
        self.lbl_brand.configure(text=self.i18n.t("app_title"))
        self.btn_record.configure(text=self.i18n.t("nav_record"))
        self.btn_library.configure(text=self.i18n.t("nav_library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings"))
        self.lbl_theme.configure(text=self.i18n.t("theme"))
        self.lbl_lang.configure(text=self.i18n.t("language"))

        # header title based on page
        if self._active_page == "record":
            self.h_title.configure(text=self.i18n.t("page_record"))
        elif self._active_page == "library":
            self.h_title.configure(text=self.i18n.t("page_library"))
        else:
            self.h_title.configure(text=self.i18n.t("page_settings"))

        # record page
        self.lbl_ctrl.configure(text=self.i18n.t("controls"))
        self.btn_start.configure(text=self.i18n.t("rec_start"))
        self.btn_stop.configure(text=self.i18n.t("rec_stop"))
        self.btn_play.configure(text=self.i18n.t("rec_play_loaded"))
        self.btn_stopplay.configure(text=self.i18n.t("rec_stop_play"))
        self.save_label.configure(text=self.i18n.t("save_label"))
        self.btn_save.configure(text=self.i18n.t("save_btn"))
        self.lbl_hint.configure(text=self.i18n.t("hint"))
        self.txt_hint.configure(text=self.i18n.t("hint_text"))
        self.lbl_log.configure(text=self.i18n.t("log"))
        self.btn_clear_log.configure(text=self.i18n.t("log_clear"))

        # library page
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
        self._refresh_binds_box()

        # settings page
        self.set_title.configure(text=self.i18n.t("settings_playback"))
        self.lab_repeat.configure(text=self.i18n.t("repeat"))
        self.lab_loop.configure(text=self.i18n.t("loop"))
        self.lab_speed.configure(text=self.i18n.t("speed"))
        self.lab_delay.configure(text=self.i18n.t("delay"))
        self.hk_title.configure(text=self.i18n.t("base_hotkeys"))
        self.lab_hk_rec.configure(text=self.i18n.t("hk_rec"))
        self.lab_hk_stoprec.configure(text=self.i18n.t("hk_stoprec"))
        self.lab_hk_play.configure(text=self.i18n.t("hk_play"))
        self.lab_hk_stop.configure(text=self.i18n.t("hk_stop"))
        self.btn_apply.configure(text=self.i18n.t("apply"))
        self.btn_reset.configure(text=self.i18n.t("reset"))
        self.btn_apply_hotkeys.configure(text=self.i18n.t("hk_apply"))

        # theme menu values (language-dependent)
        self.theme_menu.configure(values=[self.i18n.t("theme_dark"), self.i18n.t("theme_light")])
        self.theme_menu.set(self.i18n.t("theme_dark") if ctk.get_appearance_mode() == "Dark" else self.i18n.t("theme_light"))


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
        raise

if __name__ == "__main__":
    main()
