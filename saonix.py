import json
import os
import sys
import time
import threading
import traceback
import ctypes
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Callable

import customtkinter as ctk
from tkinter import messagebox, filedialog

from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, KeyCode, Controller as KeyboardController

# Optional notifications (Windows toast)
try:
    from win10toast import ToastNotifier
except Exception:
    ToastNotifier = None


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
    """
    For PyInstaller onefile: sys._MEIPASS
    For normal run: current folder
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel)


def pick_icon_path() -> Optional[str]:
    # priority: data/icon.ico, then local ./icon.ico, then bundled icon.ico
    p1 = os.path.join(APP_VENDOR_DIR, "icon.ico")
    p2 = os.path.join(os.path.abspath("."), "icon.ico")
    p3 = resource_path("icon.ico")
    for p in (p1, p2, p3):
        if os.path.exists(p):
            return p
    return None


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


# =========================
# Notifications
# =========================
class Notifier:
    def __init__(self, enabled: bool):
        self.enabled = bool(enabled)
        self._toast = ToastNotifier() if ToastNotifier else None

    def set_enabled(self, v: bool):
        self.enabled = bool(v)

    def toast(self, title: str, msg: str, duration: int = 3):
        if not self.enabled or not self._toast:
            return
        try:
            self._toast.show_toast(title, msg, duration=duration, threaded=True)
        except Exception:
            pass


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
    """
    Use Windows UI language if possible.
    Fallback: 'en'
    """
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        langid_map = {
            0x0409: "en",     # English (US)
            0x0809: "en",     # English (UK)
            0x0419: "ru",     # Russian
            0x0804: "zh-CN",  # Chinese (Simplified)
            0x0411: "ja",     # Japanese
            0x0412: "ko",     # Korean
            0x0421: "id",     # Indonesian
            0x040c: "fr",     # French
            0x0416: "pt-BR",  # Portuguese (Brazil) - not perfect mapping but ok
            0x042a: "vi",     # Vietnamese
            0x0415: "pl",     # Polish
        }
        return langid_map.get(lid, "en")
    except Exception:
        return "en"


class I18N:
    def __init__(self, lang: str):
        self.lang = lang if lang in SUPPORTED_LANGS else "en"
        self.data: Dict[str, str] = {}
        self.load()

    def load(self):
        # priority: ProgramData locales, then bundled locales
        p1 = os.path.join(LOCALES_DIR, f"{self.lang}.json")
        p2 = resource_path(os.path.join("locales", f"{self.lang}.json"))
        path = p1 if os.path.exists(p1) else p2
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def t(self, key: str, fallback: Optional[str] = None) -> str:
        if key in self.data:
            return str(self.data[key])
        return fallback if fallback is not None else key


# =========================
# Config
# =========================
DEFAULT_CONFIG = {
    "lang": "auto",  # auto or explicit tag
    "notifications": True,
    "appearance": "Dark",  # Dark/Light
    "style": "CalmDark",
    "base_hotkeys": {
        "record": "Ctrl+Alt+1",
        "stop_record": "Ctrl+Alt+2",
        "play_loaded": "Ctrl+Alt+3",
        "stop_play": "Ctrl+Alt+4",
    }
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
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: Dict[str, Any]):
    ensure_dirs()
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


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
            "settings": settings
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
        if old not in self.data["macros"]:
            return False
        if new in self.data["macros"]:
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
    Returns pynput GlobalHotKeys format:
      "<ctrl>+<alt>+1", "<cmd>+<shift>+z", "<f6>", "<space>" ...
    Supports 1-3 keys (mods + main key).
    """
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None

    # allow already formatted "<...>"
    if t.startswith("<") and t.endswith(">") and "+" not in t:
        return t

    parts = t.split("+")
    mods = []
    key = None

    mod_map = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "win": "<cmd>",
        "cmd": "<cmd>",
        "meta": "<cmd>",
    }

    for p in parts:
        if p in mod_map:
            if mod_map[p] not in mods:
                mods.append(mod_map[p])
        else:
            key = p

    if key is None:
        return None

    # main key normalization
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
    elif key in ("tab",):
        key_fmt = "<tab>"
    elif key in ("esc", "escape"):
        key_fmt = "<esc>"
    elif key in ("enter", "return"):
        key_fmt = "<enter>"
    else:
        return None

    seq = mods + [key_fmt]
    return "+".join(seq)


