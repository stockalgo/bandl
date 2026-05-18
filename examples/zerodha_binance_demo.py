#!/usr/bin/env python3
"""
Historical OHLCV demo (Binance + Zerodha).

This file is a thin alias for ``main.py`` so older debug/launch configs keep working.

Install dependencies first::

    pip install -r requirements.txt
    # or
    pip install -e .

Then run::

    python examples/main.py
    # or
    python examples/zerodha_binance_demo.py
"""

from __future__ import annotations

import os
import runpy

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MAIN = os.path.join(_THIS_DIR, "main.py")

if __name__ == "__main__":
    runpy.run_path(_MAIN, run_name="__main__")
