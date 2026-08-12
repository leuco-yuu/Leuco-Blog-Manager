#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="leuco-blog-manager"
VENV_DIR="$PROJECT_ROOT/.venv"

echo "==> Leuco Blog Manager Kali/Linux 一键安装"
if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "    检测到系统: ${PRETTY_NAME:-${ID:-unknown}}"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "错误: 未找到 $PYTHON_BIN，请先安装 Python 3.10+。"
    exit 1
fi

APT_CORE_PACKAGES=(
    ca-certificates
    curl
    libdbus-1-3
    libegl1
    libgl1
    libxcb-cursor0
    libxcb-icccm4
    libxcb-keysyms1
    libxcb-shape0
    libxcb-xkb1
    libxkbcommon-x11-0
    fonts-noto-cjk
    python3-pip
    python3-venv
)

APT_TOOL_PACKAGES=(
    git
    hugo
    iproute2
    lsof
    procps
    xdg-utils
)

echo "==> 安装核心系统依赖（需要管理员权限）..."
if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    apt-get install -y "${APT_CORE_PACKAGES[@]}"
else
    if ! command -v sudo >/dev/null 2>&1; then
        echo "错误: 当前用户不是 root 且未安装 sudo，无法安装系统依赖。"
        exit 1
    fi
    sudo apt-get update
    sudo apt-get install -y "${APT_CORE_PACKAGES[@]}"
fi

echo "==> 安装 git / hugo / 系统工具..."
if [ "$(id -u)" -eq 0 ]; then
    apt-get install -y "${APT_TOOL_PACKAGES[@]}" \
        || echo "警告: 部分工具（git/hugo/xdg-utils 等）安装失败，可稍后手动安装。"
else
    sudo apt-get install -y "${APT_TOOL_PACKAGES[@]}" \
        || echo "警告: 部分工具（git/hugo/xdg-utils 等）安装失败，可稍后手动安装。"
fi

echo "==> 创建 Python 虚拟环境: $VENV_DIR"
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
pip install -r "$PROJECT_ROOT/requirements.txt"
pip install -e "$PROJECT_ROOT"

echo "==> 设置启动脚本权限..."
chmod +x "$PROJECT_ROOT/run" "$SCRIPT_DIR/run_kali.sh" "$SCRIPT_DIR/build_linux.sh"

echo "==> 安装桌面入口..."
ICON_DIR="$HOME/.local/share/icons/hicolor/512x512/apps"
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$ICON_DIR" "$APP_DIR"
cp -f "$PROJECT_ROOT/src/icon.png" "$ICON_DIR/$APP_NAME.png"
VENV_PYTHON="$VENV_DIR/bin/python"
sed \
    -e "s|__VENV_PYTHON__|$VENV_PYTHON|g" \
    -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    "$PROJECT_ROOT/packaging/leuco-blog-manager.desktop" \
    > "$APP_DIR/$APP_NAME.desktop"
chmod +x "$APP_DIR/$APP_NAME.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

cat <<EOF

安装完成！

  开发运行:  $SCRIPT_DIR/run_kali.sh
  或者:      cd $PROJECT_ROOT && .venv/bin/leuco-blog-manager
  桌面入口:  在应用菜单中搜索 “Leuco”

如果 Hugo 命令不在 PATH 中，请执行: sudo apt-get install -y hugo
EOF
