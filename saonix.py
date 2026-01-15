# saonix.py
# Single-file app (CustomTkinter + pynput) with:
# - Splash loader (no console dependency), progress UI
# - GitHub version check (no re-download if same; uses ETag cache when possible)
# - Embedded multilingual UI core: EN/RU/JA/PL/DE/ZH (+ auto)
# - Contact/support text: Discord Relberof
#
# Notes for "no console":
# - Run as pythonw.exe or build with PyInstaller: --noconsole / --windowed

import os
import sys
import json
import time
import threading
import traceback
import ctypes
import locale as pylocale
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Callable

import customtkinter as ctk
from tkinter import messagebox, filedialog

from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, KeyCode, Controller as KeyboardController

# -----------------------------
# App constants / GitHub
# -----------------------------
APP_NAME = "Saonix"

# Bump this when you publish a new build on GitHub
APP_VERSION = "1.0.0"

# You can keep version.txt and icon.png in repo. Loader checks version first.
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/relberof/desktop-tutorial/69cec69713c6f91563ba3c2c87c6215042e67ee5/version.txt"
GITHUB_ICON_URL = "https://raw.githubusercontent.com/relberof/desktop-tutorial/69cec69713c6f91563ba3c2c87c6215042e67ee5/icon.png"

SUPPORT_DISCORD = "Relberof"


