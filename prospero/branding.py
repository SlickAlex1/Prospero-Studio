# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Name, version, links and the start-up banner shared by the window and the command line."""
from __future__ import annotations

from anyps5_settings import VERSION

APP_NAME = "Prospero Studio"
TAGLINE = "Run your own PS5 game dumps and homebrew on Windows - a front end for AnyPS5"
AUTHOR = "SlickAlex"
AUTHOR_URL = "https://github.com/SlickAlex1"
REPO_URL = "https://github.com/SlickAlex1/Prospero-Studio"
ISSUES_URL = f"{REPO_URL}/issues"
DOCS_URL = f"{REPO_URL}/tree/main/docs"
TROUBLESHOOTING_URL = f"{REPO_URL}/blob/main/docs/TROUBLESHOOTING.md"
LICENSE_NAME = "GNU GPL v3.0 or later"
CREDITS = (
    ("AnyPS5", "boykopovar and contributors", "https://github.com/boykopovar/AnyPS5",
     "relinker, PS5 system libraries for Windows, unwrap_self.py, import_audit.py (GPL-2.0-only)"),
    ("PS5-SELF-TO-ELF", "julienlgy", "https://github.com/julienlgy/PS5-SELF-TO-ELF",
     "self_to_elf.py SELF/PRX converter"),
)
NOTICE = ("Unofficial. Not affiliated with Sony, AnyPS5 or PS5-SELF-TO-ELF. Contains no game files, keys or "
          "Sony code and cannot decrypt anything: use it only with games you own and dumped yourself.")

# 5-row block font for the banner (only the letters of the name).
_GLYPHS = {
    "P": ("████ ", "█   █", "████ ", "█    ", "█    "),
    "R": ("████ ", "█   █", "████ ", "█  █ ", "█   █"),
    "O": (" ███ ", "█   █", "█   █", "█   █", " ███ "),
    "S": (" ████", "█    ", " ███ ", "    █", "████ "),
    "E": ("█████", "█    ", "████ ", "█    ", "█████"),
    "T": ("█████", "  █  ", "  █  ", "  █  ", "  █  "),
    "U": ("█   █", "█   █", "█   █", "█   █", " ███ "),
    "D": ("████ ", "█   █", "█   █", "█   █", "████ "),
    "I": ("█████", "  █  ", "  █  ", "  █  ", "█████"),
    " ": ("   ",) * 5,
}


def banner_rows(word: str) -> list[str]:
    """The word in the block font, 5 rows."""
    return ["  ".join(_GLYPHS[c][row] for c in word.upper()) for row in range(5)]


def banner() -> list[str]:
    """Both banner lines: PROSPERO above STUDIO."""
    return banner_rows("PROSPERO") + [""] + banner_rows("STUDIO")
