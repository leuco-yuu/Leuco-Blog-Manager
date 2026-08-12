#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "错误: 未找到 $PYTHON_BIN，且项目内没有 .venv。"
    echo "请先运行 scripts/install_kali.sh 完成环境安装。"
    exit 1
fi

# 强制 UTF-8，避免 Git/Hugo 输出乱码。
export PYTHONUTF8=1
# 桌面缩放与 X11 平台插件：Kali 无 Wayland 会话时自动回退 xcb。
export QT_AUTO_SCREEN_SCALE_FACTOR="${QT_AUTO_SCREEN_SCALE_FACTOR:-1}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
# 使用内置浅色主题，修复深色桌面下白字白底问题。
export QT_STYLE_OVERRIDE="${QT_STYLE_OVERRIDE:-Fusion}"
unset QT_QPA_PLATFORMTHEME 2>/dev/null || true

if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    exec "$PROJECT_ROOT/.venv/bin/python" run.py "$@"
fi

exec "$PYTHON_BIN" run.py "$@"
