# projection.py — 角度 (yaw, pitch) を x, z 座標に直す方法
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
#   project_xz       : 棒の先端を真上から見た位置 (上下の動きはほとんど出ない)
#   PointerProjector : 向いている先の画面上の位置 (ポインター風。ジェスチャーにはこちら)
# 自分で作る場合は (pitch, yaw, arm_length) -> (x, z) を返す関数を渡す。
from __future__ import annotations

import math
from typing import Callable, Optional, Tuple

# (pitch, yaw, arm_length) -> (x, z)
Projector = Callable[[float, float, float], Tuple[float, float]]


def project_xz(pitch: float, yaw: float, arm_length: float) -> Tuple[float, float]:
    """角度 (度) から xz 座標を求める (既定の変換: 棒の先端を真上から見た位置)。"""
    p = math.radians(pitch)
    y = math.radians(yaw)
    r = arm_length * math.cos(p)
    return r * math.sin(y), r * math.cos(y)


class PointerProjector:
    """ポインター風: 向いている先の仮想スクリーン上の位置を返す (根元の固定や腕の長さは不要)。

    角度はストローク開始点からの相対角なので、ストロークの書き始めが画面の中央 (0, 0) になる。
      x = distance * tan(yaw)                … 横 (右が +)
      z = distance * tan(pitch) / cos(yaw)   … 縦 (上が +)
    """

    def __init__(self, distance: float = 1.0, max_angle: float = 60.0,
                 limit: Optional[float] = None):
        """
        distance:  仮想スクリーンまでの距離 (= 感度。座標はこれと同じ単位)
        max_angle: 中央から何度までを使うか。これ以上は端で止める (tan が発散しないように)
        limit:     x, z をこの値で止める (None なら max_angle で決まる範囲)
        """
        self.distance = distance
        self.max_angle = max_angle
        self.limit = limit

    def __call__(self, pitch: float, yaw: float, arm_length: float) -> Tuple[float, float]:
        m = self.max_angle
        dy = max(-m, min(m, yaw))
        dp = max(-m, min(m, pitch))
        x = self.distance * math.tan(math.radians(dy))
        z = self.distance * math.tan(math.radians(dp)) / math.cos(math.radians(dy))
        if self.limit is not None:
            x = max(-self.limit, min(self.limit, x))
            z = max(-self.limit, min(self.limit, z))
        return x, z
