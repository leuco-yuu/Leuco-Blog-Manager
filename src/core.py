#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leuco Blog Manager

专用于 D:/Blog/leuco blog 的 Hugo 内容管理器。
管理文章、项目、分类、系列、标签、封面、主题资源、Hugo 预览和 Git 提交。
"""

from __future__ import annotations

from contextlib import contextmanager
import calendar
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import gc
import hashlib
import json
from io import BytesIO
import math
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time as time_module
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests
import yaml
from Crypto.Cipher import AES
from PyQt6.QtCore import QDate, QObject, QPoint, QRect, QProcess, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "LeucoBlogManager"
BLOG_SITE_URL = "https://leuco-yuu.github.io/"
HUGO_PREVIEW_HOST = "127.0.0.1"
HUGO_PREVIEW_PORT = 1313
PACKAGE_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else PACKAGE_DIR
)
BUNDLED_RESOURCE_DIR = (
    Path(getattr(sys, "_MEIPASS"))
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
    else PACKAGE_DIR
)


def default_blog_root() -> Path:
    """返回当前平台合理的默认博客根目录，可用 LEUCO_BLOG_ROOT 环境变量覆盖。"""
    env = os.environ.get("LEUCO_BLOG_ROOT", "").strip()
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(r"D:\Blog\leuco blog")
    return Path.home() / "Blog" / "leuco blog"


def is_linux() -> bool:
    """判断当前是否运行在 Linux 上（包括 Kali）。"""
    return os.name == "posix" and sys.platform.startswith("linux")


def platform_config_dir() -> Path:
    """返回当前平台的配置目录。

    - Windows：沿用程序目录下的 config，兼容旧版本。
    - Linux/Kali：优先使用 XDG 配置目录；若仓库内已有旧配置，则继续沿用旧位置，
      避免丢失已有设置与加密密钥。
    """
    if is_linux():
        xdg_root = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        xdg_dir = xdg_root / "leuco-blog-manager"
        legacy = PROGRAM_DIR / "config"
        if (legacy / "config.json").exists() or (legacy / "apikey_data.bin").exists():
            return legacy
        return xdg_dir
    return PROGRAM_DIR / "config"


DEFAULT_BLOG_ROOT = default_blog_root()
CONFIG_DIR = platform_config_dir()
CONFIG_PATH = CONFIG_DIR / "config.json"
API_KEY_FILE = CONFIG_DIR / "apikey_data.bin"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IMAGE_FILTER = "Images (*.svg *.png *.jpg *.jpeg *.webp *.gif *.bmp);;All Files (*)"
TEXT_EXTS = {".md", ".yaml", ".yml", ".toml", ".json", ".html", ".css", ".js", ".svg", ".txt"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}
RESOURCE_ROOTS = [
    "assets",
    "layouts",
    "static",
    "data",
    "i18n",
    "archetypes",
    "themes/hugo-narrow/layouts",
    "themes/hugo-narrow/assets",
]


class NoDatesSafeLoader(yaml.SafeLoader):
    pass


class FrontMatterParseError(ValueError):
    """表示某个 Markdown 文件的 YAML Front Matter 无法解析。"""

    def __init__(
        self,
        source_path: Optional[Path],
        problem: str,
        line: Optional[int] = None,
        column: Optional[int] = None,
        snippet: str = "",
    ) -> None:
        self.source_path = Path(source_path) if source_path else None
        self.problem = problem.strip() or "未知 YAML 语法错误"
        self.line = line
        self.column = column
        self.snippet = snippet.rstrip()

        location = ""
        if line is not None:
            location = f"第 {line} 行"
            if column is not None:
                location += f"，第 {column} 列"

        parts = ["Front Matter YAML 格式错误"]
        if self.source_path is not None:
            parts.append(f"文件：{self.source_path}")
        if location:
            parts.append(f"位置：{location}")
        parts.append(f"原因：{self.problem}")
        if self.snippet:
            parts.append(f"附近内容：{self.snippet}")
        super().__init__("\n".join(parts))


FRONT_MATTER_AUTO_REPAIRS: List[str] = []


for ch in list("0123456789"):
    resolvers = NoDatesSafeLoader.yaml_implicit_resolvers.get(ch, [])
    NoDatesSafeLoader.yaml_implicit_resolvers[ch] = [
        item for item in resolvers if item[0] != "tag:yaml.org,2002:timestamp"
    ]


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def rename_path_with_retry(
    source: Path,
    target: Path,
    timeout: float = 12.0,
    interval: float = 0.25,
) -> None:
    """
    在 Windows 上对目录/文件重命名进行有限重试。

    Hugo、编辑器、杀毒软件或资源管理器可能短暂持有目录句柄，
    从而触发 WinError 32。这里会释放 Python 临时对象并等待句柄释放。
    """
    source = Path(source)
    target = Path(target)
    deadline = time_module.monotonic() + max(0.5, timeout)
    last_error: Optional[OSError] = None

    while True:
        try:
            source.rename(target)
            return
        except OSError as exc:
            last_error = exc
            winerror = getattr(exc, "winerror", None)
            retryable = isinstance(exc, PermissionError) or winerror in {5, 32, 33}
            if not retryable or time_module.monotonic() >= deadline:
                break
            gc.collect()
            time_module.sleep(interval)

    if last_error is None:
        raise OSError(f"无法重命名：{source} -> {target}")

    winerror = getattr(last_error, "winerror", None)
    if winerror in {5, 32, 33} or isinstance(last_error, PermissionError):
        raise PermissionError(
            f"目录或文件仍被其他程序占用，重试后仍无法重命名：\\n"
            f"{source}\\n→\\n{target}\\n\\n"
            "请关闭正在打开该目录或其中 Markdown 文件的外部编辑器、"
            "终端、文件预览窗口或其他 Hugo 进程后重试。"
        ) from last_error
    raise last_error


def program_dir() -> Path:
    return PROGRAM_DIR


def prompts_dir() -> Path:
    for candidate in (
        program_dir() / "prompts",
        PACKAGE_DIR / "prompts",
        BUNDLED_RESOURCE_DIR / "prompts",
    ):
        if candidate.exists():
            return candidate
    return program_dir() / "prompts"


def load_prompt(name: str, **values: Any) -> str:
    path = prompts_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"缺少提示词文件：{path}")
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text.strip()


def rel_path(path: Path | str, base: Optional[Path] = None) -> str:
    try:
        p = Path(path)
        if not p.is_absolute():
            return str(p).replace("\\", "/")
        b = base or program_dir()
        return os.path.relpath(p.resolve(), b.resolve()).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def safe_traceback() -> str:
    return traceback.format_exc()


def run_cmd(args: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        shell=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(" ".join(args) + "\n\n" + proc.stdout)
    return proc.stdout


def run_cmd_status(args: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> Tuple[int, str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        shell=False,
    )
    return proc.returncode, proc.stdout


def icon() -> QIcon:
    search_dirs = unique([program_dir(), BUNDLED_RESOURCE_DIR, PACKAGE_DIR])
    # Linux 上 PNG 兼容性最好（ICO 依赖 Qt 图像插件，SVG 依赖 qsvg 插件）。
    names = ("icon.ico", "icon.svg", "icon.png") if os.name == "nt" else ("icon.png", "icon.svg", "icon.ico")
    for base in search_dirs:
        for name in names:
            p = Path(base) / name
            if p.exists():
                q = QIcon(str(p))
                if not q.isNull():
                    return q
    if is_linux():
        themed = QIcon.fromTheme("applications-internet")
        if not themed.isNull():
            return themed
    return QIcon()


def build_stylesheet() -> str:
    """返回完整浅色 QSS。

    原有样式只覆盖了少数控件，Kali 等深色桌面主题下未覆盖的控件会继承
    白色前景色，与白色背景叠加形成“白字白底”。这里为所有常用控件显式指定
    前景/背景/选区颜色，保证任何 Linux 桌面环境下都可读。
    """
    return """
