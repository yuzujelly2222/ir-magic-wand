# parser.py — 受信機 (firmware/ir_rx) が USB シリアルに出す行を読んで、ストロークにする
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
# 受信機は、送信機から届いた 1 ストロークを組み立て、欠けた点を補間してから次の行を送ってくる:
#
#   #stroke_begin,id=3,n=42,missing=0
#   pt,0.0,0.0           ← pt,<yaw>,<pitch> [度]。ストローク開始点からの相対角 (25Hz)
#   ...
#   #stroke_end
#   #drop,id=4,reason=too_many_lost   ← 届いた点が少なすぎて捨てたストローク
#   #stats,strokes=..,dropped=..,crc_err=..,interp=..
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .projection import Projector
from .track import Event, StrokeDrop, XZTrack


def _kv(line: str) -> Dict[str, str]:
    """'#stroke_begin,id=3,n=42' → {'id': '3', 'n': '42'}"""
    out = {}
    for item in line.split(",")[1:]:
        k, sep, v = item.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def parse_stats(line: str) -> Dict[str, int]:
    """'#stats,strokes=3,dropped=1,crc_err=2,interp=4' → {'strokes': 3, 'dropped': 1, ...}"""
    out: Dict[str, int] = {}
    for k, v in _kv(line).items():
        try:
            out[k] = int(v)
        except ValueError:
            pass
    return out


def _int_or_none(s: Optional[str]) -> Optional[int]:
    try:
        return int(s) if s is not None else None
    except ValueError:
        return None


class StrokeParser:
    """ir_rx の出力を 1 行ずつ feed() すると、ストロークが終わるたびに XZTrack を返す。

    feed() はその行で確定したもののリストを返す (ふつうは空か 1 つ)。
    受け取ったストロークは XZTrack、捨てたストロークは StrokeDrop。
    """

    def __init__(self, projector: Optional[Projector] = None, arm_length: float = 1.0):
        self.projector = projector
        self.arm_length = arm_length
        self.stats: Dict[str, int] = {}  # 最後に受けた #stats
        self.resets = 0  # #ir_rx ready を受けた回数 (Arduino のリセット)
        self._header: Optional[Dict[str, str]] = None
        self._angles: List[Tuple[float, float]] = []
        self._broken = False

    def feed(self, line: str, t: Optional[float] = None) -> List[Event]:
        line = line.strip()
        if line.startswith("#stroke_begin"):
            prev = self._abort("incomplete", t)
            self._header = _kv(line)
            self._angles = []
            self._broken = False
            return prev
        if line.startswith("pt,"):
            if self._header is None:
                return []  # 途中から聞き始めた
            try:
                _, yaw, pitch = line.split(",")
                a = (float(yaw), float(pitch))
                if not all(math.isfinite(v) for v in a):
                    raise ValueError
                self._angles.append(a)
            except ValueError:
                self._broken = True
            return []
        if line.startswith("#stroke_end"):
            if self._header is None:
                return []
            h, angles, broken = self._header, self._angles, self._broken
            self._header = None
            sid = _int_or_none(h.get("id"))
            n = _int_or_none(h.get("n"))
            if broken:
                return [StrokeDrop(sid, "broken_line", t)]
            if (n is not None and n != len(angles)) or not angles:
                return [StrokeDrop(sid, "incomplete", t)]
            return [XZTrack(angles, sid, _int_or_none(h.get("missing")) or 0, t,
                            self.projector, self.arm_length)]
        if line.startswith("#drop"):
            kv = _kv(line)
            return self._abort("incomplete", t) + \
                [StrokeDrop(_int_or_none(kv.get("id")), kv.get("reason", ""), t)]
        if line.startswith("#stats"):
            self.stats = parse_stats(line)
        elif line.startswith("#ir_rx ready"):
            self.resets += 1
            return self._abort("incomplete", t)
        return []

    def _abort(self, reason: str, t: Optional[float]) -> List[Event]:
        """途中のストロークを捨てる (#stroke_end が来る前に別の行が来た)。"""
        if self._header is None:
            return []
        sid = _int_or_none(self._header.get("id"))
        self._header = None
        return [StrokeDrop(sid, reason, t)]
