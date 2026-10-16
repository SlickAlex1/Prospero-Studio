# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
# Double-click to open the Prospero Studio window (no console).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anyps5_gui

anyps5_gui.main()
