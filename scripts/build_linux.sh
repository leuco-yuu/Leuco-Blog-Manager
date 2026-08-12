#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "错误: 未找到 .venv，请先运行 scripts/install_kali.sh 或手动创建虚拟环境。"
    exit 1
fi

"$PROJECT_ROOT/.venv/bin/python" -m pip install -r requirements-dev.txt
"$PROJECT_ROOT/.venv/bin/python" -m PyInstaller packaging/LeucoBlogManager_linux.spec --clean --noconfirm

echo "构建完成: dist/leuco-blog-manager"