# =========================
# Engine
# =========================
class MacroEngine:
    def __init__(self, logger: Logger, notifier: Notifier):
        self.log = logger
        self.notifier = notifier
        self.events: List[Event] = []
        self.recording = False
        self.playing = False

        self._t0: Optional[float] = None
        self._stop_play = threading.Event()
        self._play_lock = threading.Lock()
        self._play_thread: Optional[threading.Thread] = None

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
        return 0.0 if self._t0 is None else self.now() - self._t0

    def _add(self, device: str, etype: str, data: Dict[str, Any]):
        if not self.recording:
            return
        self.events.append(Event(t=self.rel_time(), device=device, type=etype, data=data))

    def start_recording(self):
        with self._play_lock:
            if self.playing:
                self.log.warn("Can't record while playing.")
                return
            if self.recording:
                self.log.warn("Already recording.")
                return
            self.events = []
            self._t0 = self.now()
            self.recording = True
            self.log.info("=== Recording started ===")
            self.notifier.toast(APP_NAME, "Recording started")

    def stop_recording(self):
        if not self.recording:
            self.log.warn("Not recording.")
            return
        self.recording = False
        self.log.info(f"=== Recording stopped. Events: {len(self.events)} ===")
        self.notifier.toast(APP_NAME, f"Recording stopped ({len(self.events)} events)")

    def stop_playing(self):
        with self._play_lock:
            if not self.playing:
                self.log.warn("Not playing.")
                return
            self._stop_play.set()
            self.playing = False
            self.log.info("=== Playback stopped ===")
            self.notifier.toast(APP_NAME, "Playback stopped")

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

            def play_once():
                base = self.now()
                for ev in self.events:
                    if self._stop_play.is_set():
                        return
                    target = base + (ev.t / speed)
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
                        self.log.info(f"Start in {start_delay:.2f}s...")
                        self.notifier.toast(APP_NAME, f"Start in {start_delay:.1f}s")
                        end = time.time() + start_delay
                        while time.time() < end and not self._stop_play.is_set():
                            time.sleep(0.01)

                    if loop_seconds > 0:
                        self.log.info(f"=== Loop {loop_seconds}s, speed={speed} ===")
                        self.notifier.toast(APP_NAME, f"Playback loop {loop_seconds}s")
                        started = time.time()
                        loops = 0
                        while not self._stop_play.is_set() and (time.time() - started) < loop_seconds:
                            play_once()
                            loops += 1
                        self.log.info(f"Done. Passes: {loops}")
                    else:
                        self.log.info(f"=== Repeat {repeat} times, speed={speed} ===")
                        self.notifier.toast(APP_NAME, f"Playback x{repeat}")
                        for i in range(repeat):
                            if self._stop_play.is_set():
                                break
                            self.log.info(f"Pass {i+1}/{repeat}")
                            play_once()

                    self.log.info("=== Playback finished ===")
                    self.notifier.toast(APP_NAME, "Playback finished")

                except Exception as e:
                    self.log.error(f"Playback error: {e}")
                    self.log.error(traceback.format_exc())
                finally:
                    with self._play_lock:
                        self.playing = False
                        self._stop_play.set()

            self._play_thread = threading.Thread(target=run, daemon=True)
            self._play_thread.start()


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
            self.log.error(f"Hotkey error: {e}")

    def shutdown(self):
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass


# =========================
# Styles (simple, stable)
# =========================
class StylePack:
    def __init__(self, name, dark_bg, dark_panel, dark_card, dark_text, dark_muted, accent,
                 light_bg, light_panel, light_card, light_text, light_muted):
        self.name = name

        self.dark_bg = dark_bg
        self.dark_panel = dark_panel
        self.dark_card = dark_card
        self.dark_text = dark_text
        self.dark_muted = dark_muted

        self.light_bg = light_bg
        self.light_panel = light_panel
        self.light_card = light_card
        self.light_text = light_text
        self.light_muted = light_muted

        self.accent = accent


STYLES = {
    "CalmDark": StylePack(
        "CalmDark",
        dark_bg="#0d1118", dark_panel="#121826", dark_card="#141d2e",
        dark_text="#e9eef7", dark_muted="#a7b4cc", accent="#5aa7ff",
        # soft light theme (applies to everything)
        light_bg="#f3f5f8", light_panel="#ffffff", light_card="#ffffff",
        light_text="#121826", light_muted="#5a6477"
    ),
}


