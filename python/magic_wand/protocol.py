# protocol.py — 杖 (firmware) の IR パケットの定義 (v2: ストローク一括送信 / 0.2° 固定 / 最大 4 秒)
#               firmware/ir_tx・ir_rx の protocol.h の Python 版
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
# 送信機はストローク (最大 4 秒) をため込み、終わってからまとめて送る。1 ストロークの送信は:
#
#   INFO(begin) → DATA × ceil(n/4) → INFO(end)     (これを再送回数ぶん)
#
# パケット (13 bytes, 1200bps 8N1, LSB first):
#   [0xAA][sid][idx][b0][b1][b2][b3][b4][b5][b6][b7][b8][CRC8]
#
#   sid : ストローク ID (送るたびに +1)
#   idx : 0..99 → DATA。点 idx〜idx+3 の 4 点
#           b0..b2 = 点 idx の絶対座標 (アンカー)。x, y を 12bit の符号付きで
#                    b0 = x の上位 8bit, b1 = y の上位 8bit, b2 = (x の下位 4bit << 4) | y の下位 4bit
#           b3..b8 = 点 idx+1〜idx+3 の、1 つ前の点からの差分 (dx, dy) を int8 で。-128 は「点なし」
#         0xFF  → INFO。b0 = 点数 n, b1 = 0: begin / 1: end, b2 = このあと残っている再送の回数
#
#   座標 (x = yaw, y = pitch) は「ストローク開始点からの相対角」で、単位は 0.2°
#
#   - CRC8 (多項式 0x07, 初期値 0x00) はバイト 0〜11 から計算
#   - ヘッダ以外の 12 バイトは 0x55 で XOR して送る
#
# パケットからストロークを組み立てる処理は assembler.py。
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

BAUD = 1200  # IR 上のビットレート
HEADER = 0xAA
WHITEN_MASK = 0x55
PACKET_SIZE = 13
PAYLOAD_SIZE = 9
POINTS_PER_PACKET = 4  # アンカー 1 点 + 差分 3 点
IDX_INFO = 0xFF
NO_POINT = -128
SAMPLE_HZ = 25  # 点のサンプリング周波数
MAX_POINTS = 100  # 4 秒 × 25Hz
UNIT_DEG = 0.2  # 座標の単位 [度]
COORD_MAX = 2047  # 12bit 符号付き
COORD_MIN = -2048
INFO_BEGIN = 0
INFO_END = 1


@dataclass
class Packet:
    sid: int
    idx: int
    b: Tuple[int, ...]  # ペイロード 9 バイト (0〜255)

    @property
    def is_info(self) -> bool:
        return self.idx == IDX_INFO

    def points(self) -> List[Tuple[int, int, int]]:
        """DATA パケットの点を [(index, x, y), ...] で返す (x, y は 0.2° 単位の整数)。"""
        x, y = unpack_anchor(self.b)
        out = []
        for k in range(POINTS_PER_PACKET):
            if k > 0:
                dx, dy = _int8(self.b[1 + 2 * k]), _int8(self.b[2 + 2 * k])
                if dx == NO_POINT:
                    break
                x, y = x + dx, y + dy
            j = self.idx + k
            if j >= MAX_POINTS:
                break
            out.append((j, x, y))
        return out


def _int8(b: int) -> int:
    return b - 256 if b >= 128 else b


def crc8(data: bytes) -> int:
    crc = 0x00
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _whiten(data: bytes) -> bytes:
    # バイト0 (ヘッダ) はそのまま、それ以降を XOR。往復とも同じ処理
    return data[:1] + bytes(b ^ WHITEN_MASK for b in data[1:])


def encode(pk: Packet) -> bytes:
    raw = bytes([HEADER, pk.sid & 0xFF, pk.idx & 0xFF, *(v & 0xFF for v in pk.b)])
    return _whiten(raw + bytes([crc8(raw)]))


def decode(frame: bytes) -> Optional[Packet]:
    """不正なパケット (長さ・ヘッダ・CRC・idx) なら None を返す。"""
    if len(frame) != PACKET_SIZE:
        return None
    raw = _whiten(bytes(frame))
    if raw[0] != HEADER or crc8(raw[:-1]) != raw[-1]:
        return None
    pk = Packet(raw[1], raw[2], tuple(raw[3:3 + PAYLOAD_SIZE]))
    if not pk.is_info and pk.idx >= MAX_POINTS:
        return None
    return pk


def pack_anchor(x: int, y: int) -> Tuple[int, int, int]:
    ux, uy = x & 0x0FFF, y & 0x0FFF
    return ux >> 4, uy >> 4, ((ux & 0x0F) << 4) | (uy & 0x0F)


def _sign12(v: int) -> int:
    return v - 0x1000 if v & 0x800 else v


def unpack_anchor(b: Sequence[int]) -> Tuple[int, int]:
    return _sign12((b[0] << 4) | (b[2] >> 4)), _sign12((b[1] << 4) | (b[2] & 0x0F))


def make_info(sid: int, n: int, kind: int, repeats_left: int = 0) -> Packet:
    return Packet(sid, IDX_INFO, (n, kind, repeats_left, 0, 0, 0, 0, 0, 0))


def make_data(sid: int, idx: int, anchor: Tuple[int, int], deltas: List[Tuple[int, int]]) -> Packet:
    """点 idx の絶対座標と、続く最大 3 点の差分 (0.2° 単位) を詰めた DATA パケット。"""
    b = list(pack_anchor(*anchor))
    for k in range(POINTS_PER_PACKET - 1):
        dx, dy = deltas[k] if k < len(deltas) else (NO_POINT, NO_POINT)
        b += [dx & 0xFF, dy & 0xFF]
    return Packet(sid, idx, tuple(b))


def quantize(points_deg: List[Tuple[float, float]]) -> List[Tuple[int, int]]:
    """(yaw, pitch) [度] を、送信機と同じ手順で 0.2° 単位の整数にする。

    四捨五入して 12bit に収め、1 つ前の点からの差分が ±127 を超える分は次の点に回す。
    """
    out: List[Tuple[int, int]] = []
    qx = qy = 0
    for x, y in points_deg:
        qx = _step(qx, _clamp12(_round(x / UNIT_DEG)))
        qy = _step(qy, _clamp12(_round(y / UNIT_DEG)))
        out.append((qx, qy))
    return out


def _clamp12(v: int) -> int:
    return max(COORD_MIN, min(COORD_MAX, v))


def _step(prev: int, q: int) -> int:
    return prev + max(-127, min(127, q - prev))


def encode_stroke(sid: int, points_deg: List[Tuple[float, float]], repeat: int = 1) -> List[bytes]:
    """(yaw, pitch) [度, 開始点からの相対角] の点列を、送信機と同じ手順でパケット列にする (テスト用)。"""
    q = quantize(points_deg)
    n = len(q)
    frames: List[bytes] = []
    for r in range(repeat):
        left = repeat - 1 - r
        frames.append(encode(make_info(sid, n, INFO_BEGIN, left)))
        for i in range(0, n, POINTS_PER_PACKET):
            deltas = [(q[j][0] - q[j - 1][0], q[j][1] - q[j - 1][1])
                      for j in range(i + 1, min(i + POINTS_PER_PACKET, n))]
            frames.append(encode(make_data(sid, i, q[i], deltas)))
        frames.append(encode(make_info(sid, n, INFO_END, left)))
    return frames


def _round(v: float) -> int:
    # C 版と同じく四捨五入 (0 から遠い方へ)。Python の round() は偶数丸めなので使わない
    return int(v + 0.5) if v >= 0.0 else int(v - 0.5)