# -----------------------------
# Paths
# -----------------------------
def ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def get_root_dir() -> str:
    base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    root = os.path.join(base, APP_NAME)
    try:
        ensure_dir(root)
        t = os.path.join(root, "_rw.tmp")
        with open(t, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(t)
        return root
    except Exception:
        here = os.path.abspath(os.path.dirname(__file__)) if "__file__" in globals() else os.getcwd()
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

CACHE_FILE = os.path.join(DIR_DATA, "net_cache.json")
ICON_PNG = os.path.join(DIR_APP, "icon.png")


# -----------------------------
# Utils
# -----------------------------
def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def safe_int(s: str, d: int) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return d


def safe_float(s: str, d: float) -> float:
    try:
        return float(str(s).strip())
    except Exception:
        return d


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def load_json(path: str, fallback: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def save_json(path: str, obj: Any):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# -----------------------------
# Logger
# -----------------------------
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

    def _log(self, lvl: str, msg: str):
        line = f"[{ts()}] [{lvl}] {msg}"
        with self._lock:
            self._write_file(line)
        try:
            if self.ui_append:
                self.ui_append(line + "\n")
        except Exception:
            pass

    def info(self, m: str): self._log("INFO", m)
    def warn(self, m: str): self._log("WARN", m)
    def error(self, m: str): self._log("ERROR", m)


# -----------------------------
# System language
# -----------------------------
def system_lang_guess() -> str:
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        primary = lang_id & 0x3FF
        mapping_primary = {
            0x09: "en",
            0x19: "ru",
            0x0C: "fr",
            0x07: "de",
            0x15: "pl",
            0x11: "ja",
            0x04: "zh",
        }
        base = mapping_primary.get(primary)
        if base:
            return base
    except Exception:
        pass

    try:
        loc = pylocale.getdefaultlocale()[0] or ""
        loc = loc.replace("_", "-")
        if loc:
            return loc.split("-")[0].lower()
    except Exception:
        pass

    return "en"


# -----------------------------
# i18n (EN/RU/JA/PL/DE/ZH)
# -----------------------------
class I18N:
    SUPPORTED = ["en", "ru", "ja", "pl", "de", "zh"]

    BUILTIN = {
        "en": {
            "app_title": "Saonix",
            "loader_title": "Starting Saonix…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_check": "Checking version…",
            "loader_icon": "Checking icon…",
            "loader_ready": "Launching UI…",
            "support": f"Problems / questions / suggestions — Discord: {SUPPORT_DISCORD}",
            "theme_dark": "Dark",
            "theme_light": "Light",
            "nav_record": "● Record",
            "nav_library": "📚 Library",
            "nav_settings": "⚙ Settings",
            "status_ready": "Ready",
            "status_recording": "● Recording…",
            "status_playing": "▶ Playing…",
            "rec_start": "● Start recording",
            "rec_stop": "■ Stop recording",
            "rec_play": "▶ Play",
            "rec_stop_play": "⏹ Stop",
            "rec_save": "💾 Save",
            "rec_save_label": "Save name:",
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
            "settings_title": "Settings",
            "repeat": "Repeat (times)",
            "loop": "Loop (sec)",
            "speed": "Speed",
            "delay": "Start delay (sec)",
            "apply": "Apply",
            "reset": "Reset",
            "hk_title": "Hotkeys",
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
            "invalid_hotkey": "Invalid hotkey format. Example: F6 or Ctrl+Alt+F6",
            "empty": "(empty)",
            "binds_none": "(no binds)",
            "saved": "Saved",
            "loaded": "Loaded",
            "deleted": "Deleted",
            "renamed": "Renamed",
            "cloned": "Cloned",
            "imported": "Imported",
            "exported": "Exported",
        },
        "ru": {
            "app_title": "Saonix",
            "loader_title": "Запуск Saonix…",
            "loader_langs": "Языки: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_check": "Проверка версии…",
            "loader_icon": "Проверка иконки…",
            "loader_ready": "Запуск интерфейса…",
            "support": f"Проблемы / вопросы / предложения — Discord: {SUPPORT_DISCORD}",
            "theme_dark": "Тёмная",
            "theme_light": "Светлая",
            "nav_record": "● Запись",
            "nav_library": "📚 Библиотека",
            "nav_settings": "⚙ Настройки",
            "status_ready": "Готово",
            "status_recording": "● Запись…",
            "status_playing": "▶ Воспроизведение…",
            "rec_start": "● Начать запись",
            "rec_stop": "■ Остановить запись",
            "rec_play": "▶ Воспроизвести",
            "rec_stop_play": "⏹ Остановить",
            "rec_save": "💾 Сохранить",
            "rec_save_label": "Имя сохранения:",
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
            "settings_title": "Настройки",
            "repeat": "Повтор (раз)",
            "loop": "Цикл (сек)",
            "speed": "Скорость",
            "delay": "Задержка старта (сек)",
            "apply": "Применить",
            "reset": "Сброс",
            "hk_title": "Хоткеи",
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
        },
        "ja": {
            "app_title": "Saonix",
            "loader_title": "Saonix を起動中…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_check": "バージョン確認中…",
            "loader_icon": "アイコン確認中…",
            "loader_ready": "UI を起動中…",
            "support": f"問題 / 質問 / 提案 — Discord: {SUPPORT_DISCORD}",
        },
        "pl": {
            "app_title": "Saonix",
            "loader_title": "Uruchamianie Saonix…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_check": "Sprawdzanie wersji…",
            "loader_icon": "Sprawdzanie ikony…",
            "loader_ready": "Uruchamianie UI…",
            "support": f"Problemy / pytania / propozycje — Discord: {SUPPORT_DISCORD}",
        },
        "de": {
            "app_title": "Saonix",
            "loader_title": "Saonix wird gestartet…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_check": "Version wird geprüft…",
            "loader_icon": "Icon wird geprüft…",
            "loader_ready": "UI wird gestartet…",
            "support": f"Probleme / Fragen / Vorschläge — Discord: {SUPPORT_DISCORD}",
        },
        "zh": {
            "app_title": "Saonix",
            "loader_title": "正在启动 Saonix…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_check": "正在检查版本…",
            "loader_icon": "正在检查图标…",
            "loader_ready": "正在启动界面…",
            "support": f"问题 / 咨询 / 建议 — Discord: {SUPPORT_DISCORD}",
        },
    }

    def __init__(self, lang: str):
        self.lang = "en"
        self.dict: Dict[str, str] = {}
        self.load(lang)

    def load(self, lang: str):
        lang = (lang or "en").strip()
        if lang == "auto":
            lang = system_lang_guess()

        if lang not in self.SUPPORTED:
            base = lang.split("-")[0].lower()
            lang = base if base in self.SUPPORTED else "en"

        base = dict(self.BUILTIN["en"])
        base.update(self.BUILTIN.get(lang, {}))

        # Optional external override: locales/<lang>.json
        ext_path = os.path.join(DIR_LOCALES, f"{lang}.json")
        if os.path.exists(ext_path):
            try:
                j = load_json(ext_path, {})
                if isinstance(j, dict):
                    for k, v in j.items():
                        base[str(k)] = str(v)
            except Exception:
                pass

        self.lang = lang
        self.dict = base

    def t(self, key: str) -> str:
        return self.dict.get(key, key)


# -----------------------------
# Net cache + downloader
# -----------------------------
def _cache_get() -> Dict[str, Any]:
    c = load_json(CACHE_FILE, {})
    return c if isinstance(c, dict) else {}


def _cache_set(c: Dict[str, Any]):
    save_json(CACHE_FILE, c)


def http_get_text(url: str, timeout: float = 6.0) -> Optional[str]:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        return data.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def http_get_bytes(url: str, timeout: float = 8.0, etag_key: Optional[str] = None) -> Optional[bytes]:
    """
    Simple ETag-based cache:
    - If etag_key provided and cached, request with If-None-Match
    - If 304, returns None to indicate "no change"
    """
    try:
        import urllib.request
        c = _cache_get()
        headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
        if etag_key:
            etag = c.get(f"etag:{etag_key}")
            if etag:
                headers["If-None-Match"] = etag

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                code = getattr(r, "status", 200)
                if code == 304:
                    return None
                et = r.headers.get("ETag")
                if etag_key and et:
                    c[f"etag:{etag_key}"] = et
                    _cache_set(c)
                return r.read()
        except Exception as e:
            # urllib in py <=3.11 raises HTTPError for 304 too
            import urllib.error
            if isinstance(e, urllib.error.HTTPError) and e.code == 304:
                return None
            raise
    except Exception:
        return None


def ensure_icon_png(progress: Optional[Callable[[str, float], None]] = None) -> str:
    """
    Ensures icon.png exists locally.
    Downloads only if:
    - file missing OR
    - remote changed (ETag) OR
    - remote URL changed (cache invalidated)
    """
    ensure_dir(DIR_APP)

    c = _cache_get()
    last_url = c.get("icon_url")
    if last_url != GITHUB_ICON_URL:
        # URL changed => force refresh by removing etag
        c.pop("etag:icon", None)
        c["icon_url"] = GITHUB_ICON_URL
        _cache_set(c)

    if os.path.exists(ICON_PNG):
        # Try ETag check; if unchanged => keep file
        if progress:
            progress("icon_check", 0.55)
        data = http_get_bytes(GITHUB_ICON_URL, etag_key="icon")
        if data is None:
            return ICON_PNG
        if isinstance(data, (bytes, bytearray)) and len(data) > 100:
            try:
                with open(ICON_PNG, "wb") as f:
                    f.write(data)
            except Exception:
                pass
            return ICON_PNG
        return ICON_PNG

    if progress:
        progress("icon_download", 0.55)
    data = http_get_bytes(GITHUB_ICON_URL, etag_key="icon")
    if isinstance(data, (bytes, bytearray)) and len(data) > 100:
        try:
            with open(ICON_PNG, "wb") as f:
                f.write(data)
        except Exception:
            pass
    return ICON_PNG


def check_remote_version(progress: Optional[Callable[[str, float], None]] = None) -> Dict[str, Any]:
    """
    Reads version.txt from GitHub.
    Does NOT auto-update executable.
    Behavior:
    - If same => ok
    - If different => informs (flag only)
    """
    if progress:
        progress("version_check", 0.25)

    remote = http_get_text(GITHUB_VERSION_URL)
    if not remote:
        return {"ok": True, "remote": None, "update": False}

    remote = remote.strip()
    update = (remote != APP_VERSION)
    return {"ok": True, "remote": remote, "update": update}


# -----------------------------
# Hotkey parsing
# -----------------------------
def normalize_hotkey(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None
    t = t.replace("<", "").replace(">", "")

    # F1..F24
    if t.startswith("f") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 24:
            return f"<f{n}>"

    parts = t.split("+")
    mods = []
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
    elif len(key) == 1 and (key.isdigit() or ("a" <= key <= "z")):
        key_fmt = key
    elif key in ("space", "spc"):
        key_fmt = "<space>"
    elif key in ("tab",):
        key_fmt = "<tab>"
    elif key in ("esc", "escape"):
        key_fmt = "<esc>"
    else:
        return None

    return "+".join(mods + [key_fmt])


# -----------------------------
# DB
# -----------------------------
class MacroDB:
    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 4, "macros": {}, "binds": {}, "settings": {}}
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        d = load_json(self.path, None)
        if isinstance(d, dict):
            self.data.update(d)
            self.data.setdefault("macros", {})
            self.data.setdefault("binds", {})
            self.data.setdefault("settings", {})

    def save(self):
        save_json(self.path, self.data)

    def names(self) -> List[str]:
        return sorted(self.data.get("macros", {}).keys(), key=lambda x: x.lower())

    def exists(self, name: str) -> bool:
        return name in self.data.get("macros", {})

    def get(self, name: str):
        return self.data.get("macros", {}).get(name)

    def put(self, name: str, events: List[dict], settings: Dict[str, Any]):
        self.data.setdefault("macros", {})
        self.data["macros"][name] = {
            "created": int(time.time()),
            "events": events,
            "settings": settings
        }
        self.save()

    def delete(self, name: str):
        if name in self.data.get("macros", {}):
            del self.data["macros"][name]
        dead = [hk for hk, mn in self.data.get("binds", {}).items() if mn == name]
        for hk in dead:
            del self.data["binds"][hk]
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
        s = self.data.get("settings", {})
        return s if isinstance(s, dict) else {}

    def set_settings(self, s: Dict[str, Any]):
        self.data["settings"] = dict(s)
        self.save()


# -----------------------------
# Engine
# -----------------------------
@dataclass
class Event:
    t: float
    device: str
    type: str
    data: Dict[str, Any]


class MacroEngine:
    """
    FN/WIN not blocked: suppress=False
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
        self.log.info("Engine ready")

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
                self.log.warn("Cannot record while playing")
                return
            if self.recording:
                return
            self.events = []
            self._t0 = self.now()
            self.recording = True
            self.log.info("Recording started")

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.log.info(f"Recording stopped. Events={len(self.events)}")

    def stop_playing(self):
        with self._play_lock:
            if not self.playing:
                return
            self._stop_play.set()
            self.playing = False
            self.log.info("Playback stopped")

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


# -----------------------------
# Hotkeys
# -----------------------------
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


# -----------------------------
# Splash loader (GUI)
# -----------------------------
class Splash(ctk.CTkToplevel):
    def __init__(self, master, i18n: I18N, png_path: Optional[str] = None):
        super().__init__(master)
        self.i18n = i18n
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#0b0f16")

        w, h = 620, 340
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.card = ctk.CTkFrame(self, corner_radius=26)
        self.card.pack(fill="both", expand=True, padx=18, pady=18)

        self.card.grid_columnconfigure(0, weight=1)

        self._img_ref = None
        if png_path and os.path.exists(png_path):
            try:
                import tkinter as tk
                img = tk.PhotoImage(file=png_path)
                self._img_ref = img
                ctk.CTkLabel(self.card, text="", image=img).grid(row=0, column=0, pady=(26, 12))
            except Exception:
                pass

        self.lbl_title = ctk.CTkLabel(self.card, text=self.i18n.t("loader_title"),
                                      font=ctk.CTkFont(size=22, weight="bold"))
        self.lbl_title.grid(row=1, column=0, pady=(0, 6))

        self.lbl_langs = ctk.CTkLabel(self.card, text=self.i18n.t("loader_langs"))
        self.lbl_langs.grid(row=2, column=0, pady=(0, 14))

        self.status_var = ctk.StringVar(value=self.i18n.t("loader_check"))
        self.lbl_status = ctk.CTkLabel(self.card, textvariable=self.status_var)
        self.lbl_status.grid(row=3, column=0, pady=(0, 10))

        self.pb = ctk.CTkProgressBar(self.card)
        self.pb.grid(row=4, column=0, padx=48, pady=(0, 8), sticky="ew")
        self.pb.set(0.02)

        self.small = ctk.CTkLabel(self.card, text=self.i18n.t("support"), wraplength=520, justify="center")
        self.small.grid(row=5, column=0, pady=(10, 22), padx=28)

        self.update_idletasks()

    def set_status(self, text: str, frac: float):
        try:
            self.status_var.set(text)
            self.pb.set(clamp(float(frac), 0.02, 1.0))
            self.update_idletasks()
        except Exception:
            pass

    def close(self):
        try:
            self.destroy()
        except Exception:
            pass


# -----------------------------
# App UI (minimal stable, no page animations)
# -----------------------------
class SaonixApp(ctk.CTk):
    def __init__(self, i18n: I18N, boot_info: Dict[str, Any]):
        super().__init__()
        self.i18n = i18n
        self.boot_info = boot_info

        self._active_page = "record"
        self.db = MacroDB(DB_FILE)

        saved = self.db.get_settings()
        theme = saved.get("appearance", "Dark")
        if theme not in ("Dark", "Light"):
            theme = "Dark"
        ctk.set_appearance_mode(theme)

        self.title(self.i18n.t("app_title"))
        self.geometry("1180x720")
        self.minsize(1080, 640)

        # icon
        try:
            if os.path.exists(ICON_PNG):
                # Tk iconphoto supports PNG
                import tkinter as tk
                img = tk.PhotoImage(file=ICON_PNG)
                self.iconphoto(True, img)
                self._ico_ref = img
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.log_box = None
        self.logger = Logger(self._append_log_ui)
        self.engine = MacroEngine(self.logger)
        self.hk = HotkeyManager(self.logger)

        # playback defaults
        self.repeat_var = ctk.StringVar(value=str(saved.get("repeat", 1)))
        self.loop_var = ctk.StringVar(value=str(saved.get("loop_seconds", 0)))
        self.speed_var = ctk.StringVar(value=str(saved.get("speed", 1.0)))
        self.delay_var = ctk.StringVar(value=str(saved.get("start_delay", 0.0)))

        # base hotkeys
        self.hk_rec_var = ctk.StringVar(value=str(saved.get("hk_rec", "Ctrl+Alt+1")))
        self.hk_stoprec_var = ctk.StringVar(value=str(saved.get("hk_stoprec", "Ctrl+Alt+2")))
        self.hk_play_var = ctk.StringVar(value=str(saved.get("hk_play", "Ctrl+Alt+3")))
        self.hk_stop_var = ctk.StringVar(value=str(saved.get("hk_stop", "Ctrl+Alt+4")))

        # layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=18)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=14, pady=14)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(99, weight=1)

        self.lbl_brand = ctk.CTkLabel(self.sidebar, text=self.i18n.t("app_title"),
                                      font=ctk.CTkFont(size=26, weight="bold"))
        self.lbl_brand.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        self.btn_record = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_record"),
                                        command=lambda: self.show_page("record"))
        self.btn_library = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_library"),
                                         command=lambda: self.show_page("library"))
        self.btn_settings = ctk.CTkButton(self.sidebar, text=self.i18n.t("nav_settings"),
                                          command=lambda: self.show_page("settings"))
        self.btn_record.grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        self.btn_library.grid(row=3, column=0, padx=16, pady=8, sticky="ew")
        self.btn_settings.grid(row=4, column=0, padx=16, pady=8, sticky="ew")

        # language selector
        ctk.CTkLabel(self.sidebar, text="Language", font=ctk.CTkFont(weight="bold")).grid(
            row=6, column=0, padx=16, pady=(18, 6), sticky="w"
        )
        self.lang_menu = ctk.CTkOptionMenu(
            self.sidebar, values=["auto"] + I18N.SUPPORTED, command=self.set_lang
        )
        self.lang_choice = saved.get("lang", "auto")
        if self.lang_choice not in (["auto"] + I18N.SUPPORTED):
            self.lang_choice = "auto"
        self.lang_menu.set(self.lang_choice)
        self.lang_menu.grid(row=7, column=0, padx=16, pady=(0, 10), sticky="ew")

        # support text
        self.support_lbl = ctk.CTkLabel(self.sidebar, text=self.i18n.t("support"), wraplength=220, justify="left")
        self.support_lbl.grid(row=98, column=0, padx=16, pady=14, sticky="sw")

        # main
        self.main = ctk.CTkFrame(self, corner_radius=18)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkFrame(self.main, corner_radius=18, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        self.header.grid_columnconfigure(0, weight=1)

        self.h_title = ctk.CTkLabel(self.header, text="", font=ctk.CTkFont(size=18, weight="bold"))
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

        self.build_record_page()
        self.build_library_page()
        self.build_settings_page()

        self.rebuild_hotkeys()
        self.after(200, self.tick)
        self.show_page("record")

        # boot info log
        if self.boot_info.get("remote"):
            if self.boot_info.get("update"):
                self.logger.warn(f"Remote version {self.boot_info['remote']} available (local {APP_VERSION})")
            else:
                self.logger.info(f"Version OK: {APP_VERSION}")

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

    def _append_log_ui(self, text: str):
        try:
            if self.log_box is None:
                return
            self.log_box.insert("end", text)
            self.log_box.see("end")
        except Exception:
            pass

    def tick(self):
        if self.engine.recording:
            self.status_var.set(self.i18n.t("status_recording"))
        elif self.engine.playing:
            self.status_var.set(self.i18n.t("status_playing"))
        else:
            self.status_var.set(self.i18n.t("status_ready"))
        self.after(200, self.tick)

    def set_lang(self, lang: str):
        s = self.db.get_settings()
        s["lang"] = lang
        self.db.set_settings(s)
        self.i18n.load(lang)
        self.title(self.i18n.t("app_title"))
        self.btn_record.configure(text=self.i18n.t("nav_record"))
        self.btn_library.configure(text=self.i18n.t("nav_library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings"))
        self.support_lbl.configure(text=self.i18n.t("support"))
        self.refresh_library()
        self.show_page(self._active_page)

    # ----- settings helpers -----
    def current_play_settings(self) -> Dict[str, Any]:
        repeat = clamp(safe_int(self.repeat_var.get(), 1), 1, 9999)
        loop_seconds = clamp(safe_int(self.loop_var.get(), 0), 0, 24 * 3600)
        speed = clamp(safe_float(self.speed_var.get(), 1.0), 0.05, 5.0)
        delay = clamp(safe_float(self.delay_var.get(), 0.0), 0.0, 60.0)
        return {"repeat": repeat, "loop_seconds": loop_seconds, "speed": speed, "start_delay": delay}

    def persist_settings(self):
        s = self.db.get_settings()
        s.update(self.current_play_settings())
        s.update({
            "lang": self.lang_menu.get(),
            "hk_rec": self.hk_rec_var.get(),
            "hk_stoprec": self.hk_stoprec_var.get(),
            "hk_play": self.hk_play_var.get(),
            "hk_stop": self.hk_stop_var.get(),
        })
        self.db.set_settings(s)

    # ----- pages -----
    def show_page(self, which: str):
        self._active_page = which
        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid_remove()
        if which == "record":
            self.page_record.grid()
            self.h_title.configure(text=self.i18n.t("nav_record"))
        elif which == "library":
            self.page_library.grid()
            self.h_title.configure(text=self.i18n.t("lib_title"))
        else:
            self.page_settings.grid()
            self.h_title.configure(text=self.i18n.t("settings_title"))

    # ----- record page -----
    def build_record_page(self):
        self.page_record.grid_columnconfigure(0, weight=1)
        self.page_record.grid_columnconfigure(1, weight=1)
        self.page_record.grid_rowconfigure(2, weight=1)

        card = ctk.CTkFrame(self.page_record, corner_radius=18)
        card.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=(16, 10))

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(14, 6))
        self.btn_start = ctk.CTkButton(row1, text=self.i18n.t("rec_start"), command=self.engine.start_recording)
        self.btn_stop = ctk.CTkButton(row1, text=self.i18n.t("rec_stop"), command=self.engine.stop_recording)
        self.btn_start.pack(side="left", padx=6)
        self.btn_stop.pack(side="left", padx=6)

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=6)
        self.btn_play = ctk.CTkButton(row2, text=self.i18n.t("rec_play"), command=self.play_from_ui)
        self.btn_stopplay = ctk.CTkButton(row2, text=self.i18n.t("rec_stop_play"), command=self.engine.stop_playing)
        self.btn_play.pack(side="left", padx=6)
        self.btn_stopplay.pack(side="left", padx=6)

        self.save_label = ctk.CTkLabel(card, text=self.i18n.t("rec_save_label"))
        self.save_label.pack(anchor="w", padx=16, pady=(12, 4))
        self.save_name = ctk.StringVar(value="New macro")
        self.save_entry = ctk.CTkEntry(card, textvariable=self.save_name)
        self.save_entry.pack(fill="x", padx=16, pady=6)

        self.btn_save = ctk.CTkButton(card, text=self.i18n.t("rec_save"), command=self.save_current_macro)
        self.btn_save.pack(fill="x", padx=16, pady=(6, 16))

        hint = ctk.CTkFrame(self.page_record, corner_radius=18)
        hint.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=(16, 10))
        self.hint_text = ctk.CTkLabel(
            hint,
            text=self.i18n.t("support"),
            justify="left",
            wraplength=420
        )
        self.hint_text.pack(anchor="w", padx=16, pady=16)

        self.log_box = ctk.CTkTextbox(self.page_record, height=220, corner_radius=18)
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 10))

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
        self.logger.info(f"{self.i18n.t('saved')}: {name} (events: {len(events)})")
        self.refresh_library()
        self.show_page("library")

    # ----- library page -----
    def build_library_page(self):
        self.page_library.grid_columnconfigure(0, weight=1)
        self.page_library.grid_columnconfigure(1, weight=2)
        self.page_library.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self.page_library, corner_radius=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=16)
        left.grid_rowconfigure(3, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(left, textvariable=self.search_var, placeholder_text=self.i18n.t("search_ph"))
        self.search_entry.grid(row=1, column=0, padx=16, pady=(16, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_library())

        self.macros_scroll = ctk.CTkScrollableFrame(left, corner_radius=14)
        self.macros_scroll.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        self.macro_buttons: Dict[str, ctk.CTkButton] = {}
        self.selected_macro: Optional[str] = None

        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="ew")
        btns.grid_columnconfigure((0, 1), weight=1)

        self.btn_load = ctk.CTkButton(btns, text=self.i18n.t("btn_load"), command=self.load_selected)
        self.btn_delete = ctk.CTkButton(btns, text=self.i18n.t("btn_delete"), command=self.delete_selected)
        self.btn_load.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.btn_delete.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        right = ctk.CTkFrame(self.page_library, corner_radius=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=16)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.preview_title = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=18, weight="bold"))
        self.preview_title.grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")

        self.preview_box = ctk.CTkTextbox(right, corner_radius=14)
        self.preview_box.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.refresh_library()

    def refresh_library(self):
        q = self.search_var.get().strip().lower()

        for child in self.macros_scroll.winfo_children():
            try: child.destroy()
            except Exception: pass
        self.macro_buttons.clear()

        names = []
        for n in self.db.names():
            if q and q not in n.lower():
                continue
            names.append(n)

        if not names:
            ctk.CTkLabel(self.macros_scroll, text=self.i18n.t("empty")).pack(anchor="w", padx=8, pady=8)
            self.selected_macro = None
            self.preview_title.configure(text="—")
            self.preview_box.delete("1.0", "end")
            return

        if self.selected_macro not in names:
            self.selected_macro = names[0]

        for n in names:
            btn = ctk.CTkButton(self.macros_scroll, text=n, anchor="w", corner_radius=12,
                               command=lambda name=n: self.select_macro(name))
            btn.pack(fill="x", padx=6, pady=6)
            self.macro_buttons[n] = btn

        self.preview_selected()

    def select_macro(self, name: str):
        self.selected_macro = name
        self.preview_selected()

    def preview_selected(self):
        name = self.selected_macro
        if not name:
            return
        item = self.db.get(name)
        if not item:
            return

        self.preview_title.configure(text=name)
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("end", json.dumps(item.get("settings", {}), ensure_ascii=False, indent=2))

    def load_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        item = self.db.get(name)
        if not item:
            return
        self.engine.events = [Event(**e) for e in item.get("events", [])]
        s = item.get("settings", {})
        self.repeat_var.set(str(s.get("repeat", 1)))
        self.loop_var.set(str(s.get("loop_seconds", 0)))
        self.speed_var.set(str(s.get("speed", 1.0)))
        self.delay_var.set(str(s.get("start_delay", 0.0)))
        self.logger.info(f"{self.i18n.t('loaded')}: {name} (events: {len(self.engine.events)})")
        self.show_page("record")

    def delete_selected(self):
        name = self.selected_macro
        if not name:
            messagebox.showwarning(self.i18n.t("app_title"), self.i18n.t("select_macro_warn"))
            return
        if not messagebox.askyesno(self.i18n.t("app_title"), self.i18n.t("delete_q")):
            return
        self.db.delete(name)
        self.logger.info(f"{self.i18n.t('deleted')}: {name}")
        self.selected_macro = None
        self.refresh_library()

    # ----- settings page -----
    def build_settings_page(self):
        wrap = ctk.CTkFrame(self.page_settings, corner_radius=18)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)
        wrap.grid_columnconfigure(1, weight=1)

        def row(r: int, label: str, var: ctk.StringVar, ph: str):
            ctk.CTkLabel(wrap, text=label).grid(row=r, column=0, padx=14, pady=10, sticky="w")
            ctk.CTkEntry(wrap, textvariable=var, placeholder_text=ph).grid(row=r, column=1, padx=14, pady=10, sticky="ew")

        row(0, self.i18n.t("repeat"), self.repeat_var, "e.g. 5")
        row(1, self.i18n.t("loop"), self.loop_var, "e.g. 60")
        row(2, self.i18n.t("speed"), self.speed_var, "0.5 / 1.0 / 2.0")
        row(3, self.i18n.t("delay"), self.delay_var, "e.g. 3")

        ctk.CTkLabel(wrap, text=self.i18n.t("hk_title"), font=ctk.CTkFont(weight="bold")).grid(
            row=4, column=0, columnspan=2, padx=14, pady=(18, 6), sticky="w"
        )

        row(5, self.i18n.t("hk_rec"), self.hk_rec_var, "Ctrl+Alt+1")
        row(6, self.i18n.t("hk_stoprec"), self.hk_stoprec_var, "Ctrl+Alt+2")
        row(7, self.i18n.t("hk_play"), self.hk_play_var, "Ctrl+Alt+3")
        row(8, self.i18n.t("hk_stop"), self.hk_stop_var, "Ctrl+Alt+4")

        bar = ctk.CTkFrame(wrap, fg_color="transparent")
        bar.grid(row=9, column=0, columnspan=2, padx=14, pady=(12, 0), sticky="ew")

        ctk.CTkButton(bar, text=self.i18n.t("apply"), command=self.apply_settings).pack(side="left", padx=6)
        ctk.CTkButton(bar, text=self.i18n.t("hk_apply"), command=self.apply_hotkeys).pack(side="left", padx=6)

        info = self.boot_info
        ver_line = f"Version: {APP_VERSION}"
        if info.get("remote"):
            ver_line += f" | Remote: {info['remote']}"
        ctk.CTkLabel(wrap, text=ver_line).grid(row=10, column=0, columnspan=2, padx=14, pady=(18, 6), sticky="w")
        ctk.CTkLabel(wrap, text=self.i18n.t("support"), wraplength=900).grid(
            row=11, column=0, columnspan=2, padx=14, pady=(0, 10), sticky="w"
        )

    def apply_settings(self):
        self.persist_settings()
        self.logger.info("Settings saved")

    def apply_hotkeys(self):
        self.persist_settings()
        self.rebuild_hotkeys()
        self.logger.info("Hotkeys updated")

    def rebuild_hotkeys(self):
        def hk_norm(raw: str, fallback: str) -> str:
            v = normalize_hotkey(raw)
            return v if v else (normalize_hotkey(fallback) or "<f6>")

        mapping = {
            hk_norm(self.hk_rec_var.get(), "Ctrl+Alt+1"): self.engine.start_recording,
            hk_norm(self.hk_stoprec_var.get(), "Ctrl+Alt+2"): self.engine.stop_recording,
            hk_norm(self.hk_play_var.get(), "Ctrl+Alt+3"): self.play_from_ui,
            hk_norm(self.hk_stop_var.get(), "Ctrl+Alt+4"): self.engine.stop_playing,
        }
        self.hk.set(mapping)


# -----------------------------
# Bootstrap
# -----------------------------
def main():
    splash = None
    root = None
    try:
        # initial config language
        settings = load_json(CFG_FILE, {})
        lang = "auto"
        if isinstance(settings, dict):
            lang = settings.get("language", "auto")

        i18n = I18N(lang)

        # create hidden root for splash
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("dark-blue")

        root = ctk.CTk()
        root.withdraw()

        # Make sure icon exists before showing splash (so splash can display image too)
        ensure_dir(DIR_APP)
        if not os.path.exists(ICON_PNG):
            # best effort: download; if fails, splash works without image
            ensure_icon_png()

        splash = Splash(master=root, i18n=i18n, png_path=ICON_PNG)

        def progress(tag: str, frac: float):
            if not splash:
                return
            if tag == "version_check":
                splash.set_status(i18n.t("loader_check"), frac)
            elif tag.startswith("icon"):
                splash.set_status(i18n.t("loader_icon"), frac)
            else:
                splash.set_status(i18n.t("loader_ready"), frac)

        # Version check (no updater; only status)
        boot_info = check_remote_version(progress=progress)

        # Icon ensure with ETag (no repeat downloads if not changed)
        ensure_icon_png(progress=lambda _t, f: progress("icon", f))

        splash.set_status(i18n.t("loader_ready"), 0.92)

        # Main window
        app = SaonixApp(i18n=i18n, boot_info=boot_info)
        splash.close()
        splash = None
        try:
            root.destroy()
        except Exception:
            pass

        app.mainloop()

    except Exception as e:
        try:
            with open(CRASH_FILE, "w", encoding="utf-8") as f:
                f.write(str(e) + "\n\n" + traceback.format_exc())
        except Exception:
            pass
        try:
            if splash:
                splash.close()
        except Exception:
            pass
        try:
            if root:
                root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
