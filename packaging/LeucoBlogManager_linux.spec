# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path.cwd()

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[str(project_root / 'src')],
    binaries=[],
    datas=[
        (str(project_root / 'src' / 'prompts'), 'prompts'),
        (str(project_root / 'src' / 'config' / 'config.example.json'), 'config'),
        (str(project_root / 'src' / 'icon.png'), '.'),
        (str(project_root / 'src' / 'icon.svg'), '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='leuco-blog-manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