# =========================
# App
# =========================
class SaonixApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ensure_dirs()

        self.cfg = load_config()

        # appearance
        ctk.set_appearance_mode(self.cfg.get("appearance", "Dark"))
        ctk.set_default_color_theme("blue")

        self.style = STYLES.get(self.cfg.get("style", "CalmDark"), STYLES["CalmDark"])

        # language
        lang = self.cfg.get("lang", "auto")
        if lang == "auto":
            lang = get_windows_ui_lang_tag()
            if lang not in SUPPORTED_LANGS:
                lang = "en"
        self.lang = lang if lang in SUPPORTED_LANGS else "en"
        self.i18n = I18N(self.lang)

        # notifier
        self.notifier = Notifier(self.cfg.get("notifications", True))

        # window
        self.title(self.i18n.t("app_title", APP_NAME))
        self.geometry("1180x720")
        self.minsize(1180, 720)

        ico = pick_icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.db = MacroDB(DB_FILE)
        self.log_box = None
        self.logger = Logger(self._append_log_ui)

        self.engine = MacroEngine(self.logger, self.notifier)
        self.hk = HotkeyManager(self.logger)

        # layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=18)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=14, pady=14)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(99, weight=1)

        self.lbl_brand = ctk.CTkLabel(self.sidebar, text=APP_NAME, font=ctk.CTkFont(size=26, weight="bold"))
        self.lbl_brand.grid(row=0, column=0, padx=16, pady=(16, 2), sticky="w")

        self.lbl_tag = ctk.CTkLabel(self.sidebar, text=self.i18n.t("tagline", "Macro Recorder"), font=ctk.CTkFont(size=13))
        self.lbl_tag.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")

        self.btn_record = ctk.CTkButton(self.sidebar, text="●", command=lambda: self.show_page("record"))
        self.btn_record.grid(row=2, column=0, padx=16, pady=8, sticky="ew")

        self.btn_library = ctk.CTkButton(self.sidebar, text="📚", command=lambda: self.show_page("library"))
        self.btn_library.grid(row=3, column=0, padx=16, pady=8, sticky="ew")

        self.btn_settings = ctk.CTkButton(self.sidebar, text="⚙", command=lambda: self.show_page("settings"))
        self.btn_settings.grid(row=4, column=0, padx=16, pady=8, sticky="ew")

        # star decor bottom
        self.star = ctk.CTkLabel(self.sidebar, text="✦", font=ctk.CTkFont(size=64, weight="bold"))
        self.star.place(relx=0.82, rely=0.92, anchor="center")

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

        self.status_var = ctk.StringVar(value="")
        self.h_status = ctk.CTkLabel(self.header, textvariable=self.status_var)
        self.h_status.grid(row=0, column=1, padx=14, pady=12, sticky="e")

        self.content = ctk.CTkFrame(self.main, corner_radius=18, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=14, pady=(8, 14))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # pages
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

        self.apply_style()
        self.apply_texts()

        self.rebuild_hotkeys()

        self.after(200, self.tick)

        self.logger.info("Started.")
        self.notifier.toast(APP_NAME, "Started")

    # ---------- close ----------
    def on_close(self):
        try:
            self.logger.info("Closing...")
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
            self.status_var.set(self.i18n.t("status_recording", "● Recording..."))
        elif self.engine.playing:
            self.status_var.set(self.i18n.t("status_playing", "▶ Playing..."))
        else:
            self.status_var.set(self.i18n.t("status_ready", "Ready"))
        self.after(200, self.tick)

    # ---------- style ----------
    def _palette(self):
        is_dark = (ctk.get_appearance_mode() == "Dark")
        s = self.style
        if is_dark:
            return dict(bg=s.dark_bg, panel=s.dark_panel, card=s.dark_card, text=s.dark_text, muted=s.dark_muted, accent=s.accent)
        return dict(bg=s.light_bg, panel=s.light_panel, card=s.light_card, text=s.light_text, muted=s.light_muted, accent=s.accent)

    def apply_style(self):
        p = self._palette()

        self.configure(fg_color=p["bg"])
        self.sidebar.configure(fg_color=p["panel"])
        self.main.configure(fg_color=p["bg"])

        self.lbl_brand.configure(text_color=p["text"])
        self.lbl_tag.configure(text_color=p["muted"])
        self.h_title.configure(text_color=p["text"])
        self.h_status.configure(text_color=p["muted"])
        self.star.configure(text_color=p["accent"])

        for b in (self.btn_record, self.btn_library, self.btn_settings):
            b.configure(fg_color=p["card"], hover_color=p["panel"], text_color=p["text"], corner_radius=14)

        # record widgets
        self.card_ctrl.configure(fg_color=p["card"])
        self.card_hint.configure(fg_color=p["card"])
        self.rec_title.configure(text_color=p["text"])
        self.hint_title.configure(text_color=p["text"])
        self.hint_text.configure(text_color=p["muted"])

        for b in (self.btn_start, self.btn_stop, self.btn_play, self.btn_stopplay, self.btn_save, self.btn_clear_log):
            b.configure(text_color=p["text"])

        self.save_label.configure(text_color=p["muted"])
        self.save_entry.configure(fg_color=p["panel"], text_color=p["text"])
        self.log_title.configure(text_color=p["text"])
        self.log_box.configure(fg_color=p["panel"], text_color=p["text"])

        # library
        self.lib_left.configure(fg_color=p["card"])
        self.lib_right.configure(fg_color=p["card"])
        self.lib_title.configure(text_color=p["text"])
        self.search_entry.configure(fg_color=p["panel"], text_color=p["text"])
        self.macros_scroll.configure(fg_color=p["panel"])
        self.preview_title.configure(text_color=p["text"])
        self.preview_meta.configure(text_color=p["muted"])
        self.preview_box.configure(fg_color=p["panel"], text_color=p["text"])
        self.bind_label.configure(text_color=p["text"])
        self.bind_entry.configure(fg_color=p["panel"], text_color=p["text"])
        self.binds_box.configure(fg_color=p["panel"], text_color=p["text"])

        for b in (self.btn_load, self.btn_rename, self.btn_clone, self.btn_export, self.btn_import, self.btn_bind, self.btn_unbind, self.btn_play_sel, self.btn_stop_sel, self.btn_delete):
            b.configure(text_color=p["text"])

        # settings
        self.set_wrap.configure(fg_color=p["card"])
        self.set_title.configure(text_color=p["text"])
        self.set_hint.configure(text_color=p["muted"])
        for lab in self.set_labels:
            lab.configure(text_color=p["text"])
        for ent in self.set_entries:
            ent.configure(fg_color=p["panel"], text_color=p["text"])
        for ent in (self.hk_record_entry, self.hk_stoprec_entry, self.hk_play_entry, self.hk_stop_entry):
            ent.configure(fg_color=p["panel"], text_color=p["text"])
        self.lang_menu.configure(fg_color=p["panel"], button_color=p["card"], button_hover_color=p["panel"], text_color=p["text"])
        self.mode_menu.configure(fg_color=p["panel"], button_color=p["card"], button_hover_color=p["panel"], text_color=p["text"])
        self.notify_switch.configure(text_color=p["text"], progress_color=p["accent"])

    def apply_texts(self):
        self.title(self.i18n.t("app_title", APP_NAME))

        self.btn_record.configure(text=self.i18n.t("nav_record", "● Record"))
        self.btn_library.configure(text=self.i18n.t("nav_library", "📚 Library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings", "⚙ Settings"))

        # page titles
        if self._active_page == "record":
            self.h_title.configure(text=self.i18n.t("page_record", "Record"))
        elif self._active_page == "library":
            self.h_title.configure(text=self.i18n.t("page_library", "Library"))
        else:
            self.h_title.configure(text=self.i18n.t("page_settings", "Settings"))

        # record page
        self.rec_title.configure(text=self.i18n.t("record_controls", "Controls"))
        self.btn_start.configure(text=self.i18n.t("start_record", "● Start recording"))
        self.btn_stop.configure(text=self.i18n.t("stop_record", "■ Stop recording"))
        self.btn_play.configure(text=self.i18n.t("play_loaded", "▶ Play (loaded)"))
        self.btn_stopplay.configure(text=self.i18n.t("stop_play", "⏹ Stop"))
        self.save_label.configure(text=self.i18n.t("save_to_library", "Save to library:"))
        self.btn_save.configure(text=self.i18n.t("save", "💾 Save"))
        self.hint_title.configure(text=self.i18n.t("hotkeys_title", "Hotkeys"))
        self.log_title.configure(text=self.i18n.t("log", "Log"))
        self.btn_clear_log.configure(text=self.i18n.t("clear_log", "Clear log (UI only)"))

        self.refresh_hotkeys_hint()

        # library page
        self.lib_title.configure(text=self.i18n.t("library", "Library"))
        self.search_entry.configure(placeholder_text=self.i18n.t("search", "Search..."))
        self.btn_load.configure(text=self.i18n.t("load", "Load"))
        self.btn_delete.configure(text=self.i18n.t("delete", "Delete"))
        self.btn_rename.configure(text=self.i18n.t("rename", "Rename"))
        self.btn_clone.configure(text=self.i18n.t("clone", "Clone"))
        self.btn_export.configure(text=self.i18n.t("export", "Export JSON"))
        self.btn_import.configure(text=self.i18n.t("import", "Import JSON"))
        self.bind_label.configure(text=self.i18n.t("bind", "Bind:"))
        self.bind_entry.configure(placeholder_text=self.i18n.t("bind_placeholder", "F6 or Ctrl+Alt+F6"))
        self.btn_bind.configure(text=self.i18n.t("assign", "Assign"))
        self.btn_unbind.configure(text=self.i18n.t("remove", "Remove"))
        self.btn_play_sel.configure(text=self.i18n.t("play_selected", "▶ Play selected"))
        self.btn_stop_sel.configure(text=self.i18n.t("stop", "⏹ Stop"))

        # settings page
        self.set_title.configure(text=self.i18n.t("playback_settings", "Playback settings"))
        self.set_hint.configure(text=self.i18n.t("loop_hint", "If Loop > 0, Repeat is ignored."))

        self.notify_switch.configure(text=self.i18n.t("notifications", "Notifications"))
        self.lang_label.configure(text=self.i18n.t("language", "Language"))
        self.mode_label.configure(text=self.i18n.t("theme", "Theme"))

        self.hk_title.configure(text=self.i18n.t("base_hotkeys", "Base hotkeys"))
        self.hk_record_label.configure(text=self.i18n.t("hk_record", "Record"))
        self.hk_stoprec_label.configure(text=self.i18n.t("hk_stop_record", "Stop record"))
        self.hk_play_label.configure(text=self.i18n.t("hk_play_loaded", "Play loaded"))
        self.hk_stop_label.configure(text=self.i18n.t("hk_stop_play", "Stop play"))

        self.btn_apply.configure(text=self.i18n.t("apply", "Apply"))
        self.btn_reset.configure(text=self.i18n.t("reset", "Reset"))

    def refresh_hotkeys_hint(self):
        hk = self.cfg.get("base_hotkeys", DEFAULT_CONFIG["base_hotkeys"])
        txt = (
            f"{self.i18n.t('hotkeys_base', 'Base')}:\n"
            f"{hk.get('record','')}" + " — " + self.i18n.t("hk_record", "Record") + "\n"
            f"{hk.get('stop_record','')}" + " — " + self.i18n.t("hk_stop_record", "Stop record") + "\n"
            f"{hk.get('play_loaded','')}" + " — " + self.i18n.t("hk_play_loaded", "Play loaded") + "\n"
            f"{hk.get('stop_play','')}" + " — " + self.i18n.t("hk_stop_play", "Stop play") + "\n\n"
            + self.i18n.t("admin_hint", "If target app runs as Admin, run Saonix as Admin too.")
        )
        self.hint_text.configure(text=txt)

    # ---------- navigation ----------
    def show_page(self, which: str, animate: bool = True):
        self._active_page = which
        pages = {
            "record": (self.page_record, self.i18n.t("page_record", "Record")),
            "library": (self.page_library, self.i18n.t("page_library", "Library")),
            "settings": (self.page_settings, self.i18n.t("page_settings", "Settings")),
        }
        frame, title = pages[which]

        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid_remove()

        frame.grid()
        self.h_title.configure(text=title)

    # =========================
    # Playback settings helpers
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

        self.rec_title = ctk.CTkLabel(self.card_ctrl, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.rec_title.pack(anchor="w", padx=16, pady=(16, 8))

        row1 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=6)

        self.btn_start = ctk.CTkButton(row1, text="", command=self.engine.start_recording)
        self.btn_start.pack(side="left", padx=6)

        self.btn_stop = ctk.CTkButton(row1, text="", command=self.engine.stop_recording)
        self.btn_stop.pack(side="left", padx=6)

        row2 = ctk.CTkFrame(self.card_ctrl, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=6)

        self.btn_play = ctk.CTkButton(row2, text="", command=self.play_from_ui)
        self.btn_play.pack(side="left", padx=6)

        self.btn_stopplay = ctk.CTkButton(row2, text="", command=self.engine.stop_playing)
        self.btn_stopplay.pack(side="left", padx=6)

        self.save_label = ctk.CTkLabel(self.card_ctrl, text="", font=ctk.CTkFont(size=12))
        self.save_label.pack(anchor="w", padx=16, pady=(12, 4))

        self.save_name = ctk.StringVar(value="New macro")
        self.save_entry = ctk.CTkEntry(self.card_ctrl, textvariable=self.save_name)
        self.save_entry.pack(fill="x", padx=16, pady=6)

        self.btn_save = ctk.CTkButton(self.card_ctrl, text="", command=self.save_current_macro)
        self.btn_save.pack(fill="x", padx=16, pady=(6, 16))

        self.card_hint = ctk.CTkFrame(self.page_record, corner_radius=18)
        self.card_hint.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=(16, 10))

        self.hint_title = ctk.CTkLabel(self.card_hint, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.hint_title.pack(anchor="w", padx=16, pady=(16, 8))

        self.hint_text = ctk.CTkLabel(self.card_hint, text="", justify="left", wraplength=420)
        self.hint_text.pack(anchor="w", padx=16, pady=(0, 16))

        self.log_title = ctk.CTkLabel(self.page_record, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self.log_title.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 6))

        self.log_box = ctk.CTkTextbox(self.page_record, height=220, corner_radius=18)
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 10))

        self.btn_clear_log = ctk.CTkButton(self.page_record, text="", command=self.clear_log_ui)
        self.btn_clear_log.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

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
            messagebox.showwarning(self.i18n.t("name", "Name"), self.i18n.t("enter_name", "Enter macro name."))
            return
        if not self.engine.events:
            messagebox.showwarning(self.i18n.t("empty", "Empty"), self.i18n.t("no_events", "No events. Record first."))
            return

        if self.db.exists(name):
            if not messagebox.askyesno(self.i18n.t("overwrite", "Overwrite"), self.i18n.t("overwrite_q", "Macro exists. Overwrite?")):
                return

        settings = self.current_settings()
        self.db.put(name, self.engine.events, settings)
        self.logger.info(f"Saved: {name} (events: {len(self.engine.events)})")
        self.notifier.toast(APP_NAME, f"Saved: {name}")
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

        self.lib_title = ctk.CTkLabel(self.lib_left, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.lib_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(self.lib_left, textvariable=self.search_var, placeholder_text="")
        self.search_entry.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_library())

        self.macros_scroll = ctk.CTkScrollableFrame(self.lib_left, corner_radius=14)
        self.macros_scroll.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")
        self.macro_buttons: Dict[str, ctk.CTkButton] = {}
        self.selected_macro: Optional[str] = None

        actions = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)

        self.btn_load = ctk.CTkButton(actions, text="", command=self.load_selected)
        self.btn_load.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_delete = ctk.CTkButton(actions, text="", command=self.delete_selected)
        self.btn_delete.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions2 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions2.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions2.grid_columnconfigure((0, 1), weight=1)

        self.btn_rename = ctk.CTkButton(actions2, text="", command=self.rename_selected)
        self.btn_rename.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_clone = ctk.CTkButton(actions2, text="", command=self.clone_selected)
        self.btn_clone.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        actions3 = ctk.CTkFrame(self.lib_left, fg_color="transparent")
        actions3.grid(row=6, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions3.grid_columnconfigure((0, 1), weight=1)

        self.btn_export = ctk.CTkButton(actions3, text="", command=self.export_selected)
        self.btn_export.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.btn_import = ctk.CTkButton(actions3, text="", command=self.import_macro)
        self.btn_import.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

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

        self.bind_label = ctk.CTkLabel(bind_row, text="", width=90, anchor="w")
        self.bind_label.grid(row=0, column=0, sticky="w")

        self.bind_var = ctk.StringVar(value="F6")
        self.bind_entry = ctk.CTkEntry(bind_row, textvariable=self.bind_var, placeholder_text="")
        self.bind_entry.grid(row=0, column=1, sticky="ew", padx=(10, 10))

        self.btn_bind = ctk.CTkButton(bind_row, text="", width=110, command=self.bind_selected)
        self.btn_bind.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.btn_unbind = ctk.CTkButton(bind_row, text="", width=90, command=self.unbind_selected)
        self.btn_unbind.grid(row=0, column=3, sticky="e")

        self.binds_box = ctk.CTkTextbox(self.lib_right, height=120, corner_radius=14)
        self.binds_box.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        self.preview_box = ctk.CTkTextbox(self.lib_right, corner_radius=14)
        self.preview_box.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="nsew")

        playbar = ctk.CTkFrame(self.lib_right, fg_color="transparent")
        playbar.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")
        playbar.grid_columnconfigure((0, 1), weight=1)

        self.btn_play_sel = ctk.CTkButton(playbar, text="", command=self.play_selected)
        self.btn_play_sel.grid(row=0, column=0, padx=6, sticky="ew")

        self.btn_stop_sel = ctk.CTkButton(playbar, text="", command=self.engine.stop_playing)
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
            empty = ctk.CTkLabel(self.macros_scroll, text="(empty)")
            empty.pack(anchor="w", padx=8, pady=8)
            self.selected_macro = None
            self.preview_clear()
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
        self.notifier.toast(APP_NAME, f"Deleted: {name}")
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
        path = filedialog.askopenfilename(title="Import macro", filetypes=[("JSON", "*.json")])
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            if not isinstance(payload, dict) or "events" not in payload:
                raise ValueError("Invalid format")

            name = str(payload.get("name", os.path.splitext(os.path.basename(path))[0])).strip() or "Imported macro"

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
            self.notifier.toast(APP_NAME, f"Imported: {name}")
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
            messagebox.showerror("Bind", "Invalid format. Example: F6 or Ctrl+Alt+F6 or Win+Shift+Z")
            return

        binds = self.db.binds()
        if hk in binds and binds[hk] != name:
            if not messagebox.askyesno("Conflict", f"{hk} bound to '{binds[hk]}'. Rebind?"):
                return

        self.db.set_bind(hk, name)
        self.logger.info(f"Bind: {hk} -> {name}")
        self.refresh_binds_box()
        self.rebuild_hotkeys()

    def unbind_selected(self):
        hk_raw = self.bind_var.get()
        hk = normalize_hotkey(hk_raw)
        if not hk:
            messagebox.showerror("Remove", "Enter hotkey, e.g. F6")
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

        self.set_title = ctk.CTkLabel(self.set_wrap, text="", font=ctk.CTkFont(size=18, weight="bold"))
        self.set_title.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self.repeat_var = ctk.StringVar(value="1")
        self.loop_var = ctk.StringVar(value="0")
        self.speed_var = ctk.StringVar(value="1.0")
        self.delay_var = ctk.StringVar(value="0")

        self.set_labels = []
        self.set_entries = []

        def add_row(r: int, label: str, var: ctk.StringVar, placeholder: str):
            row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
            row.grid(row=r, column=0, padx=16, pady=8, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            lab = ctk.CTkLabel(row, text=label, width=190, anchor="w")
            lab.grid(row=0, column=0, sticky="w")
            ent = ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder)
            ent.grid(row=0, column=1, sticky="ew", padx=(10, 0))

            self.set_labels.append(lab)
            self.set_entries.append(ent)

        add_row(1, "Repeat", self.repeat_var, "e.g. 5")
        add_row(2, "Loop (sec)", self.loop_var, "e.g. 7200")
        add_row(3, "Speed", self.speed_var, "0.5 / 1.0 / 2.0")
        add_row(4, "Start delay", self.delay_var, "e.g. 3")

        self.set_hint = ctk.CTkLabel(self.set_wrap, text="", anchor="w")
        self.set_hint.grid(row=5, column=0, padx=16, pady=(4, 12), sticky="w")

        # Notifications toggle
        self.notify_var = ctk.BooleanVar(value=bool(self.cfg.get("notifications", True)))
        self.notify_switch = ctk.CTkSwitch(self.set_wrap, text="", variable=self.notify_var, command=self.toggle_notify)
        self.notify_switch.grid(row=6, column=0, padx=16, pady=(0, 10), sticky="w")

        # Language + Theme row
        row_lt = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        row_lt.grid(row=7, column=0, padx=16, pady=(0, 12), sticky="ew")
        row_lt.grid_columnconfigure((1, 3), weight=1)

        self.lang_label = ctk.CTkLabel(row_lt, text="", width=120, anchor="w")
        self.lang_label.grid(row=0, column=0, sticky="w")

        self.lang_var = ctk.StringVar(value=self.lang)
        self.lang_menu = ctk.CTkOptionMenu(row_lt, values=SUPPORTED_LANGS, variable=self.lang_var, command=self.set_language)
        self.lang_menu.grid(row=0, column=1, sticky="ew", padx=(10, 16))

        self.mode_label = ctk.CTkLabel(row_lt, text="", width=120, anchor="w")
        self.mode_label.grid(row=0, column=2, sticky="w")

        self.mode_var = ctk.StringVar(value="Dark" if ctk.get_appearance_mode() == "Dark" else "Light")
        self.mode_menu = ctk.CTkOptionMenu(row_lt, values=["Dark", "Light"], variable=self.mode_var, command=self.set_mode)
        self.mode_menu.grid(row=0, column=3, sticky="ew", padx=(10, 0))

        # Base hotkeys section
        self.hk_title = ctk.CTkLabel(self.set_wrap, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.hk_title.grid(row=8, column=0, padx=16, pady=(8, 8), sticky="w")

        hk_row = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        hk_row.grid(row=9, column=0, padx=16, pady=(0, 10), sticky="ew")
        hk_row.grid_columnconfigure(1, weight=1)

        self.hk_record_label = ctk.CTkLabel(hk_row, text="", width=140, anchor="w")
        self.hk_record_label.grid(row=0, column=0, sticky="w")
        self.hk_record_var = ctk.StringVar(value=self.cfg["base_hotkeys"].get("record", "Ctrl+Alt+1"))
        self.hk_record_entry = ctk.CTkEntry(hk_row, textvariable=self.hk_record_var)
        self.hk_record_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        hk_row2 = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        hk_row2.grid(row=10, column=0, padx=16, pady=(0, 10), sticky="ew")
        hk_row2.grid_columnconfigure(1, weight=1)

        self.hk_stoprec_label = ctk.CTkLabel(hk_row2, text="", width=140, anchor="w")
        self.hk_stoprec_label.grid(row=0, column=0, sticky="w")
        self.hk_stoprec_var = ctk.StringVar(value=self.cfg["base_hotkeys"].get("stop_record", "Ctrl+Alt+2"))
        self.hk_stoprec_entry = ctk.CTkEntry(hk_row2, textvariable=self.hk_stoprec_var)
        self.hk_stoprec_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        hk_row3 = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        hk_row3.grid(row=11, column=0, padx=16, pady=(0, 10), sticky="ew")
        hk_row3.grid_columnconfigure(1, weight=1)

        self.hk_play_label = ctk.CTkLabel(hk_row3, text="", width=140, anchor="w")
        self.hk_play_label.grid(row=0, column=0, sticky="w")
        self.hk_play_var = ctk.StringVar(value=self.cfg["base_hotkeys"].get("play_loaded", "Ctrl+Alt+3"))
        self.hk_play_entry = ctk.CTkEntry(hk_row3, textvariable=self.hk_play_var)
        self.hk_play_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        hk_row4 = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        hk_row4.grid(row=12, column=0, padx=16, pady=(0, 10), sticky="ew")
        hk_row4.grid_columnconfigure(1, weight=1)

        self.hk_stop_label = ctk.CTkLabel(hk_row4, text="", width=140, anchor="w")
        self.hk_stop_label.grid(row=0, column=0, sticky="w")
        self.hk_stop_var = ctk.StringVar(value=self.cfg["base_hotkeys"].get("stop_play", "Ctrl+Alt+4"))
        self.hk_stop_entry = ctk.CTkEntry(hk_row4, textvariable=self.hk_stop_var)
        self.hk_stop_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        btns = ctk.CTkFrame(self.set_wrap, fg_color="transparent")
        btns.grid(row=13, column=0, padx=16, pady=(6, 16), sticky="ew")

        self.btn_apply = ctk.CTkButton(btns, text="", command=self.apply_settings_to_engine)
        self.btn_apply.pack(side="left", padx=6)

        self.btn_reset = ctk.CTkButton(btns, text="", command=self.reset_settings)
        self.btn_reset.pack(side="left", padx=6)

    def toggle_notify(self):
        self.cfg["notifications"] = bool(self.notify_var.get())
        save_config(self.cfg)
        self.notifier.set_enabled(self.cfg["notifications"])
        self.notifier.toast(APP_NAME, "Notifications updated")

    def set_language(self, lang: str):
        if lang not in SUPPORTED_LANGS:
            return
        self.lang = lang
        self.cfg["lang"] = lang  # switch from auto to fixed
        save_config(self.cfg)
        self.i18n = I18N(lang)
        self.apply_texts()

    def set_mode(self, mode: str):
        ctk.set_appearance_mode("Dark" if mode == "Dark" else "Light")
        self.cfg["appearance"] = "Dark" if mode == "Dark" else "Light"
        save_config(self.cfg)
        self.apply_style()

    def reset_settings(self):
        self.repeat_var.set("1")
        self.loop_var.set("0")
        self.speed_var.set("1.0")
        self.delay_var.set("0")

        # reset hotkeys to defaults
        self.hk_record_var.set(DEFAULT_CONFIG["base_hotkeys"]["record"])
        self.hk_stoprec_var.set(DEFAULT_CONFIG["base_hotkeys"]["stop_record"])
        self.hk_play_var.set(DEFAULT_CONFIG["base_hotkeys"]["play_loaded"])
        self.hk_stop_var.set(DEFAULT_CONFIG["base_hotkeys"]["stop_play"])

        self.apply_settings_to_engine()
        self.logger.info("Settings reset.")

    def apply_settings_to_engine(self):
        # validate and save base hotkeys
        hk_record = normalize_hotkey(self.hk_record_var.get())
        hk_stoprec = normalize_hotkey(self.hk_stoprec_var.get())
        hk_play = normalize_hotkey(self.hk_play_var.get())
        hk_stop = normalize_hotkey(self.hk_stop_var.get())

        if not all([hk_record, hk_stoprec, hk_play, hk_stop]):
            messagebox.showerror("Hotkeys", "Invalid hotkey format. Examples: F6 | Ctrl+Alt+1 | Win+Shift+Z")
            return

        # save readable input too (for UI), but store normalized mapping by re-normalizing on rebuild
        self.cfg["base_hotkeys"] = {
            "record": self.hk_record_var.get().strip(),
            "stop_record": self.hk_stoprec_var.get().strip(),
            "play_loaded": self.hk_play_var.get().strip(),
            "stop_play": self.hk_stop_var.get().strip(),
        }
        save_config(self.cfg)

        s = self.current_settings()
        self.logger.info(f"Applied: repeat={s['repeat']} loop={s['loop_seconds']} speed={s['speed']} delay={s['start_delay']}")
        self.notifier.toast(APP_NAME, "Settings applied")

        self.rebuild_hotkeys()
        self.refresh_hotkeys_hint()

    # =========================
    # Hotkeys
    # =========================
    def rebuild_hotkeys(self):
        # base hotkeys from config (normalize)
        base = self.cfg.get("base_hotkeys", DEFAULT_CONFIG["base_hotkeys"])

        hk_record = normalize_hotkey(base.get("record", "Ctrl+Alt+1"))
        hk_stoprec = normalize_hotkey(base.get("stop_record", "Ctrl+Alt+2"))
        hk_play = normalize_hotkey(base.get("play_loaded", "Ctrl+Alt+3"))
        hk_stop = normalize_hotkey(base.get("stop_play", "Ctrl+Alt+4"))

        mapping: Dict[str, Callable[[], None]] = {}
        if hk_record: mapping[hk_record] = self.engine.start_recording
        if hk_stoprec: mapping[hk_stoprec] = self.engine.stop_recording
        if hk_play: mapping[hk_play] = self.play_from_ui
        if hk_stop: mapping[hk_stop] = self.engine.stop_playing

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
                    self.logger.info(f"[bind] playing: {name}")
                    self.notifier.toast(APP_NAME, f"Play: {name}")
                return _f

            mapping[hk] = make_play()

        self.hk.set(mapping)


def main():
    try:
        app = SaonixApp()
        app.mainloop()
    except Exception as e:
        try:
            ensure_dirs()
            with open(os.path.join(LOG_DIR, "crash_log.txt"), "w", encoding="utf-8") as f:
                f.write(str(e) + "\n\n" + traceback.format_exc())
        except Exception:
            pass
        print("Crash. See logs/crash_log.txt")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