QMainWindow, QDialog { background: #f8fafc; }
QWidget { color: #0f172a; }

QLabel { background: transparent; color: #0f172a; }
QLabel#Title { font-size: 18px; font-weight: 800; color: #0f172a; }
QLabel#Subtitle { color: #64748b; }

QFrame#Card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }

QGroupBox {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;
    margin-top: 10px; padding: 10px 8px 8px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: #334155; font-weight: 700; background: transparent;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
QDateEdit, QTimeEdit, QDateTimeEdit, QComboBox {
    background: #ffffff; color: #0f172a;
    border: 1px solid #dbe3ef; border-radius: 6px; padding: 4px 6px;
    selection-background-color: #dbeafe; selection-color: #0f172a;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus,
QTimeEdit:focus, QDateTimeEdit:focus, QComboBox:focus {
    border-color: #2563eb;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled,
QTimeEdit:disabled, QDateTimeEdit:disabled, QComboBox:disabled {
    background: #f1f5f9; color: #94a3b8;
}
QComboBox QAbstractItemView {
    background: #ffffff; color: #0f172a; border: 1px solid #dbe3ef;
    selection-background-color: #dbeafe; selection-color: #0f172a;
}

QTableWidget, QTreeWidget, QListWidget, QTableView, QTreeView, QListView {
    background: #ffffff; color: #0f172a; alternate-background-color: #f8fafc;
    border: 1px solid #dbe3ef; border-radius: 6px;
    selection-background-color: #dbeafe; selection-color: #0f172a;
}
QTableCornerButton::section { background: #f1f5f9; border: 0; }
QHeaderView::section {
    background: #f1f5f9; color: #334155; border: 0;
    border-bottom: 1px solid #dbe3ef; padding: 3px 5px; font-weight: 700;
}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {
    background: #dbeafe; color: #0f172a;
}

QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; }
QTabBar::tab {
    padding: 4px 8px; margin-right: 3px; color: #475569;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
}
QTabBar::tab:selected { background: #ffffff; color: #1d4ed8; font-weight: 700; }
QTabBar::tab:!selected { background: #e2e8f0; color: #475569; }
QTabBar::tab:hover:!selected { background: #cbd5e1; color: #334155; }

QPushButton {
    background: #2563eb; color: #ffffff; border: 0;
    border-radius: 6px; padding: 4px 7px; font-weight: 600;
}
QPushButton:hover { background: #1d4ed8; }
QPushButton:pressed { background: #1e40af; }
QPushButton:disabled { background: #93c5fd; color: #eff6ff; }
QPushButton#CompactButton { padding: 3px 5px; }
QToolButton {
    background: transparent; color: #0f172a;
    border: 1px solid #dbe3ef; border-radius: 6px; padding: 3px 6px;
}
QToolButton:hover { background: #eff6ff; }
QToolButton:pressed { background: #dbeafe; }

QCheckBox, QRadioButton { color: #0f172a; spacing: 6px; background: transparent; }

QMenuBar { background: #f8fafc; color: #0f172a; }
QMenuBar::item { padding: 4px 8px; background: transparent; }
QMenuBar::item:selected { background: #e2e8f0; }
QMenu {
    background: #ffffff; color: #0f172a;
    border: 1px solid #dbe3ef; border-radius: 8px; padding: 4px;
}
QMenu::item { padding: 4px 18px 4px 12px; border-radius: 4px; }
QMenu::item:selected { background: #dbeafe; color: #1d4ed8; }
QMenu::item:disabled { color: #94a3b8; }
QMenu::separator { height: 1px; background: #e2e8f0; margin: 4px 8px; }

QScrollBar:vertical { background: #f1f5f9; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #cbd5e1; min-height: 24px; border-radius: 6px; }
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar:horizontal { background: #f1f5f9; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: #cbd5e1; min-width: 24px; border-radius: 6px; }
QScrollBar::handle:horizontal:hover { background: #94a3b8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QProgressBar {
    background: #e2e8f0; color: #0f172a; border: 1px solid #dbe3ef;
    border-radius: 6px; text-align: center;
}
QProgressBar::chunk { background: #2563eb; border-radius: 5px; }

QSplitter::handle { background: #e2e8f0; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }

QToolTip {
    background: #0f172a; color: #f8fafc;
    border: 1px solid #334155; padding: 4px 6px;
}
QStatusBar { background: #f8fafc; color: #334155; }
QMessageBox QLabel, QInputDialog QLabel { background: transparent; color: #0f172a; }
"""


def _families_font(families: List[str]) -> QFont:
    font = QFont()
    try:
        font.setFamilies([family for family in families if family])
    except AttributeError:
        font.setFamily(families[0] if families else "")
    return font


def configure_app_font(app: QApplication) -> None:
    """在 Linux 上优先使用带中日韩字形回退的字体，避免中文显示为方块。"""
    if not is_linux():
        return
    families = [
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "Droid Sans Fallback",
        "AR PL UMing CN",
        "DejaVu Sans",
    ]
    font = _families_font(families)
    if font.pointSize() < 9:
        font.setPointSize(10)
    app.setFont(font)


def apply_light_palette(app: QApplication) -> None:
    """强制浅色调色板，避免 Kali 深色主题造成白字白底。"""
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#0f172a"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#0f172a"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#0f172a"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#0f172a"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#94a3b8"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#1d4ed8"))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#6d28d9"))
    for group in (
        QPalette.ColorGroup.Disabled,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Active,
    ):
        palette.setColor(group, QPalette.ColorRole.Text, QColor("#0f172a"))
        palette.setColor(group, QPalette.ColorRole.WindowText, QColor("#0f172a"))
        palette.setColor(group, QPalette.ColorRole.ButtonText, QColor("#0f172a"))
    app.setPalette(palette)


def configure_app_theme(app: QApplication) -> None:
    """Kali/Linux 深度适配：Fusion 样式 + 浅色调色板 + 完整 QSS。"""
    if is_linux():
        app.setStyle("Fusion")
        apply_light_palette(app)
    app.setStyleSheet(build_stylesheet())


def open_with_system(target: str | Path) -> bool:
    """打开本地路径或 URL；Linux 上 QDesktopServices 失败时回退到 xdg-open。"""
    try:
        if isinstance(target, Path):
            url = QUrl.fromLocalFile(str(target.resolve()))
        else:
            url = QUrl(target)
        if QDesktopServices.openUrl(url):
            return True
    except Exception:
        pass
    if is_linux():
        opener = shutil.which("xdg-open")
        if opener:
            try:
                subprocess.Popen(
                    [opener, str(target)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except OSError:
                pass
    return False


def unique(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        s = str(value).strip()
        if not s:
            continue
        key = s.casefold()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def listify(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return unique(value)
    if isinstance(value, tuple):
        return unique(list(value))
    if isinstance(value, str):
        return unique([x.strip() for x in re.split(r"[,，]", value) if x.strip()])
    return unique([str(value)])


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value).strip()


def boolify(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def has_yaml_front_matter(text: str) -> bool:
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    first_line = normalized.split("\n", 1)[0]
    return first_line.strip() == "---"


def _front_matter_error(
    exc: yaml.YAMLError,
    raw: str,
    source_path: Optional[Path],
) -> FrontMatterParseError:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    line: Optional[int] = None
    column: Optional[int] = None
    snippet = ""

    if mark is not None:
        # raw 的第 1 行在完整 Markdown 中对应第 2 行。
        line = int(mark.line) + 2
        column = int(mark.column) + 1
        raw_lines = raw.splitlines()
        if 0 <= int(mark.line) < len(raw_lines):
            snippet = raw_lines[int(mark.line)].strip()

    problem = getattr(exc, "problem", None) or str(exc).splitlines()[-1]
    return FrontMatterParseError(source_path, str(problem), line, column, snippet)


def _write_repaired_front_matter(
    source_path: Path,
    repaired_raw: str,
    body: str,
) -> None:
    fixed_raw = repaired_raw.rstrip("\n")
    fixed_text = f"---\n{fixed_raw}\n---\n"
    if body:
        fixed_text += body.lstrip("\n")
    source_path.write_text(fixed_text, encoding="utf-8", newline="\n")


def split_front_matter(
    text: str,
    source_path: Optional[Path] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    分离并解析 YAML Front Matter。

    修复能力：
    - 兼容 UTF-8 BOM；
    - 兼容 CRLF/CR 换行；
    - 只把独立一行的 --- 识别为边界；
    - YAML 因 Tab 字符失败时，将 Front Matter 中的 Tab 替换为四个空格后重试；
    - 若传入 source_path 且 Tab 修复成功，会把修复结果安全写回原文件，
      使 Hugo 自身也能继续解析。
    """
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines(keepends=True)

    if not lines or lines[0].strip() != "---":
        return {}, normalized

    closing_index: Optional[int] = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break

    if closing_index is None:
        raise FrontMatterParseError(
            source_path,
            "缺少结束分隔符 ---",
            line=1,
            column=1,
            snippet=lines[0].strip() if lines else "---",
        )

    raw = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1:])

    try:
        data = yaml.load(raw, Loader=NoDatesSafeLoader) or {}
    except yaml.YAMLError as first_error:
        repaired_raw = raw.replace("\t", "    ")
        if repaired_raw != raw:
            try:
                data = yaml.load(repaired_raw, Loader=NoDatesSafeLoader) or {}
            except yaml.YAMLError:
                raise _front_matter_error(first_error, raw, source_path) from first_error

            if source_path is not None:
                try:
                    _write_repaired_front_matter(Path(source_path), repaired_raw, body)
                    repaired_name = str(Path(source_path))
                    if repaired_name not in FRONT_MATTER_AUTO_REPAIRS:
                        FRONT_MATTER_AUTO_REPAIRS.append(repaired_name)
                except OSError:
                    # 即使无法写回，也允许程序使用内存中的修复结果继续读取。
                    pass
        else:
            raise _front_matter_error(first_error, raw, source_path) from first_error

    if not isinstance(data, dict):
        raise FrontMatterParseError(
            source_path,
            "Front Matter 顶层必须是“键: 值”形式，不能是列表或单个标量",
            line=2,
            column=1,
        )

    return data, body


def yaml_scalar(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return value


def dump_front_matter(meta: Dict[str, Any], order: List[str], body: str) -> str:
    ordered: Dict[str, Any] = {}
    for key in order:
        if key in meta:
            ordered[key] = yaml_scalar(meta[key])
    for key, value in meta.items():
        if key not in ordered:
            ordered[key] = yaml_scalar(value)
    dumped = yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()
    return f"---\n{dumped}\n---\n\n{body.lstrip()}"


def sanitize_slug_guess(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or f"untitled-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def is_web_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value.strip(), re.I))


def normalized_reference_slug(value: str) -> str:
    """把 slug 或目录名整理成引用路径中的单个 path segment。"""
    return str(value).strip().strip("/")


def hugo_preview_port_in_use(host: str = HUGO_PREVIEW_HOST, port: int = HUGO_PREVIEW_PORT) -> bool:
    """检测本机 Hugo 预览端口是否处于监听状态。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def content_reference_path(kind: str, slug: str) -> str:
    section = "posts" if kind == "post" else "projects"
    return f"/{section}/{normalized_reference_slug(slug)}"


def taxonomy_reference_path(kind: str, name: str) -> str:
    section = {"category": "categories", "series": "series", "tag": "tags"}[kind]
    return f"/{section}/{normalized_reference_slug(name)}"


def markdown_reference(title: str, path: str) -> str:
    return f"[{str(title).strip() or path}]({path})"


def is_fragmented_record(record: "ContentRecord") -> bool:
    """沿用现有分片发现逻辑：只要已解析出 sections 文件，就视为分片内容。"""
    return bool(record.section_files)


def decrypt_api_key(password: str, encrypted_file: str | Path) -> str:
    """
    使用 AES-256-GCM 解密 API Key 文件。

    文件格式：
        nonce      16 字节
        tag        16 字节
        ciphertext 剩余字节

    密钥生成方式：
        SHA-256(password.encode("utf-8"))
    """
    path = Path(encrypted_file)

    if not path.is_file():
        raise FileNotFoundError(f"密文文件不存在：{path}")

    blob = path.read_bytes()

    if len(blob) <= 32:
        raise ValueError(
            "密文文件格式错误：文件应为 "
            "nonce(16B) + tag(16B) + ciphertext。"
        )

    aes_key = hashlib.sha256(password.encode("utf-8")).digest()

    nonce = blob[:16]
    tag = blob[16:32]
    ciphertext = blob[32:]

    try:
        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError as exc:
        raise ValueError(
            "解密失败：密码错误，或者密文文件已损坏、被篡改。"
        ) from exc

    return plaintext.decode("utf-8").strip()



def _atomic_write_cover(payload: bytes, dst: Path) -> None:
    """把压缩结果先写入临时文件，成功后再原子替换目标文件。"""
    ensure_dir(dst.parent)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".cover-optimized-",
            suffix=dst.suffix,
            dir=str(dst.parent),
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, dst)
        temp_path = None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)



def format_file_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _optimized_svg_bytes(src: Path) -> bytes:
    try:
        from scour import scour
    except ImportError as exc:
        raise RuntimeError(
            "压缩 SVG 需要安装 scour：\npip install scour"
        ) from exc

    source = src.read_text(encoding="utf-8")
    options = scour.sanitizeOptions()
    options.strip_comments = True
    options.remove_metadata = True
    options.keep_editor_data = False
    options.newlines = False
    options.indent_type = "none"
    optimized = scour.scourString(source, options)
    return optimized.encode("utf-8")


def _optimized_raster_bytes(src: Path, suffix: str) -> Tuple[bytes, str]:
    try:
        from PIL import Image, ImageSequence
    except ImportError as exc:
        raise RuntimeError(
            "压缩位图需要安装 Pillow：\npip install Pillow"
        ) from exc

    with Image.open(src) as image:
        output = BytesIO()
        info = dict(image.info)

        if suffix == ".png":
            kwargs: Dict[str, Any] = {
                "format": "PNG",
                "optimize": True,
                "compress_level": 9,
            }
            if info.get("icc_profile"):
                kwargs["icc_profile"] = info["icc_profile"]
            image.save(output, **kwargs)
            return output.getvalue(), ".png"

        if suffix in {".jpg", ".jpeg"}:
            if image.mode not in {"RGB", "L", "CMYK"}:
                image = image.convert("RGB")
            kwargs = {
                "format": "JPEG",
                "quality": "keep",
                "subsampling": "keep",
                "qtables": "keep",
                "optimize": True,
                "progressive": True,
            }
            if info.get("exif"):
                kwargs["exif"] = info["exif"]
            if info.get("icc_profile"):
                kwargs["icc_profile"] = info["icc_profile"]
            image.save(output, **kwargs)
            return output.getvalue(), ".jpg"

        if suffix == ".webp":
            frames = [frame.copy().convert("RGBA") for frame in ImageSequence.Iterator(image)]
            kwargs = {
                "format": "WEBP",
                "lossless": True,
                "method": 6,
                "exact": True,
            }
            if len(frames) > 1:
                kwargs.update({
                    "save_all": True,
                    "append_images": frames[1:],
                    "duration": info.get("duration", 100),
                    "loop": info.get("loop", 0),
                })
            frames[0].save(output, **kwargs)
            return output.getvalue(), ".webp"

        if suffix == ".gif":
            frames = [frame.copy() for frame in ImageSequence.Iterator(image)]
            durations = [frame.info.get("duration", info.get("duration", 100)) for frame in frames]
            kwargs = {
                "format": "GIF",
                "save_all": len(frames) > 1,
                "append_images": frames[1:],
                "optimize": True,
                "duration": durations,
                "loop": info.get("loop", 0),
            }
            if "transparency" in info:
                kwargs["transparency"] = info["transparency"]
            frames[0].save(output, **kwargs)
            return output.getvalue(), ".gif"

        if suffix == ".bmp":
            # BMP 通常没有有效压缩；转换为 PNG 可保持像素内容并显著减小体积。
            kwargs = {
                "format": "PNG",
                "optimize": True,
                "compress_level": 9,
            }
            if info.get("icc_profile"):
                kwargs["icc_profile"] = info["icc_profile"]
            image.save(output, **kwargs)
            return output.getvalue(), ".png"

        raise RuntimeError(f"暂不支持压缩该图片格式：{suffix or '未知格式'}")



def sanitize_cover_filename_stem(value: str, fallback: str = "cover") -> str:
    """
    生成适合 static/covers 使用的文件名主体。

    保留中文、英文字母、数字、下划线和短横线；空格及其他符号统一为短横线。
    """
    value = str(value).strip()
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-+", "-", value).strip("-_.")
    return value or fallback


def unique_cover_path(covers_dir: Path, stem: str, suffix: str) -> Path:
    """如文件名冲突，则按要求附加时间戳，并进一步避免同秒冲突。"""
    ensure_dir(covers_dir)
    normalized_suffix = suffix.lower() or ".png"
    if normalized_suffix == ".jpeg":
        normalized_suffix = ".jpg"

    safe_stem = sanitize_cover_filename_stem(stem)
    candidate = covers_dir / f"{safe_stem}{normalized_suffix}"
    if not candidate.exists():
        return candidate

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = covers_dir / f"{safe_stem}-{stamp}{normalized_suffix}"
    counter = 2
    while candidate.exists():
        candidate = covers_dir / f"{safe_stem}-{stamp}-{counter}{normalized_suffix}"
        counter += 1
    return candidate


def install_cover_to_static(
    src: Path,
    blog_root: Path,
    name_hint: str,
    compress: bool = False,
) -> Tuple[str, int, int]:
    """
    将用户选择的图片复制到项目的 static/covers 中。

    - 普通添加：原样复制，不删除用户选择的源文件。
    - 压缩添加：进行无损或不降低既有 JPEG 质量的优化；若优化结果更大，
      则保留原始字节。
    - 文件名使用文章、项目、系列或分类的名称/目录名；重名时追加时间戳。
    - 返回 Hugo 可直接使用的 /covers/... URL、处理前大小和处理后大小。
    """
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"图片文件不存在：{src}")

    covers_dir = ensure_dir(Path(blog_root) / "static" / "covers")
    original = src.read_bytes()
    before = len(original)
    suffix = src.suffix.lower() or ".png"
    normalized_suffix = ".jpg" if suffix == ".jpeg" else suffix
    payload = original
    final_suffix = normalized_suffix

    if compress:
        if suffix == ".svg":
            optimized = _optimized_svg_bytes(src)
            output_suffix = ".svg"
        else:
            optimized, output_suffix = _optimized_raster_bytes(src, suffix)

        # 仅在体积更小或格式转换确有必要时采用优化结果。
        if len(optimized) < before or output_suffix != normalized_suffix:
            payload = optimized
            final_suffix = output_suffix

    dst = unique_cover_path(covers_dir, name_hint, final_suffix)
    _atomic_write_cover(payload, dst)

    # 这里刻意不删除源文件，避免把用户从其他位置选中的原始图片误删。
    return f"/covers/{dst.name}", before, len(payload)


def local_cover_path(
    cover: str,
    blog_root: Path,
    bundle_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    将 cover 字段解析为本地文件路径。

    新格式 /covers/... 对应 <博客根目录>/static/covers/...；
    同时兼容旧的、相对于文章或 taxonomy 目录的封面路径。
    """
    value = str(cover).strip()
    if not value or is_web_url(value):
        return None
    if value.startswith("/"):
        return Path(blog_root) / "static" / value.lstrip("/")
    if bundle_dir is not None:
        return Path(bundle_dir) / value
    return Path(blog_root) / "static" / value



SECTION_FILENAME_RE = re.compile(r"^(\d+)(?:[-_ .].*)?\.md$", re.IGNORECASE)


def section_name_list(value: Any) -> List[str]:
    """读取 front matter 中的 sections，同时保持用户给定顺序。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return unique(str(item).strip() for item in value)
    if isinstance(value, str):
        return unique(line.strip().lstrip("- ").strip() for line in value.splitlines())
    return unique([str(value)])


def section_sort_key(path: Path) -> Tuple[int, str]:
    match = SECTION_FILENAME_RE.match(path.name)
    number = int(match.group(1)) if match else 10**18
    return number, path.name.casefold()


def discover_numbered_section_files(bundle_dir: Path) -> List[Path]:
    """只按文件名前导数字发现并排序分片，不受现有 sections 字段影响。"""
    return sorted(
        [
            path
            for path in Path(bundle_dir).glob("*.md")
            if path.name.casefold() not in {"index.md", "_index.md"}
            and SECTION_FILENAME_RE.match(path.name)
        ],
        key=section_sort_key,
    )


def discover_section_files(bundle_dir: Path, meta: Dict[str, Any]) -> List[Path]:
    """
    发现分片正文文件。

    有 sections 时，先严格采用其中列出的有效文件顺序；随后把没有列出的、
    以数字开头的 Markdown 分片按数字从小到大追加，避免新分片被静默遗漏。
    """
    candidates = discover_numbered_section_files(bundle_dir)
    candidate_by_name = {path.name.casefold(): path for path in candidates}
    ordered: List[Path] = []
    seen: set[str] = set()

    for raw_name in section_name_list(meta.get("sections")):
        name = Path(raw_name).name
        explicit = bundle_dir / name
        key = name.casefold()
        if explicit.is_file() and explicit.suffix.casefold() == ".md" and key not in seen:
            ordered.append(explicit)
            seen.add(key)
        elif key in candidate_by_name and key not in seen:
            ordered.append(candidate_by_name[key])
            seen.add(key)

    for path in sorted(candidates, key=section_sort_key):
        key = path.name.casefold()
        if key not in seen:
            ordered.append(path)
            seen.add(key)
    return ordered


def read_markdown_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    has_front_matter = has_yaml_front_matter(text)
    _, body = split_front_matter(text, path)
    return body if has_front_matter else text.lstrip("\ufeff")


def markdown_h1_title(line: str) -> str:
    match = re.match(r"^ {0,3}#(?!#)\s+(.+?)\s*#*\s*$", line.rstrip("\n"))
    if not match:
        return ""
    title = match.group(1).strip()
    return re.sub(r"\s+#*$", "", title).strip()


def body_is_single_h1_title(body: str) -> bool:
    """判断正文是否只包含一个一级标题，用于避免自动标题污染 index.md。"""
    normalized = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return False
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    return len(lines) == 1 and bool(markdown_h1_title(lines[0]))


def strip_single_h1_index_body(body: str) -> str:
    return "" if body_is_single_h1_title(body) else body


def markdown_h1_blocks(path: Path, body: str) -> List[MarkdownHeadingBlock]:
    """按一级标题切分 Markdown 正文；代码围栏中的 # 不作为标题。"""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)
    headings: List[Tuple[int, str]] = []
    in_fence = False
    fence_marker = ""

    for index, line in enumerate(lines):
        fence = re.match(r"^\s*(```+|~~~+)", line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[:3]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        title = markdown_h1_title(line)
        if title:
            headings.append((index, title))

    if not headings:
        return []

    preamble = "".join(lines[:headings[0][0]]).strip()
    blocks: List[MarkdownHeadingBlock] = []
    for pos, (start, title) in enumerate(headings):
        end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        chunk = "".join(lines[start:end]).strip()
        if pos == 0 and preamble:
            chunk = preamble + "\n\n" + chunk
        if chunk:
            blocks.append(MarkdownHeadingBlock(title=title, source_path=path, text=chunk.rstrip() + "\n"))
    return blocks


def collect_record_h1_blocks(record: ContentRecord) -> List[MarkdownHeadingBlock]:
    """统计 index.md 与所有分片 Markdown 中出现的一级标题块。"""
    blocks: List[MarkdownHeadingBlock] = []
    if (record.index_body or "").strip():
        blocks.extend(markdown_h1_blocks(record.md_path, record.index_body or ""))
    for section_path in record.section_files:
        try:
            body = read_markdown_body(section_path)
        except Exception:
            body = section_path.read_text(encoding="utf-8", errors="replace")
        blocks.extend(markdown_h1_blocks(section_path, body))
    return blocks


def chinese_section_ordinal(number: int) -> str:
    numerals = "零一二三四五六七八九"
    if number <= 0:
        return str(number)
    if number < 10:
        return numerals[number]
    if number == 10:
        return "十"
    if number < 20:
        return "十" + numerals[number % 10]
    if number < 100:
        tens, ones = divmod(number, 10)
        return numerals[tens] + "十" + (numerals[ones] if ones else "")
    return str(number)


def split_part_title(title: str, index: int) -> str:
    return f"{title}（{chinese_section_ordinal(index)}）"


def unique_content_slug(root: Path, base_slug: str, reserved: Optional[set[str]] = None) -> str:
    reserved = reserved if reserved is not None else set()
    base = sanitize_slug_guess(base_slug)
    candidate = base
    suffix = 2
    while candidate.casefold() in reserved or (Path(root) / candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    reserved.add(candidate.casefold())
    return candidate


def unique_section_filename(directory: Path, number: int, title: str, used: set[str]) -> str:
    stem = sanitize_cover_filename_stem(title, f"section-{number}")
    base = f"{number}-{stem}.md"
    candidate = base
    suffix = 2
    while candidate.casefold() in used or (Path(directory) / candidate).exists():
        candidate = f"{number}-{stem}-{suffix}.md"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def is_relative_file_reference(value: str) -> bool:
    raw = value.strip().strip("<>\"'")
    if not raw or raw.startswith("#") or raw.startswith("/"):
        return False
    if re.match(r"^[a-z][a-z0-9+.-]*:", raw, re.I):
        return False
    if raw.startswith(("{{", "{%")):
        return False
    cleaned = re.split(r"[?#]", raw, 1)[0]
    if not cleaned or cleaned.endswith("/"):
        return False
    suffix = Path(cleaned).suffix.casefold()
    return bool(suffix) and suffix not in {".md", ".markdown"}


def _clean_markdown_link_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        value = value[1:value.index(">")]
    elif re.search(r"\s", value):
        # 常见形式：![alt](image.png "title")。带空格文件名建议使用 %20。
        value = value.split()[0]
    return value.strip().strip("<>\"'")


def markdown_relative_dependencies(text: str) -> List[str]:
    refs: List[str] = []
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
        target = _clean_markdown_link_target(match.group(1))
        if is_relative_file_reference(target):
            refs.append(re.split(r"[?#]", target, 1)[0])
    for match in re.finditer(r"(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.I):
        target = _clean_markdown_link_target(match.group(1))
        if is_relative_file_reference(target):
            refs.append(re.split(r"[?#]", target, 1)[0])
    return unique(refs)


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def compose_content_body(index_body: str, section_files: List[Path]) -> str:
    """按 index 正文 + 分片正文顺序拼接出供 AI、统计等功能使用的全文。"""
    parts: List[str] = []
    if index_body.strip():
        parts.append(index_body.strip())
    for path in section_files:
        body = read_markdown_body(path).strip()
        if body:
            parts.append(body)
    return "\n\n".join(parts).strip()


def parse_iso_datetime(value: str) -> Optional[datetime]:
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def markdown_word_count(text: str) -> int:
    """适合中英文混排 Markdown 的近似字数，用于随机发布时间间隔加权。"""
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.S)
    cleaned = re.sub(r"`[^`]*`", " ", cleaned)
    return len(re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9_]+", cleaned))


def _active_axis_to_datetime(start_day: date, offset_seconds: float, day_count: int) -> datetime:
    daily_seconds = 14 * 3600  # 09:00 到 23:00
    maximum = max(0.0, day_count * daily_seconds - 1.0)
    value = min(max(0.0, offset_seconds), maximum)
    day_index = min(int(value // daily_seconds), day_count - 1)
    seconds_in_day = value - day_index * daily_seconds
    local_tz = datetime.now().astimezone().tzinfo
    return datetime.combine(
        start_day + timedelta(days=day_index),
        time(9, 0),
        tzinfo=local_tz,
    ) + timedelta(seconds=seconds_in_day)


def generate_creation_datetimes(
    records_oldest_first: List["ContentRecord"],
    start_day: date,
    end_day: date,
) -> List[datetime]:
    """
    生成非均匀、随机且保持当前顺序的创建时间。

    间隔受前一篇内容字数影响；同系列相邻文章的间隔权重更小。
    所有时间都落在每天 09:00—23:00 的允许窗口内。
    """
    count = len(records_oldest_first)
    if count == 0:
        return []
    if end_day < start_day:
        raise ValueError("结束日期不能早于开始日期。")

    day_count = (end_day - start_day).days + 1
    total = float(day_count * 14 * 3600)
    if count == 1:
        return [_active_axis_to_datetime(start_day, random.uniform(0, max(0, total - 1)), day_count)]

    gap_count = count - 1
    if total < gap_count * 30 * 60:
        raise ValueError("日期范围过短：请至少为相邻内容预留约 30 分钟的有效时间。")

    edge_limit = min(7 * 3600.0, total * 0.04)
    first_offset = random.uniform(0, edge_limit)
    final_slack = random.uniform(0, edge_limit)
    usable_span = max(1.0, total - first_offset - final_slack)

    average_gap = usable_span / gap_count
    minimum_gap = min(6 * 3600.0, max(30 * 60.0, average_gap * 0.14))
    if minimum_gap * gap_count >= usable_span:
        minimum_gap = usable_span / (gap_count * 2.0)

    weights: List[float] = []
    for index in range(1, count):
        previous = records_oldest_first[index - 1]
        current = records_oldest_first[index]
        words = markdown_word_count(previous.body)
        content_factor = 0.75 + min(math.log1p(max(words, 1)) / 7.5, 1.8)
        shared_series = bool(
            {name.casefold() for name in previous.series}
            & {name.casefold() for name in current.series}
        )
        series_factor = 0.62 if shared_series else 1.0
        random_factor = random.lognormvariate(0.0, 0.72)
        weights.append(max(0.05, content_factor * series_factor * random_factor))

    remaining = max(0.0, usable_span - minimum_gap * gap_count)
    weight_sum = sum(weights) or 1.0
    gaps = [minimum_gap + remaining * weight / weight_sum for weight in weights]

    positions = [first_offset]
    for gap in gaps:
        positions.append(positions[-1] + gap)
    return [_active_axis_to_datetime(start_day, position, day_count) for position in positions]


def random_lastmod_after(created: datetime) -> datetime:
    months = random.randint(1, 5)
    month_index = created.year * 12 + (created.month - 1) + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = random.randint(1, calendar.monthrange(year, month)[1])
    hour = random.randint(9, 22)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return datetime(year, month, day, hour, minute, second, tzinfo=created.tzinfo)


def read_hugo_base_url(root: Path) -> str:
    path = Path(root) / "hugo.yaml"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?mi)^\s*baseURL\s*:\s*(.*?)\s*$", text)
    if not match:
        return ""
    value = match.group(1).strip().strip('"\'')
    return value


def write_hugo_base_url(root: Path, url: str) -> None:
    path = Path(root) / "hugo.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"找不到 Hugo 配置文件：{path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    replacement = "baseURL: " + json.dumps(url, ensure_ascii=False)
    if re.search(r"(?mi)^\s*baseURL\s*:", text):
        text = re.sub(r"(?mi)^\s*baseURL\s*:.*$", replacement, text, count=1)
    else:
        text = replacement + "\n" + text
    path.write_text(text, encoding="utf-8", newline="\n")


def ai_chat_completion(
    endpoint: str,
    api_key: str,
    model: str,
    system_prompt: str,
    prompt: str,
    temperature: float = 0.0,
    timeout: int = 90,
) -> str:
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def parse_series_orders(value: Any, series_count: int) -> List[Optional[int]]:
    """兼容旧的单个 series_order，并规范为与 series 一一对应的列表。"""
    raw_values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    orders: List[Optional[int]] = []
    for raw in raw_values:
        try:
            number = int(raw)
            orders.append(number if number > 0 else None)
        except (TypeError, ValueError):
            orders.append(None)
    if len(orders) < series_count:
        orders.extend([None] * (series_count - len(orders)))
    return orders[:series_count]


@dataclass
class LeucoBlogConfig:
    root: Path = DEFAULT_BLOG_ROOT
    post_order: List[str] = field(default_factory=lambda: [
        "title",
        "date",
        "lastmod",
        "draft",
        "slug",
        "homepage",
        "sections",
        "series_order",
        "description",
        "summary",
        "tags",
        "categories",
        "series",
        "cover",
    ])
    project_order: List[str] = field(default_factory=lambda: [
        "title",
        "date",
        "lastmod",
        "draft",
        "slug",
        "homepage",
        "sections",
        "description",
        "summary",
        "featured",
        "tags",
        "categories",
        "cover",
        "link",
        "status",
    ])

    @property
    def content(self) -> Path:
        return self.root / "content"

    @property
    def posts(self) -> Path:
        return self.content / "posts"

    @property
    def projects(self) -> Path:
        return self.content / "projects"

    def taxonomy_root(self, kind: str) -> Path:
        return self.content / {"category": "categories", "series": "series", "tag": "tags"}[kind]


@dataclass
class ContentRecord:
    kind: str
    title: str
    slug: str
    date: str
    lastmod: str
    draft: bool
    homepage: bool
    description: str
    summary: str
    tags: List[str]
    categories: List[str]
    series: List[str]
    cover: str
    md_path: Path
    bundle_dir: Path
    body: str
    meta: Dict[str, Any]
    index_body: Optional[str] = None
    section_files: List[Path] = field(default_factory=list)
    series_order: List[Optional[int]] = field(default_factory=list)
    featured: bool = False
    link: str = ""
    status: str = ""

    def rel_display(self, root: Path) -> str:
        return rel_path(self.md_path, root)


@dataclass
class TaxonomyRecord:
    kind: str
    name: str
    title: str
    description: str
    cover: str
    index_path: Path
    folder: Path
    body: str
    meta: Dict[str, Any]


@dataclass
class MarkdownHeadingBlock:
    title: str
    source_path: Path
    text: str


@dataclass
class BrokenReference:
    kind: str
    slug: str
    reference: str
    path: Path
    line: int
    context: str


@dataclass
class TagMergeSuggestion:
    tags: List[str]
    target: str
    reason: str


class AppConfig:
    def __init__(self) -> None:
        ensure_dir(CONFIG_DIR)
        self.data: Dict[str, Any] = {
            "blog_root": str(DEFAULT_BLOG_ROOT),
            "api_base_url": "https://api.deepseek.com",
            "api_model": "deepseek-v4-flash",
            "git_remote": "origin",
            "git_branch": "main",
            "git_rebase": True,
            "git_autostash": True,
            "blog_url": BLOG_SITE_URL,
            "slug_concurrency": 20,
            "slug_batch_size": 40,
            "last_browse_dir": str(Path.home()),
        }
        if CONFIG_PATH.exists():
            try:
                loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass

        current_blog_url = str(self.data.get("blog_url", "")).strip()
        legacy_or_empty_urls = {
            "",
            "http://127.0.0.1:1313",
            "http://127.0.0.1:1313/",
            "http://localhost:1313",
            "http://localhost:1313/",
            "https://leuco-yuu.github.io",
        }
        if current_blog_url in legacy_or_empty_urls:
            self.data["blog_url"] = BLOG_SITE_URL

    def save(self) -> None:
        ensure_dir(CONFIG_PATH.parent)
        CONFIG_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def __getitem__(self, key: str) -> str:
        return str(self.data.get(key, ""))

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.data.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()


def parse_content(path: Path, kind: str) -> ContentRecord:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, index_body = split_front_matter(text, path)
    section_files = discover_section_files(path.parent, meta)
    full_body = compose_content_body(index_body, section_files)
    series = listify(meta.get("series"))
    return ContentRecord(
        kind=kind,
        title=scalar(meta.get("title")) or path.parent.name,
        slug=scalar(meta.get("slug")) or path.parent.name,
        date=scalar(meta.get("date")),
        lastmod=scalar(meta.get("lastmod")),
        draft=boolify(meta.get("draft")),
        homepage=boolify(meta.get("homepage")),
        description=scalar(meta.get("description")),
        summary=scalar(meta.get("summary")),
        tags=listify(meta.get("tags")),
        categories=listify(meta.get("categories")),
        series=series,
        cover=scalar(meta.get("cover")),
        md_path=path,
        bundle_dir=path.parent,
        body=full_body,
        meta=meta,
        index_body=index_body,
        section_files=section_files,
        series_order=parse_series_orders(meta.get("series_order"), len(series)),
        featured=boolify(meta.get("featured")),
        link=scalar(meta.get("link")),
        status=scalar(meta.get("status")),
    )


def parse_taxonomy(folder: Path, kind: str) -> TaxonomyRecord:
    index = folder / "_index.md"
    text = index.read_text(encoding="utf-8", errors="replace") if index.exists() else ""
    meta, body = split_front_matter(text, index)
    return TaxonomyRecord(
        kind=kind,
        name=folder.name,
        title=scalar(meta.get("title")) or folder.name,
        description=scalar(meta.get("description")),
        cover=scalar(meta.get("cover")),
        index_path=index,
        folder=folder,
        body=body,
        meta=meta,
    )


def write_content(record: ContentRecord, cfg: LeucoBlogConfig) -> None:
    meta = dict(record.meta)
    meta.pop("keywords", None)
    meta.pop("image", None)
    meta.update({
        "title": record.title,
        "date": record.date or now_iso(),
        "lastmod": record.lastmod or now_iso(),
        "draft": bool(record.draft),
        "slug": record.slug,
        "description": record.description,
        "summary": record.summary,
        "tags": unique(record.tags),
        "categories": unique(record.categories),
        "cover": record.cover,
    })
    if record.homepage:
        meta["homepage"] = True
    else:
        meta.pop("homepage", None)
    if record.kind == "post":
        record.series = unique(record.series)
        meta["series"] = record.series
        normalized_orders = parse_series_orders(record.series_order, len(record.series))
        record.series_order = normalized_orders
        if record.series:
            serializable = list(normalized_orders)
            meta["series_order"] = serializable[0] if len(serializable) == 1 else serializable
        else:
            meta.pop("series_order", None)
        order = cfg.post_order
    else:
        meta["featured"] = bool(record.featured)
        meta["link"] = record.link or None
        meta["status"] = record.status
        order = cfg.project_order
    fragmented = is_fragmented_record(record) or bool(section_name_list(meta.get("sections")))
    if record.index_body is not None:
        index_body = record.index_body
    elif fragmented:
        # 分片内容的正文保存在各分片 Markdown 中。只改元数据时，
        # 不把拼接后的全文或自动一级标题写回 index.md。
        index_body = ""
    else:
        index_body = record.body
    if fragmented:
        index_body = strip_single_h1_index_body(index_body)
    record.md_path.write_text(dump_front_matter(meta, order, index_body), encoding="utf-8", newline="\n")
    record.index_body = index_body
    record.meta = meta


def write_taxonomy(record: TaxonomyRecord) -> None:
    meta = dict(record.meta)
    meta["title"] = record.title or record.name
    meta["description"] = record.description or ""
    if record.cover:
        meta["cover"] = record.cover
    else:
        meta.pop("cover", None)
    record.index_path.write_text(
        dump_front_matter(meta, ["title", "description", "cover"], record.body),
        encoding="utf-8",
        newline="\n",
    )
    record.meta = meta
