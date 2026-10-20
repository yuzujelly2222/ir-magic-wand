# assembler.py — 受信したパケットから 1 ストロークを組み立てる (firmware/ir_rx の Python 版)
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
# ふつうは受信機の Arduino (ir_rx) が組み立ててから PC に送ってくるので、PC 側で使う必要はない。
# Raspberry Pi などで受光モジュールの出力を直接読む場合や、パケットを 16 進で保存した CSV を
# 読む場合に使う。
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .protocol import HEADER, INFO_END, MAX_POINTS, PACKET_SIZE, UNIT_DEG, Packet, decode


@dataclass
class AssembledStroke:
    sid: int
    points: List[Tuple[float, float]]  # [(yaw, pitch), ...] [度]
    missing: int  # 届かずに補間した点の数


@dataclass
class Dropped:
    sid: int
    reason: str  # "too_short" / "too_many_lost"


class StrokeAssembler:
    """パケットから 1 ストロークを組み立てる (ir_rx の stroke_assembler.h と同じ動き)。

    - sid が変わったら前のストロークを確定して、新しいストロークを始める
    - INFO(end) で残り再送が 0 なら確定。再送が残っていて欠けがあれば待つ
    - パケットが TIMEOUT 秒来なければ確定 (end を取りこぼした場合)
    - 欠けた点は前後から直線補間する
    - 届いた点が 6 割未満なら破棄。INFO を両方落としても、点数は DATA から分かる

    push() / poll() は、確定したものを AssembledStroke / Dropped のリストで返す。
    """

    TIMEOUT = 0.4  # [秒] パケット間隔は約 0.12 秒
    MIN_PERCENT = 60
    DONE_HOLD = 3.0  # [秒] 確定後この時間は同じ sid の再送を無視

    def __init__(self) -> None:
        self._active = False
        self._sid = 0
        self._n = 0
        self._top = 0
        self._xy: dict = {}  # index -> (x, y) 0.2° 単位
        self._last = 0.0
        self._done_sid: Optional[int] = None
        self._done_t = 0.0

    def push(self, pk: Packet, now: float) -> list:
        out: list = []
        if self._done_sid == pk.sid and now - self._done_t < self.DONE_HOLD:
            return out  # 確定済みストロークの再送
        if self._active and pk.sid != self._sid:
            out.append(self._finalize())  # 前のストロークの end を落とした
            if self._done_sid == pk.sid:  # (起こらないが念のため)
                return out
        if not self._active:
            self._start(pk.sid)
        self._last = now

        if pk.is_info:
            self._n = min(pk.b[0], MAX_POINTS)
            if pk.b[1] == INFO_END and (pk.b[2] == 0 or len(self._xy) >= self._n):
                out.append(self._finalize())
            return out

        for j, x, y in pk.points():
            self._xy[j] = (x, y)
            self._top = max(self._top, j + 1)
        return out

    def poll(self, now: float) -> list:
        if self._active and now - self._last >= self.TIMEOUT:
            self._last = now
            return [self._finalize()]
        return []

    def _start(self, sid: int) -> None:
        self._active = True
        self._sid = sid
        self._n = self._top = 0
        self._xy = {}

    def _finalize(self):
        self._active = False
        self._done_sid = self._sid
        self._done_t = self._last
        n = self._n or self._top
        if n < 2:
            return Dropped(self._sid, "too_short")
        got = sum(1 for i in range(n) if i in self._xy)
        if got * 100 < n * self.MIN_PERCENT or got < 2:
            return Dropped(self._sid, "too_many_lost")

        xs: List[int] = [0] * n
        ys: List[int] = [0] * n
        known = [i for i in range(n) if i in self._xy]
        for i in known:
            xs[i], ys[i] = self._xy[i]
        prev = None
        for i in range(n):
            if i in self._xy:
                prev = i
                continue
            nxt = next((k for k in known if k > i), None)
            src = prev if nxt is None else nxt
            if prev is None or nxt is None:
                xs[i], ys[i] = xs[src], ys[src]
            else:
                xs[i] = _lerp(xs[prev], xs[nxt], i - prev, nxt - prev)
                ys[i] = _lerp(ys[prev], ys[nxt], i - prev, nxt - prev)
        # 0.2° 単位 → 度 (受信機と同じく 0.01° 単位の整数を経由して丸め誤差を出さない)
        c = round(UNIT_DEG * 100)
        return AssembledStroke(self._sid, [(x * c / 100, y * c / 100) for x, y in zip(xs, ys)],
                               n - got)


def _lerp(a: int, b: int, num: int, den: int) -> int:
    # stroke_assembler.h と同じ整数の四捨五入
    d = (b - a) * num
    q = (d + den // 2) // den if d >= 0 else -((-d + den // 2) // den)
    return a + q


class Framer:
    """バイト列から 10 バイトのパケットを切り出す (CRC 不一致なら次の 0xAA まで戻って再同期)。"""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.crc_errors = 0

    def push(self, data: bytes) -> List[Packet]:
        out: List[Packet] = []
        for b in data:
            if not self._buf and b != HEADER:
                continue
            self._buf.append(b)
            if len(self._buf) < PACKET_SIZE:
                continue
            pk = decode(bytes(self._buf))
            if pk is not None:
                out.append(pk)
                self._buf.clear()
                continue
            self.crc_errors += 1
            rest = self._buf[1:]
            i = rest.find(HEADER)
            self._buf = bytearray(rest[i:]) if i >= 0 else bytearray()
        return out
