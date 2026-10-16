# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
# Double-click this file to open Prospero Studio. Everything else lives in prospero/ (code) and
# runtime/ (downloads and settings, created on first start).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "prospero"))
import anyps5_gui  # noqa: E402

anyps5_gui.main()
