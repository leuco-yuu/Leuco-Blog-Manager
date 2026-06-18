$ErrorActionPreference = "Stop"
python -m pip install -r requirements-dev.txt
python -m PyInstaller packaging/LeucoBlogManager.spec --clean --noconfirm
