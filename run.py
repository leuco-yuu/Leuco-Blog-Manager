#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Development launcher for the source-tree checkout.

This file intentionally bootstraps ./src so the application can be started with:

    python .\run.py

without requiring `pip install -e .` first.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if SRC_DIR.is_dir():
    sys.path.insert(0, str(SRC_DIR))

from main import main


if __name__ == "__main__":
    main()
