# csv_io.py — ストロークの CSV の読み書き
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
#   python -m magic_wand csv sample.csv      # 中身を表示する
#
# 読める形式:
#   - save_tracks() / SerialXZReader(log_csv=...) で保存したもの (stroke,i,yaw,pitch)
#   - シリアルモニタの出力をそのまま保存したもの (#stroke_begin / pt / #stroke_end)
#   - IR パケットを 16 進で並べたもの (packet 列。任意で時刻の列)
from __future__ import annotations

import argparse
import csv
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import style
from .assembler import Dropped, Framer, StrokeAssembler
from .parser import StrokeParser, _int_or_none
from .projection import PointerProjector, Projector
from .track import XZTrack


# ヘッダ名 (小文字・空白除去後) → 内部名
_ALIASES = {
    "stroke": "stroke", "id": "stroke", "stroke_id": "stroke", "sid": "stroke",
    "i": "i", "index": "i",
    "yaw": "yaw", "x_deg": "yaw",
    "pitch": "pitch", "y_deg": "pitch",
    "packet": "packet", "raw": "packet",
    "t": "t", "time": "t", "timestamp": "t", "time_s": "t",
    "time_ms": "t_ms", "timestamp_ms": "t_ms", "millis": "t_ms",
}

# ヘッダなし CSV の列の並び (列数で判断)
_NO_HEADER_LAYOUTS = {
    2: ("yaw", "pitch"),
    3: ("stroke", "yaw", "pitch"),
    4: ("stroke", "i", "yaw", "pitch"),
}


def load_tracks(path: str, projector: Optional[Projector] = None,
                arm_length: float = 1.0) -> List[XZTrack]:
    """CSV (または ir_rx の出力を保存したテキスト) を読んで、ストロークごとの XZTrack のリストを返す。

    読める形式:
      - save_tracks() / SerialXZReader(log_csv=...) で保存したもの (stroke,i,yaw,pitch)
      - シリアルモニタの出力をそのまま保存したもの (#stroke_begin / pt / #stroke_end)
      - IR パケットを 16 進で並べたもの (packet 列。任意で時刻の列)
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    return parse_tracks(lines, projector, arm_length)


def parse_tracks(lines: Iterable[str], projector: Optional[Projector] = None,
                 arm_length: float = 1.0) -> List[XZTrack]:
    """load_tracks() の中身。文字列の行のリストから読む。"""
    lines = [ln.strip() for ln in lines if ln.strip()]
    if any(ln.startswith(("#stroke_begin", "pt,")) for ln in lines):
        parser = StrokeParser(projector, arm_length)
        return [e for ln in lines for e in parser.feed(ln) if isinstance(e, XZTrack)]

    rows = list(csv.reader(lines))
    if not rows:
        return []
    columns = _detect_columns(rows[0])
    if columns is None:
        columns = _NO_HEADER_LAYOUTS.get(len(rows[0]))
        if columns is None:
            raise ValueError(f"CSV の列が判別できない: {rows[0]}")
    else:
        rows = rows[1:]
    if "packet" in columns:
        return _tracks_from_packets(columns, rows, projector, arm_length)

    groups: Dict[Optional[str], List[Tuple[int, float, float]]] = {}
    for row in rows:
        v = {name: cell.strip() for name, cell in zip(columns, row) if name}
        try:
            yaw, pitch = float(v["yaw"]), float(v["pitch"])
        except (KeyError, ValueError):
            continue  # 壊れた行は飛ばす
        g = groups.setdefault(v.get("stroke"), [])
        i = _int_or_none(v.get("i"))
        g.append((len(g) if i is None else i, yaw, pitch))

    tracks = []
    for key, pts in groups.items():
        pts.sort(key=lambda p: p[0])
        tracks.append(XZTrack([(y, p) for _, y, p in pts], _int_or_none(key), 0, None,
                              projector, arm_length))
    return tracks


def _detect_columns(cells: Sequence[str]) -> Optional[Tuple[Optional[str], ...]]:
    names = tuple(_ALIASES.get(c.strip().lower().replace(" ", "")) for c in cells)
    if not any(names):
        return None
    if not ({"yaw", "pitch"} <= set(names) or "packet" in names):
        raise ValueError(f"CSV に yaw/pitch か packet の列がない: {list(cells)}")
    return names


def _tracks_from_packets(columns, rows, projector, arm_length) -> List[XZTrack]:
    """packet 列 (16 進) を受信機と同じ手順で組み立てる。時刻の列がなければ 0.1 秒間隔とみなす。"""
    framer, asm = Framer(), StrokeAssembler()
    events: list = []
    t = 0.0
    for row in rows:
        v = {name: cell.strip() for name, cell in zip(columns, row) if name}
        try:
            if v.get("t"):
                t = float(v["t"])
            elif v.get("t_ms"):
                t = float(v["t_ms"]) / 1000.0
            else:
                t += 0.1
            data = bytes.fromhex(v.get("packet", ""))
        except ValueError:
            continue
        for pk in framer.push(data):
            events += asm.push(pk, t)
    events += asm.poll(t + StrokeAssembler.TIMEOUT)
    return [XZTrack(e.points, e.sid, e.missing, None, projector, arm_length)
            for e in events if not isinstance(e, Dropped)]


def save_tracks(path: str, tracks: Iterable[XZTrack]) -> None:
    """stroke,i,yaw,pitch の形式で保存する (load_tracks で読み直せる)。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stroke", "i", "yaw", "pitch"])
        for k, tr in enumerate(tracks):
            sid = tr.id if tr.id is not None else k
            for p in tr:
                w.writerow([sid, p.i, f"{p.yaw:.1f}", f"{p.pitch:.1f}"])

def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m magic_wand csv",
                                 description="保存したストロークの CSV を読んで、x, z 座標を表示する")
    ap.add_argument("path", help="CSV のパス")
    ap.add_argument("--arm-length", type=float, default=1.0)
    ap.add_argument("--pointer", action="store_true", help="ポインター風 (向いている先の画面上の位置)")
    args = ap.parse_args(argv)
    tracks = load_tracks(args.path, PointerProjector() if args.pointer else None, args.arm_length)
    style.banner("csv", args.path, f"{len(tracks)} ストローク")
    for tr in tracks:
        note = f"  補間 {tr.missing}" if tr.missing else ""
        print(f"  {style.green(style.OK)} {style.bold(f'stroke {tr.id}')}  "
              f"{style.gray(f'{len(tr)} 点 · {tr.duration:.2f} 秒{note}')}")
        for p in tr:
            print(f"    {style.gray(f'{p.i:3d}')}  x {p.x:+.4f}  z {p.z:+.4f}   "
                  f"{style.gray(f'yaw {p.yaw:+6.1f}  pitch {p.pitch:+6.1f}')}")

