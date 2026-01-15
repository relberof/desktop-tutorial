# saonix.py
# CustomTkinter + pynput
# - Splash loader (no console), shows languages list
# - GitHub version check (no re-download if same); icon uses ETag cache
# - FULL global i18n: EN/RU/JA/PL/DE/ZH (all UI strings)
# - No page animation (no "jerky transitions")
# - Embedded icon download/cache to ProgramData\Saonix\app\icon.png (only updates when changed)
#
# Build without console (optional):
# pyinstaller --noconsole --onefile saonix.py

import os
import sys
import json
import time
import threading
import traceback
import ctypes
import locale as pylocale
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Callable, Tuple

import customtkinter as ctk
from tkinter import messagebox, filedialog

from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, KeyCode, Controller as KeyboardController


# =============================
# App constants / GitHub
# =============================
APP_NAME = "Saonix"
APP_VERSION = "1.0.0"

# Remote version + icon (raw)
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/relberof/desktop-tutorial/69cec69713c6f91563ba3c2c87c6215042e67ee5/version.txt"
GITHUB_ICON_URL = "https://raw.githubusercontent.com/relberof/desktop-tutorial/69cec69713c6f91563ba3c2c87c6215042e67ee5/icon.png"

SUPPORT_DISCORD = "Relberof"


# =============================
# Paths
# =============================
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
LOG_FILE = os.path.join(DIR_LOGS, "app.log")
CRASH_FILE = os.path.join(DIR_LOGS, "crash_log.txt")
CACHE_FILE = os.path.join(DIR_DATA, "net_cache.json")
ICON_PNG = os.path.join(DIR_APP, "icon.png")


# =============================
# Utils
# =============================
def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


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


# =============================
# Logger
# =============================
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


