# track.py — 1 ストロークぶんの点列 (XZTrack) と、受け取れなかったストローク (StrokeDrop)
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
# 座標系 (右手系, Y 軸が上):
#   x: 右, y: 上, z: 前 (ストローク開始時に向いていた方向)
#   x, z の出し方は projection.py (既定は project_xz)。
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, Union

from .projection import Projector, project_xz
from .protocol import SAMPLE_HZ


@dataclass(frozen=True)
class XZPoint:
    x: float
    z: float
    i: int  # ストロークの中で何番目の点か (0 から)
    t: float  # ストローク開始からの秒 (= i / 25)
    yaw: float  # 元の角度 [度] (ストローク開始点からの相対角)
    pitch: float


class XZTrack:
    """1 ストロークぶんの xz 座標の軌跡。points に XZPoint が時間の順に入る。"""

    def __init__(
        self,
        angles: Sequence[Tuple[float, float]],
        id: Optional[int] = None,
        missing: int = 0,
        received_at: Optional[float] = None,
        projector: Optional[Projector] = None,
        arm_length: float = 1.0,
    ):
        """
        angles:      [(yaw, pitch), ...] [度]。ストローク開始点からの相対角 (25Hz)
        id:          ストローク ID (送信機が 0〜255 で振る)
        missing:     届かずに受信機が補間した点の数
        received_at: 受信した時刻 [秒] (SerialXZReader では受信開始からの秒)
        projector:   (pitch, yaw, arm_length) -> (x, z)。既定は project_xz
        arm_length:  棒の長さ (project_xz の座標のスケール)
        """
        self.id = id
        self.missing = missing
        self.received_at = received_at
        self.arm_length = arm_length
        self.projector: Projector = projector or project_xz
        self.points: List[XZPoint] = []
        for i, (yaw, pitch) in enumerate(angles):
            x, z = self.projector(pitch, yaw, arm_length)
            self.points.append(XZPoint(x, z, i, i / SAMPLE_HZ, yaw, pitch))

    def reproject(self, projector: Optional[Projector] = None,
                  arm_length: Optional[float] = None) -> "XZTrack":
        """同じ角度から、別の座標の出し方で作り直した XZTrack を返す。"""
        return XZTrack(self.get_angles(), self.id, self.missing, self.received_at,
                       projector or self.projector,
                       self.arm_length if arm_length is None else arm_length)

    # ------------------------------------------------------------ 取得
    def get_xz(self) -> List[Tuple[float, float]]:
        """(x, z) のタプルのリスト。"""
        return [(p.x, p.z) for p in self.points]

    def get_x(self) -> List[float]:
        return [p.x for p in self.points]

    def get_z(self) -> List[float]:
        return [p.z for p in self.points]

    def get_angles(self) -> List[Tuple[float, float]]:
        """元の角度 [(yaw, pitch), ...] [度]。"""
        return [(p.yaw, p.pitch) for p in self.points]

    def get_point(self, index: int) -> XZPoint:
        return self.points[index]

    @property
    def duration(self) -> float:
        """ストロークの長さ [秒]。"""
        return (len(self.points) - 1) / SAMPLE_HZ if self.points else 0.0

    def __len__(self) -> int:
        return len(self.points)

    def __iter__(self):
        return iter(self.points)

    def __getitem__(self, index):
        return self.points[index]

    def __repr__(self) -> str:
        return f"XZTrack(id={self.id}, points={len(self.points)}, missing={self.missing})"


@dataclass(frozen=True)
class StrokeDrop:
    """受け取れなかったストローク。"""
    id: Optional[int]
    reason: str  # ir_rx から: too_many_lost / too_short
    #              PC 側で判断: broken_line (壊れた行があった) / incomplete (#stroke_end の前に途切れた)
    received_at: Optional[float] = None


Event = Union[XZTrack, StrokeDrop]
