# style.py — コマンドラインの見た目 (色・記号・スコアのバー)
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
# 外部ライブラリに依存しない。色は ANSI エスケープで付ける。
#   - 出力先が端末でないとき (ファイルやパイプへ) と、環境変数 NO_COLOR があるときは色を付けない
#   - FORCE_COLOR があれば端末でなくても付ける
#   - Windows 10 以降のコンソールは、最初に使うときに ANSI を有効にする
#   - 出力先の文字コードで出せない記号は ? に置き換える (cp932 のパイプなどで落ちないように)
from __future__ import annotations

import os
import sys
import unicodedata
from typing import Optional

_enabled: Optional[bool] = None


def _setup() -> bool:
    global _enabled
    if _enabled is not None:
        return _enabled
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    if "NO_COLOR" in os.environ:
        _enabled = False
    elif "FORCE_COLOR" in os.environ:
        _enabled = True
    else:
        _enabled = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and _enable_vt()
    return _enabled


def _enable_vt() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k32.SetConsoleMode(h, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


def set_color(on: Optional[bool]) -> None:
    """色を付けるかどうかを決める (None で自動判定に戻す)。"""
    global _enabled
    _enabled = on
    _setup()


def _sgr(code: str):
    def paint(text: object) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if _setup() else str(text)
    return paint


bold = _sgr("1")
dim = _sgr("2")
italic = _sgr("3")
red = _sgr("38;5;203")
green = _sgr("38;5;84")
yellow = _sgr("38;5;221")
blue = _sgr("38;5;75")
magenta = _sgr("38;5;177")
cyan = _sgr("38;5;80")
gray = _sgr("38;5;244")

# 記号
SPARK = "✦"
OK = "◆"
NG = "◇"
DROP = "✕"
ARROW = "→"
RUN = "▸"
DOT = "·"


def score_bar(score: float, threshold: float, width: int = 16) -> str:
    """スコアを ━━━━──── のバーにする。しきい値以上なら緑、近ければ黄、遠ければ赤。"""
    score = max(0.0, min(1.0, score))
    n = round(score * width)
    paint = green if score >= threshold else yellow if score >= threshold - 0.1 else red
    return paint("━" * n) + gray("─" * (width - n))


def banner(title: str, *info: str) -> None:
    """コマンドの最初に出す 1 行の見出しと区切り線。"""
    extra = f"  {gray(DOT)}  ".join(info)
    head = f"  {magenta(SPARK)} {bold('magic_wand')} {gray(DOT)} {cyan(title)}"
    print(head + (f"   {extra}" if extra else ""))
    print("  " + gray("─" * 60))


def width(text: str) -> int:
    """端末での表示幅 (全角は 2)。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text: str, n: int) -> str:
    """表示幅が n になるまで右に空白を足す (色を付ける前の文字列に使う)。"""
    return text + " " * max(0, n - width(text))


def stamp(t: Optional[float]) -> str:
    """[  12.3s] 形式の時刻。"""
    return gray(f"{t:7.1f}s") if t is not None else gray("      -")
