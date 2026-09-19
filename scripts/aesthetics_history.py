#!/usr/bin/env python3
"""Checkout launcher for OrcaSlicer; no installation required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from toolpath_processors.cli import main
if __name__ == '__main__':
    raise SystemExit(main())
