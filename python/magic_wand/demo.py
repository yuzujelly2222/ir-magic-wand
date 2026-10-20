# demo.py — 実機の代わりに、受信機 (firmware/ir_rx) と同じ形式の行を出すダミー
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
#   reader = SerialXZReader(ser=DemoSerial(), ...)
#
# 約 4 秒ごとにジェスチャーを 1 つ「描いた」ことにして、1 ストロークぶんの行をまとめて出す。
# 形は templates.py の TEMPLATES に、手ぶれ・ゆがみ・速さのむらを足したもの。
# ときどき、ジェスチャーでない動き (まっすぐな線)・補間あり・受信失敗 (#drop) も混ぜる。
from __future__ import annotations

import math
import random
import time
from typing import List, Optional, Sequence, Tuple

from .templates import TEMPLATES


class DemoSerial:
    def __init__(self, shapes: Optional[Sequence[str]] = None, period: float = 4.0,
                 seed: Optional[int] = None):
        """
        shapes: 順に出す形 (既定は TEMPLATES 全部 + "line")
        period: 何秒ごとに 1 ストローク出すか
        """
        self.shapes = list(shapes) if shapes else list(TEMPLATES) + ["line"]
        self.period = period
        self.t0 = time.monotonic()
        self.next = self.t0 + 1.0
        self.sid = 0
        self.buf = bytearray(b"#ir_rx ready\r\n")
        self.rnd = random.Random(seed)
        self.last_shape: Optional[str] = None  # 最後に出した形 (確かめる用)

    @property
    def in_waiting(self) -> int:
        if not self.buf and time.monotonic() >= self.next:
            self._make_stroke()
        return len(self.buf)

    def read(self, n: int) -> bytes:
        if not self.in_waiting:
            time.sleep(0.01)
            return b""
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def close(self) -> None:
        pass

    def _make_stroke(self) -> None:
        self.next = time.monotonic() + self.period
        sid = self.sid
        self.sid = (self.sid + 1) % 256
        if self.rnd.random() < 0.1:  # たまに受信失敗
            self.buf += f"#drop,id={sid},reason=too_many_lost\r\n".encode()
            self.last_shape = None
            return
        shape = self.shapes[sid % len(self.shapes)]
        self.last_shape = shape
        pts = self.make_points(shape, self.rnd)
        missing = self.rnd.choice((0, 0, 0, 4))
        lines = [f"#stroke_begin,id={sid},n={len(pts)},missing={missing}"]
        lines += [f"pt,{y:.1f},{p:.1f}" for y, p in pts]
        lines += ["#stroke_end", f"#stats,strokes={sid + 1},dropped=0,crc_err=0,interp=0"]
        self.buf += ("\r\n".join(lines) + "\r\n").encode()

    @staticmethod
    def make_points(shape: str, rnd: random.Random) -> List[Tuple[float, float]]:
        """(yaw, pitch) [度] の点列 (25Hz)。1 点目は (0, 0) (ストローク開始点からの相対角)。"""
        base = TEMPLATES.get(shape) or [(-1.0, -0.2), (1.0, 0.2)]  # "line": ジェスチャーでない動き
        amp = rnd.uniform(15, 35)                                    # 振り幅 [度]
        L = len(base) - 1
        plen = sum(math.dist(base[i], base[i + 1]) for i in range(L)) * amp / 2
        n = max(12, min(100, int(plen / rnd.uniform(70, 130) * 25)))  # 70〜130 °/s で描く
        th = math.radians(rnd.uniform(-15, 15))
        sx, sy = rnd.uniform(0.8, 1.2), rnd.uniform(0.8, 1.2)
        out = []
        for i in range(n):
            f = i / (n - 1) * L
            j = min(int(f), L - 1)
            w = f - j
            x = (base[j][0] * (1 - w) + base[j + 1][0] * w) * sx
            y = (base[j][1] * (1 - w) + base[j + 1][1] * w) * sy
            x, y = x * math.cos(th) - y * math.sin(th), x * math.sin(th) + y * math.cos(th)
            out.append((x * amp / 2 + rnd.gauss(0, 0.3), y * amp / 2 + rnd.gauss(0, 0.3)))
        x0, y0 = out[0]
        return [(x - x0, y - y0) for x, y in out]