# =============================
# Language guess
# =============================
def system_lang_guess() -> str:
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        primary = lang_id & 0x3FF
        mapping_primary = {
            0x09: "en",
            0x19: "ru",
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


# =============================
# i18n (FULL GLOBAL)
# =============================
class I18N:
    SUPPORTED = ["en", "ru", "ja", "pl", "de", "zh"]

    # Full key set must exist in EN. Other languages can override all keys.
    BUILTIN: Dict[str, Dict[str, str]] = {
        "en": {
            "app_title": "Saonix",
            "support": f"Problems / questions / suggestions — Discord: {SUPPORT_DISCORD}",

            "loader_title": "Starting Saonix…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_step_version": "Checking version…",
            "loader_step_icon": "Checking icon…",
            "loader_step_ready": "Launching UI…",

            "nav_record": "● Record",
            "nav_library": "📚 Library",
            "nav_settings": "⚙ Settings",

            "status_ready": "Ready",
            "status_recording": "● Recording…",
            "status_playing": "▶ Playing…",

            "record_title": "Record",
            "rec_start": "● Start recording",
            "rec_stop": "■ Stop recording",
            "rec_play": "▶ Play",
            "rec_stop_play": "⏹ Stop",
            "rec_save": "💾 Save",
            "rec_save_label": "Save name:",
            "rec_events": "Events:",
            "rec_hint": "Tip: set hotkeys in Settings.",

            "library_title": "Library",
            "search_ph": "Search…",
            "btn_load": "Load",
            "btn_delete": "Delete",
            "btn_rename": "Rename",
            "btn_clone": "Clone",
            "btn_export": "Export JSON",
            "btn_import": "Import JSON",
            "btn_play_selected": "▶ Play selected",

            "settings_title": "Settings",
            "appearance": "Appearance",
            "theme_dark": "Dark",
            "theme_light": "Light",
            "language": "Language",

            "playback": "Playback",
            "repeat": "Repeat (times)",
            "loop": "Loop (sec)",
            "speed": "Speed",
            "delay": "Start delay (sec)",
            "apply": "Apply",
            "reset": "Reset",

            "hotkeys": "Hotkeys",
            "hk_rec": "Start record",
            "hk_stoprec": "Stop record",
            "hk_play": "Play loaded",
            "hk_stop": "Stop playing",
            "hk_apply": "Apply hotkeys",

            "binds_title": "Binds",
            "bind": "Bind:",
            "bind_ph": "F6 or Ctrl+Alt+F6",
            "bind_set": "Set",
            "bind_remove": "Remove",
            "binds_none": "(no binds)",

            "dialogs_title": "Saonix",
            "save_name_warn": "Enter macro name.",
            "no_events_warn": "No events. Record a macro first.",
            "overwrite_q": "Macro already exists. Overwrite?",
            "select_macro_warn": "Select a macro.",
            "delete_q": "Delete macro?",
            "rename_prompt": "New name:",
            "clone_prompt": "Clone name:",
            "invalid_hotkey": "Invalid hotkey format. Example: F6 or Ctrl+Alt+F6",
            "import_ok": "Imported.",
            "export_ok": "Exported.",
            "saved": "Saved",
            "loaded": "Loaded",
            "deleted": "Deleted",
            "renamed": "Renamed",
            "cloned": "Cloned",
            "error": "Error",
            "empty": "(empty)",
            "preview": "Preview",
            "version_line": "Version",
            "remote_line": "Remote",
            "update_available": "Update available.",
        },
        "ru": {
            "app_title": "Saonix",
            "support": f"Проблемы / вопросы / предложения — Discord: {SUPPORT_DISCORD}",

            "loader_title": "Запуск Saonix…",
            "loader_langs": "Языки: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_step_version": "Проверка версии…",
            "loader_step_icon": "Проверка иконки…",
            "loader_step_ready": "Запуск интерфейса…",

            "nav_record": "● Запись",
            "nav_library": "📚 Библиотека",
            "nav_settings": "⚙ Настройки",

            "status_ready": "Готово",
            "status_recording": "● Запись…",
            "status_playing": "▶ Воспроизведение…",

            "record_title": "Запись",
            "rec_start": "● Начать запись",
            "rec_stop": "■ Остановить запись",
            "rec_play": "▶ Воспроизвести",
            "rec_stop_play": "⏹ Остановить",
            "rec_save": "💾 Сохранить",
            "rec_save_label": "Имя сохранения:",
            "rec_events": "События:",
            "rec_hint": "Подсказка: хоткеи в Настройках.",

            "library_title": "Библиотека",
            "search_ph": "Поиск…",
            "btn_load": "Загрузить",
            "btn_delete": "Удалить",
            "btn_rename": "Переименовать",
            "btn_clone": "Клонировать",
            "btn_export": "Экспорт JSON",
            "btn_import": "Импорт JSON",
            "btn_play_selected": "▶ Воспроизвести выбранный",

            "settings_title": "Настройки",
            "appearance": "Тема",
            "theme_dark": "Тёмная",
            "theme_light": "Светлая",
            "language": "Язык",

            "playback": "Воспроизведение",
            "repeat": "Повтор (раз)",
            "loop": "Цикл (сек)",
            "speed": "Скорость",
            "delay": "Задержка старта (сек)",
            "apply": "Применить",
            "reset": "Сброс",

            "hotkeys": "Хоткеи",
            "hk_rec": "Старт записи",
            "hk_stoprec": "Стоп записи",
            "hk_play": "Пуск загруженного",
            "hk_stop": "Стоп воспроизведения",
            "hk_apply": "Применить хоткеи",

            "binds_title": "Бинды",
            "bind": "Бинд:",
            "bind_ph": "F6 или Ctrl+Alt+F6",
            "bind_set": "Назначить",
            "bind_remove": "Снять",
            "binds_none": "(биндов нет)",

            "dialogs_title": "Saonix",
            "save_name_warn": "Введи имя макроса.",
            "no_events_warn": "Нет событий. Сначала запиши макрос.",
            "overwrite_q": "Макрос уже существует. Перезаписать?",
            "select_macro_warn": "Выбери макрос.",
            "delete_q": "Удалить макрос?",
            "rename_prompt": "Новое имя:",
            "clone_prompt": "Имя копии:",
            "invalid_hotkey": "Неверный формат. Пример: F6 или Ctrl+Alt+F6",
            "import_ok": "Импортировано.",
            "export_ok": "Экспортировано.",
            "saved": "Сохранено",
            "loaded": "Загружено",
            "deleted": "Удалено",
            "renamed": "Переименовано",
            "cloned": "Клонировано",
            "error": "Ошибка",
            "empty": "(пусто)",
            "preview": "Предпросмотр",
            "version_line": "Версия",
            "remote_line": "Удалённая",
            "update_available": "Доступно обновление.",
        },
        "ja": {
            "app_title": "Saonix",
            "support": f"問題 / 質問 / 提案 — Discord: {SUPPORT_DISCORD}",

            "loader_title": "Saonix を起動中…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_step_version": "バージョン確認中…",
            "loader_step_icon": "アイコン確認中…",
            "loader_step_ready": "UI を起動中…",

            "nav_record": "● 記録",
            "nav_library": "📚 ライブラリ",
            "nav_settings": "⚙ 設定",

            "status_ready": "準備完了",
            "status_recording": "● 記録中…",
            "status_playing": "▶ 再生中…",

            "record_title": "記録",
            "rec_start": "● 記録開始",
            "rec_stop": "■ 記録停止",
            "rec_play": "▶ 再生",
            "rec_stop_play": "⏹ 停止",
            "rec_save": "💾 保存",
            "rec_save_label": "保存名:",
            "rec_events": "イベント:",
            "rec_hint": "ヒント: ホットキーは設定で変更できます。",

            "library_title": "ライブラリ",
            "search_ph": "検索…",
            "btn_load": "読み込み",
            "btn_delete": "削除",
            "btn_rename": "名前変更",
            "btn_clone": "複製",
            "btn_export": "JSON 書き出し",
            "btn_import": "JSON 読み込み",
            "btn_play_selected": "▶ 選択を再生",

            "settings_title": "設定",
            "appearance": "外観",
            "theme_dark": "ダーク",
            "theme_light": "ライト",
            "language": "言語",

            "playback": "再生",
            "repeat": "繰り返し(回)",
            "loop": "ループ(秒)",
            "speed": "速度",
            "delay": "開始遅延(秒)",
            "apply": "適用",
            "reset": "リセット",

            "hotkeys": "ホットキー",
            "hk_rec": "記録開始",
            "hk_stoprec": "記録停止",
            "hk_play": "読み込みを再生",
            "hk_stop": "再生停止",
            "hk_apply": "ホットキー適用",

            "binds_title": "割り当て",
            "bind": "キー割り当て:",
            "bind_ph": "F6 または Ctrl+Alt+F6",
            "bind_set": "設定",
            "bind_remove": "解除",
            "binds_none": "(なし)",

            "dialogs_title": "Saonix",
            "save_name_warn": "マクロ名を入力してください。",
            "no_events_warn": "イベントがありません。まず記録してください。",
            "overwrite_q": "同名マクロがあります。上書きしますか？",
            "select_macro_warn": "マクロを選択してください。",
            "delete_q": "マクロを削除しますか？",
            "rename_prompt": "新しい名前:",
            "clone_prompt": "複製名:",
            "invalid_hotkey": "ホットキー形式が無効です。例: F6 または Ctrl+Alt+F6",
            "import_ok": "読み込み完了。",
            "export_ok": "書き出し完了。",
            "saved": "保存しました",
            "loaded": "読み込みました",
            "deleted": "削除しました",
            "renamed": "変更しました",
            "cloned": "複製しました",
            "error": "エラー",
            "empty": "(空)",
            "preview": "プレビュー",
            "version_line": "バージョン",
            "remote_line": "リモート",
            "update_available": "更新があります。",
        },
        "pl": {
            "app_title": "Saonix",
            "support": f"Problemy / pytania / propozycje — Discord: {SUPPORT_DISCORD}",

            "loader_title": "Uruchamianie Saonix…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_step_version": "Sprawdzanie wersji…",
            "loader_step_icon": "Sprawdzanie ikony…",
            "loader_step_ready": "Uruchamianie UI…",

            "nav_record": "● Nagrywanie",
            "nav_library": "📚 Biblioteka",
            "nav_settings": "⚙ Ustawienia",

            "status_ready": "Gotowe",
            "status_recording": "● Nagrywanie…",
            "status_playing": "▶ Odtwarzanie…",

            "record_title": "Nagrywanie",
            "rec_start": "● Start nagrywania",
            "rec_stop": "■ Stop nagrywania",
            "rec_play": "▶ Odtwórz",
            "rec_stop_play": "⏹ Zatrzymaj",
            "rec_save": "💾 Zapisz",
            "rec_save_label": "Nazwa zapisu:",
            "rec_events": "Zdarzenia:",
            "rec_hint": "Wskazówka: hotkeye ustawisz w Ustawieniach.",

            "library_title": "Biblioteka",
            "search_ph": "Szukaj…",
            "btn_load": "Wczytaj",
            "btn_delete": "Usuń",
            "btn_rename": "Zmień nazwę",
            "btn_clone": "Klonuj",
            "btn_export": "Eksport JSON",
            "btn_import": "Import JSON",
            "btn_play_selected": "▶ Odtwórz zaznaczone",

            "settings_title": "Ustawienia",
            "appearance": "Wygląd",
            "theme_dark": "Ciemny",
            "theme_light": "Jasny",
            "language": "Język",

            "playback": "Odtwarzanie",
            "repeat": "Powtórz (razy)",
            "loop": "Pętla (sek)",
            "speed": "Szybkość",
            "delay": "Opóźnienie startu (sek)",
            "apply": "Zastosuj",
            "reset": "Resetuj",

            "hotkeys": "Hotkeye",
            "hk_rec": "Start nagrywania",
            "hk_stoprec": "Stop nagrywania",
            "hk_play": "Odtwórz wczytane",
            "hk_stop": "Zatrzymaj odtwarzanie",
            "hk_apply": "Zastosuj hotkeye",

            "binds_title": "Skróty",
            "bind": "Skrót:",
            "bind_ph": "F6 lub Ctrl+Alt+F6",
            "bind_set": "Ustaw",
            "bind_remove": "Usuń",
            "binds_none": "(brak)",

            "dialogs_title": "Saonix",
            "save_name_warn": "Wpisz nazwę makra.",
            "no_events_warn": "Brak zdarzeń. Najpierw nagraj makro.",
            "overwrite_q": "Makro już istnieje. Nadpisać?",
            "select_macro_warn": "Wybierz makro.",
            "delete_q": "Usunąć makro?",
            "rename_prompt": "Nowa nazwa:",
            "clone_prompt": "Nazwa klonu:",
            "invalid_hotkey": "Zły format skrótu. Przykład: F6 lub Ctrl+Alt+F6",
            "import_ok": "Zaimportowano.",
            "export_ok": "Wyeksportowano.",
            "saved": "Zapisano",
            "loaded": "Wczytano",
            "deleted": "Usunięto",
            "renamed": "Zmieniono nazwę",
            "cloned": "Sklonowano",
            "error": "Błąd",
            "empty": "(pusto)",
            "preview": "Podgląd",
            "version_line": "Wersja",
            "remote_line": "Zdalna",
            "update_available": "Dostępna aktualizacja.",
        },
        "de": {
            "app_title": "Saonix",
            "support": f"Probleme / Fragen / Vorschläge — Discord: {SUPPORT_DISCORD}",

            "loader_title": "Saonix wird gestartet…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_step_version": "Version wird geprüft…",
            "loader_step_icon": "Icon wird geprüft…",
            "loader_step_ready": "UI wird gestartet…",

            "nav_record": "● Aufnahme",
            "nav_library": "📚 Bibliothek",
            "nav_settings": "⚙ Einstellungen",

            "status_ready": "Bereit",
            "status_recording": "● Aufnahme…",
            "status_playing": "▶ Wiedergabe…",

            "record_title": "Aufnahme",
            "rec_start": "● Aufnahme starten",
            "rec_stop": "■ Aufnahme stoppen",
            "rec_play": "▶ Abspielen",
            "rec_stop_play": "⏹ Stop",
            "rec_save": "💾 Speichern",
            "rec_save_label": "Name speichern:",
            "rec_events": "Ereignisse:",
            "rec_hint": "Tipp: Hotkeys in Einstellungen setzen.",

            "library_title": "Bibliothek",
            "search_ph": "Suchen…",
            "btn_load": "Laden",
            "btn_delete": "Löschen",
            "btn_rename": "Umbenennen",
            "btn_clone": "Klonen",
            "btn_export": "JSON exportieren",
            "btn_import": "JSON importieren",
            "btn_play_selected": "▶ Auswahl abspielen",

            "settings_title": "Einstellungen",
            "appearance": "Darstellung",
            "theme_dark": "Dunkel",
            "theme_light": "Hell",
            "language": "Sprache",

            "playback": "Wiedergabe",
            "repeat": "Wiederholen (Anzahl)",
            "loop": "Schleife (Sek)",
            "speed": "Geschwindigkeit",
            "delay": "Startverzögerung (Sek)",
            "apply": "Anwenden",
            "reset": "Zurücksetzen",

            "hotkeys": "Hotkeys",
            "hk_rec": "Aufnahme starten",
            "hk_stoprec": "Aufnahme stoppen",
            "hk_play": "Geladenes abspielen",
            "hk_stop": "Wiedergabe stoppen",
            "hk_apply": "Hotkeys anwenden",

            "binds_title": "Belegungen",
            "bind": "Belegung:",
            "bind_ph": "F6 oder Ctrl+Alt+F6",
            "bind_set": "Setzen",
            "bind_remove": "Entfernen",
            "binds_none": "(keine)",

            "dialogs_title": "Saonix",
            "save_name_warn": "Makronamen eingeben.",
            "no_events_warn": "Keine Ereignisse. Zuerst aufnehmen.",
            "overwrite_q": "Makro existiert bereits. Überschreiben?",
            "select_macro_warn": "Makro auswählen.",
            "delete_q": "Makro löschen?",
            "rename_prompt": "Neuer Name:",
            "clone_prompt": "Klonname:",
            "invalid_hotkey": "Ungültiges Hotkey-Format. Beispiel: F6 oder Ctrl+Alt+F6",
            "import_ok": "Importiert.",
            "export_ok": "Exportiert.",
            "saved": "Gespeichert",
            "loaded": "Geladen",
            "deleted": "Gelöscht",
            "renamed": "Umbenannt",
            "cloned": "Geklont",
            "error": "Fehler",
            "empty": "(leer)",
            "preview": "Vorschau",
            "version_line": "Version",
            "remote_line": "Remote",
            "update_available": "Update verfügbar.",
        },
        "zh": {
            "app_title": "Saonix",
            "support": f"问题 / 咨询 / 建议 — Discord: {SUPPORT_DISCORD}",

            "loader_title": "正在启动 Saonix…",
            "loader_langs": "Languages: English, Русский, 日本語, Polski, Deutsch, 中文",
            "loader_step_version": "正在检查版本…",
            "loader_step_icon": "正在检查图标…",
            "loader_step_ready": "正在启动界面…",

            "nav_record": "● 录制",
            "nav_library": "📚 库",
            "nav_settings": "⚙ 设置",

            "status_ready": "就绪",
            "status_recording": "● 录制中…",
            "status_playing": "▶ 播放中…",

            "record_title": "录制",
            "rec_start": "● 开始录制",
            "rec_stop": "■ 停止录制",
            "rec_play": "▶ 播放",
            "rec_stop_play": "⏹ 停止",
            "rec_save": "💾 保存",
            "rec_save_label": "保存名称:",
            "rec_events": "事件:",
            "rec_hint": "提示：在设置里配置热键。",

            "library_title": "库",
            "search_ph": "搜索…",
            "btn_load": "加载",
            "btn_delete": "删除",
            "btn_rename": "重命名",
            "btn_clone": "克隆",
            "btn_export": "导出 JSON",
            "btn_import": "导入 JSON",
            "btn_play_selected": "▶ 播放所选",

            "settings_title": "设置",
            "appearance": "外观",
            "theme_dark": "深色",
            "theme_light": "浅色",
            "language": "语言",

            "playback": "播放",
            "repeat": "重复(次)",
            "loop": "循环(秒)",
            "speed": "速度",
            "delay": "启动延迟(秒)",
            "apply": "应用",
            "reset": "重置",

            "hotkeys": "热键",
            "hk_rec": "开始录制",
            "hk_stoprec": "停止录制",
            "hk_play": "播放已加载",
            "hk_stop": "停止播放",
            "hk_apply": "应用热键",

            "binds_title": "绑定",
            "bind": "绑定:",
            "bind_ph": "F6 或 Ctrl+Alt+F6",
            "bind_set": "设置",
            "bind_remove": "移除",
            "binds_none": "(无)",

            "dialogs_title": "Saonix",
            "save_name_warn": "请输入宏名称。",
            "no_events_warn": "没有事件。请先录制宏。",
            "overwrite_q": "宏已存在，是否覆盖？",
            "select_macro_warn": "请选择宏。",
            "delete_q": "删除宏？",
            "rename_prompt": "新名称:",
            "clone_prompt": "克隆名称:",
            "invalid_hotkey": "热键格式无效。例：F6 或 Ctrl+Alt+F6",
            "import_ok": "已导入。",
            "export_ok": "已导出。",
            "saved": "已保存",
            "loaded": "已加载",
            "deleted": "已删除",
            "renamed": "已重命名",
            "cloned": "已克隆",
            "error": "错误",
            "empty": "(空)",
            "preview": "预览",
            "version_line": "版本",
            "remote_line": "远程",
            "update_available": "有可用更新。",
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


# =============================
# Net cache + downloader
# =============================
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


def http_get_bytes(url: str, timeout: float = 8.0, etag_key: Optional[str] = None) -> Tuple[Optional[bytes], str]:
    """
    Returns (data, status):
      - (None, "not_modified") if 304
      - (bytes, "ok") if downloaded
      - (None, "error") on error
    """
    try:
        import urllib.request
        import urllib.error

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
                    return None, "not_modified"
                et = r.headers.get("ETag")
                if etag_key and et:
                    c[f"etag:{etag_key}"] = et
                    _cache_set(c)
                return r.read(), "ok"
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None, "not_modified"
            return None, "error"
        except Exception:
            return None, "error"
    except Exception:
        return None, "error"


def ensure_icon_png(progress: Optional[Callable[[float], None]] = None) -> str:
    ensure_dir(DIR_APP)

    c = _cache_get()
    last_url = c.get("icon_url")
    if last_url != GITHUB_ICON_URL:
        c.pop("etag:icon", None)
        c["icon_url"] = GITHUB_ICON_URL
        _cache_set(c)

    if os.path.exists(ICON_PNG):
        if progress:
            progress(0.55)
        data, status = http_get_bytes(GITHUB_ICON_URL, etag_key="icon")
        if status == "not_modified":
            return ICON_PNG
        if isinstance(data, (bytes, bytearray)) and len(data) > 100:
            try:
                with open(ICON_PNG, "wb") as f:
                    f.write(data)
            except Exception:
                pass
        return ICON_PNG

    if progress:
        progress(0.55)
    data, status = http_get_bytes(GITHUB_ICON_URL, etag_key="icon")
    if isinstance(data, (bytes, bytearray)) and len(data) > 100:
        try:
            with open(ICON_PNG, "wb") as f:
                f.write(data)
        except Exception:
            pass
    return ICON_PNG


def check_remote_version(progress: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
    if progress:
        progress(0.25)
    remote = http_get_text(GITHUB_VERSION_URL)
    if not remote:
        return {"ok": True, "remote": None, "update": False}
    remote = remote.strip()
    return {"ok": True, "remote": remote, "update": (remote != APP_VERSION)}


# =============================
# Hotkey parsing
# =============================
def normalize_hotkey(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None
    t = t.replace("<", "").replace(">", "")

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


# =============================
# DB
# =============================
class MacroDB:
    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 5, "macros": {}, "binds": {}, "settings": {}}
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
        b = self.data.get("binds", {})
        return dict(b) if isinstance(b, dict) else {}

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


# =============================
# Engine
# =============================
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


# =============================
# Hotkeys
# =============================
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


# =============================
# Splash loader (GUI)
# =============================
class Splash(ctk.CTkToplevel):
    def __init__(self, master, i18n: I18N, png_path: Optional[str] = None):
        super().__init__(master)
        self.i18n = i18n
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        ctk.set_appearance_mode("Dark")
        self.configure(fg_color="#0b0f16")

        w, h = 640, 360
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

        self.status_var = ctk.StringVar(value=self.i18n.t("loader_step_version"))
        self.lbl_status = ctk.CTkLabel(self.card, textvariable=self.status_var)
        self.lbl_status.grid(row=3, column=0, pady=(0, 10))

        self.pb = ctk.CTkProgressBar(self.card)
        self.pb.grid(row=4, column=0, padx=48, pady=(0, 8), sticky="ew")
        self.pb.set(0.02)

        self.small = ctk.CTkLabel(self.card, text=self.i18n.t("support"), wraplength=540, justify="center")
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


# =============================
# App UI
# =============================
class SaonixApp(ctk.CTk):
    def __init__(self, i18n: I18N, boot_info: Dict[str, Any]):
        super().__init__()
        self.i18n = i18n
        self.boot_info = boot_info

        self.db = MacroDB(DB_FILE)

        saved = self.db.get_settings()
        theme = saved.get("appearance", "Dark")
        if theme not in ("Dark", "Light"):
            theme = "Dark"

        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme(saved.get("color_theme", "dark-blue"))

        self.title(self.i18n.t("app_title"))
        self.geometry("1180x720")
        self.minsize(1080, 640)

        # icon
        self._ico_ref = None
        try:
            if os.path.exists(ICON_PNG):
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

        # vars
        self.repeat_var = ctk.StringVar(value=str(saved.get("repeat", 1)))
        self.loop_var = ctk.StringVar(value=str(saved.get("loop_seconds", 0)))
        self.speed_var = ctk.StringVar(value=str(saved.get("speed", 1.0)))
        self.delay_var = ctk.StringVar(value=str(saved.get("start_delay", 0.0)))

        self.hk_rec_var = ctk.StringVar(value=str(saved.get("hk_rec", "Ctrl+Alt+1")))
        self.hk_stoprec_var = ctk.StringVar(value=str(saved.get("hk_stoprec", "Ctrl+Alt+2")))
        self.hk_play_var = ctk.StringVar(value=str(saved.get("hk_play", "Ctrl+Alt+3")))
        self.hk_stop_var = ctk.StringVar(value=str(saved.get("hk_stop", "Ctrl+Alt+4")))

        self.selected_macro: Optional[str] = None

        # layout
        self._active_page = "record"

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=18)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=14, pady=14)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(99, weight=1)

        self.lbl_brand = ctk.CTkLabel(self.sidebar, text="", font=ctk.CTkFont(size=26, weight="bold"))
        self.lbl_brand.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        self.btn_record = ctk.CTkButton(self.sidebar, text="", command=lambda: self.show_page("record"))
        self.btn_library = ctk.CTkButton(self.sidebar, text="", command=lambda: self.show_page("library"))
        self.btn_settings = ctk.CTkButton(self.sidebar, text="", command=lambda: self.show_page("settings"))
        self.btn_record.grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        self.btn_library.grid(row=3, column=0, padx=16, pady=8, sticky="ew")
        self.btn_settings.grid(row=4, column=0, padx=16, pady=8, sticky="ew")

        self.lbl_lang_title = ctk.CTkLabel(self.sidebar, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_lang_title.grid(row=6, column=0, padx=16, pady=(18, 6), sticky="w")

        self.lang_menu = ctk.CTkOptionMenu(self.sidebar, values=["auto"] + I18N.SUPPORTED, command=self.set_lang)
        self.lang_choice = saved.get("lang", "auto")
        if self.lang_choice not in (["auto"] + I18N.SUPPORTED):
            self.lang_choice = "auto"
        self.lang_menu.set(self.lang_choice)
        self.lang_menu.grid(row=7, column=0, padx=16, pady=(0, 10), sticky="ew")

        self.lbl_theme_title = ctk.CTkLabel(self.sidebar, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_theme_title.grid(row=8, column=0, padx=16, pady=(6, 6), sticky="w")

        self.theme_menu = ctk.CTkOptionMenu(self.sidebar, values=["Dark", "Light"], command=self.set_theme)
        self.theme_menu.set(theme)
        self.theme_menu.grid(row=9, column=0, padx=16, pady=(0, 10), sticky="ew")

        self.support_lbl = ctk.CTkLabel(self.sidebar, text="", wraplength=220, justify="left")
        self.support_lbl.grid(row=98, column=0, padx=16, pady=14, sticky="sw")

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

        self.page_record = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        self.page_library = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        self.page_settings = ctk.CTkFrame(self.content, corner_radius=18, fg_color="transparent")
        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid(row=0, column=0, sticky="nsew")
            p.grid_remove()

        self._widgets_i18n: List[Tuple[Any, str, str]] = []  # (widget, property, key)

        self.build_record_page()
        self.build_library_page()
        self.build_settings_page()

        self.rebuild_hotkeys()
        self.after(200, self.tick)

        self.apply_texts()  # sets all UI text from i18n
        self.show_page("record")

        if self.boot_info.get("remote"):
            if self.boot_info.get("update"):
                self.logger.warn(f"Remote version {self.boot_info['remote']} available (local {APP_VERSION})")
            else:
                self.logger.info(f"Version OK: {APP_VERSION}")

    def i_bind(self, widget, prop: str, key: str):
        self._widgets_i18n.append((widget, prop, key))

    def apply_texts(self):
        # window + sidebar
        self.title(self.i18n.t("app_title"))
        self.lbl_brand.configure(text=self.i18n.t("app_title"))

        self.btn_record.configure(text=self.i18n.t("nav_record"))
        self.btn_library.configure(text=self.i18n.t("nav_library"))
        self.btn_settings.configure(text=self.i18n.t("nav_settings"))

        self.lbl_lang_title.configure(text=self.i18n.t("language"))
        self.lbl_theme_title.configure(text=self.i18n.t("appearance"))

        # theme names shown in menu should be localized, but values must remain Dark/Light internally
        # keep menu values as Dark/Light, but label above is localized; it’s stable and avoids breakages.

        self.support_lbl.configure(text=self.i18n.t("support"))

        # pages / controls
        for w, prop, key in self._widgets_i18n:
            try:
                txt = self.i18n.t(key)
                if prop == "text":
                    w.configure(text=txt)
                elif prop == "placeholder":
                    w.configure(placeholder_text=txt)
            except Exception:
                pass

        # header title refresh
        self.show_page(self._active_page)

    def set_lang(self, lang: str):
        s = self.db.get_settings()
        s["lang"] = lang
        self.db.set_settings(s)
        self.i18n.load(lang)
        self.apply_texts()
        self.refresh_library()

    def set_theme(self, theme: str):
        if theme not in ("Dark", "Light"):
            return
        ctk.set_appearance_mode(theme)
        s = self.db.get_settings()
        s["appearance"] = theme
        self.db.set_settings(s)

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

    def show_page(self, which: str):
        self._active_page = which
        for p in (self.page_record, self.page_library, self.page_settings):
            p.grid_remove()
        if which == "record":
            self.page_record.grid()
            self.h_title.configure(text=self.i18n.t("record_title"))
        elif which == "library":
            self.page_library.grid()
            self.h_title.configure(text=self.i18n.t("library_title"))
        else:
            self.page_settings.grid()
            self.h_title.configure(text=self.i18n.t("settings_title"))

    # ---- Record page ----
    def build_record_page(self):
        self.page_record.grid_columnconfigure(0, weight=1)
        self.page_record.grid_columnconfigure(1, weight=1)
        self.page_record.grid_rowconfigure(2, weight=1)

        card = ctk.CTkFrame(self.page_record, corner_radius=18)
        card.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=(16, 10))

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(14, 6))
        self.btn_start = ctk.CTkButton(row1, text="", command=self.engine.start_recording)
        self.btn_stop = ctk.CTkButton(row1, text="", command=self.engine.stop_recording)
        self.btn_start.pack(side="left", padx=6)
        self.btn_stop.pack(side="left", padx=6)
        self.i_bind(self.btn_start, "text", "rec_start")
        self.i_bind(self.btn_stop, "text", "rec_stop")

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=6)
        self.btn_play = ctk.CTkButton(row2, text="", command=self.play_from_ui)
        self.btn_stopplay = ctk.CTkButton(row2, text="", command=self.engine.stop_playing)
        self.btn_play.pack(side="left", padx=6)
        self.btn_stopplay.pack(side="left", padx=6)
        self.i_bind(self.btn_play, "text", "rec_play")
        self.i_bind(self.btn_stopplay, "text", "rec_stop_play")

        self.save_label = ctk.CTkLabel(card, text="")
        self.save_label.pack(anchor="w", padx=16, pady=(12, 4))
        self.i_bind(self.save_label, "text", "rec_save_label")

        self.save_name = ctk.StringVar(value="New macro")
        self.save_entry = ctk.CTkEntry(card, textvariable=self.save_name)
        self.save_entry.pack(fill="x", padx=16, pady=6)

        self.btn_save = ctk.CTkButton(card, text="", command=self.save_current_macro)
        self.btn_save.pack(fill="x", padx=16, pady=(6, 16))
        self.i_bind(self.btn_save, "text", "rec_save")

        hint = ctk.CTkFrame(self.page_record, corner_radius=18)
        hint.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=(16, 10))
        self.hint_text = ctk.CTkLabel(hint, text="", justify="left", wraplength=420)
        self.hint_text.pack(anchor="w", padx=16, pady=16)
        self.i_bind(self.hint_text, "text", "rec_hint")

        self.log_box = ctk.CTkTextbox(self.page_record, height=220, corner_radius=18)
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 10))

    def play_from_ui(self):
        s = self.current_play_settings()
        self.engine.play(s["repeat"], s["loop_seconds"], s["speed"], s["start_delay"])

    def save_current_macro(self):
        name = self.save_name.get().strip()
        if not name:
            messagebox.showwarning(self.i18n.t("dialogs_title"), self.i18n.t("save_name_warn"))
            return
        if not self.engine.events:
            messagebox.showwarning(self.i18n.t("dialogs_title"), self.i18n.t("no_events_warn"))
            return

        if self.db.exists(name):
            if not messagebox.askyesno(self.i18n.t("dialogs_title"), self.i18n.t("overwrite_q")):
                return

        settings = self.current_play_settings()
        events = [asdict(e) for e in self.engine.events]
        self.db.put(name, events, settings)
        self.logger.info(f"{self.i18n.t('saved')}: {name} (events: {len(events)})")
        self.refresh_library()
        self.show_page("library")

    # ---- Library page ----
    def build_library_page(self):
        self.page_library.grid_columnconfigure(0, weight=1)
        self.page_library.grid_columnconfigure(1, weight=2)
        self.page_library.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self.page_library, corner_radius=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=16)
        left.grid_rowconfigure(3, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(left, textvariable=self.search_var, placeholder_text="")
        self.search_entry.grid(row=1, column=0, padx=16, pady=(16, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_library())
        self.i_bind(self.search_entry, "placeholder", "search_ph")

        self.macros_scroll = ctk.CTkScrollableFrame(left, corner_radius=14)
        self.macros_scroll.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="nsew")

        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="ew")
        btns.grid_columnconfigure((0, 1), weight=1)

        self.btn_load = ctk.CTkButton(btns, text="", command=self.load_selected)
        self.btn_delete = ctk.CTkButton(btns, text="", command=self.delete_selected)
        self.btn_load.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.btn_delete.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        self.i_bind(self.btn_load, "text", "btn_load")
        self.i_bind(self.btn_delete, "text", "btn_delete")

        right = ctk.CTkFrame(self.page_library, corner_radius=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 16), pady=16)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.preview_title = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=18, weight="bold"))
        self.preview_title.grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")

        self.preview_label = ctk.CTkLabel(right, text="", font=ctk.CTkFont(weight="bold"))
        self.preview_label.grid(row=1, column=0, padx=16, pady=(0, 6), sticky="w")
        self.i_bind(self.preview_label, "text", "preview")

        self.preview_box = ctk.CTkTextbox(right, corner_radius=14)
        self.preview_box.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.refresh_library()

    def refresh_library(self):
        q = self.search_var.get().strip().lower()

        for child in self.macros_scroll.winfo_children():
            try: child.destroy()
            except Exception: pass

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
            messagebox.showwarning(self.i18n.t("dialogs_title"), self.i18n.t("select_macro_warn"))
            return
        item = self.db.get(name)
        if not item:
            return

        ev_raw = item.get("events", [])
        events: List[Event] = []
        for e in ev_raw:
            try:
                events.append(Event(**e))
            except Exception:
                pass
        self.engine.events = events

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
            messagebox.showwarning(self.i18n.t("dialogs_title"), self.i18n.t("select_macro_warn"))
            return
        if not messagebox.askyesno(self.i18n.t("dialogs_title"), self.i18n.t("delete_q")):
            return
        self.db.delete(name)
        self.logger.info(f"{self.i18n.t('deleted')}: {name}")
        self.selected_macro = None
        self.refresh_library()

    # ---- Settings page ----
    def build_settings_page(self):
        wrap = ctk.CTkFrame(self.page_settings, corner_radius=18)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)
        wrap.grid_columnconfigure(1, weight=1)

        self.lbl_playback = ctk.CTkLabel(wrap, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_playback.grid(row=0, column=0, columnspan=2, padx=14, pady=(10, 6), sticky="w")
        self.i_bind(self.lbl_playback, "text", "playback")

        def row(r: int, label_key: str, var: ctk.StringVar, ph: str):
            lab = ctk.CTkLabel(wrap, text="")
            ent = ctk.CTkEntry(wrap, textvariable=var, placeholder_text=ph)
            lab.grid(row=r, column=0, padx=14, pady=10, sticky="w")
            ent.grid(row=r, column=1, padx=14, pady=10, sticky="ew")
            self.i_bind(lab, "text", label_key)

        row(1, "repeat", self.repeat_var, "e.g. 5")
        row(2, "loop", self.loop_var, "e.g. 60")
        row(3, "speed", self.speed_var, "0.5 / 1.0 / 2.0")
        row(4, "delay", self.delay_var, "e.g. 3")

        self.lbl_hotkeys = ctk.CTkLabel(wrap, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_hotkeys.grid(row=5, column=0, columnspan=2, padx=14, pady=(18, 6), sticky="w")
        self.i_bind(self.lbl_hotkeys, "text", "hotkeys")

        def hkrow(r: int, label_key: str, var: ctk.StringVar, ph: str):
            lab = ctk.CTkLabel(wrap, text="")
            ent = ctk.CTkEntry(wrap, textvariable=var, placeholder_text=ph)
            lab.grid(row=r, column=0, padx=14, pady=10, sticky="w")
            ent.grid(row=r, column=1, padx=14, pady=10, sticky="ew")
            self.i_bind(lab, "text", label_key)

        hkrow(6, "hk_rec", self.hk_rec_var, "Ctrl+Alt+1")
        hkrow(7, "hk_stoprec", self.hk_stoprec_var, "Ctrl+Alt+2")
        hkrow(8, "hk_play", self.hk_play_var, "Ctrl+Alt+3")
        hkrow(9, "hk_stop", self.hk_stop_var, "Ctrl+Alt+4")

        bar = ctk.CTkFrame(wrap, fg_color="transparent")
        bar.grid(row=10, column=0, columnspan=2, padx=14, pady=(12, 0), sticky="ew")

        self.btn_apply = ctk.CTkButton(bar, text="", command=self.apply_settings)
        self.btn_hk_apply = ctk.CTkButton(bar, text="", command=self.apply_hotkeys)
        self.btn_apply.pack(side="left", padx=6)
        self.btn_hk_apply.pack(side="left", padx=6)
        self.i_bind(self.btn_apply, "text", "apply")
        self.i_bind(self.btn_hk_apply, "text", "hk_apply")

        self.ver_lbl = ctk.CTkLabel(wrap, text="")
        self.ver_lbl.grid(row=11, column=0, columnspan=2, padx=14, pady=(18, 6), sticky="w")

        self.support2 = ctk.CTkLabel(wrap, text="", wraplength=900, justify="left")
        self.support2.grid(row=12, column=0, columnspan=2, padx=14, pady=(0, 10), sticky="w")
        self.i_bind(self.support2, "text", "support")

        self.refresh_version_line()

    def refresh_version_line(self):
        info = self.boot_info
        line = f"{self.i18n.t('version_line')}: {APP_VERSION}"
        if info.get("remote"):
            line += f" | {self.i18n.t('remote_line')}: {info['remote']}"
            if info.get("update"):
                line += f" — {self.i18n.t('update_available')}"
        self.ver_lbl.configure(text=line)

    def apply_settings(self):
        self.persist_settings()
        self.refresh_version_line()
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


# =============================
# Bootstrap
# =============================
def main():
    splash = None
    root = None
    try:
        # load db settings for language
        db = MacroDB(DB_FILE)
        saved = db.get_settings()
        lang = saved.get("lang", "auto")

        i18n = I18N(lang)

        # hidden root for splash
        ctk.set_default_color_theme(saved.get("color_theme", "dark-blue"))
        root = ctk.CTk()
        root.withdraw()

        # ensure icon (cached, no repeat download if not changed)
        if not os.path.exists(ICON_PNG):
            ensure_icon_png()

        splash = Splash(master=root, i18n=i18n, png_path=ICON_PNG)

        def setp(step_key: str, frac: float):
            if not splash:
                return
            splash.set_status(i18n.t(step_key), frac)

        # version check
        setp("loader_step_version", 0.18)
        boot_info = check_remote_version(progress=lambda f: setp("loader_step_version", f))

        # icon check/download with ETag
        setp("loader_step_icon", 0.50)
        ensure_icon_png(progress=lambda f: setp("loader_step_icon", f))

        setp("loader_step_ready", 0.92)

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
