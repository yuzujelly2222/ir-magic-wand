# reader.py — firmware/ir_rx を書き込んだ Arduino から USB シリアルで受信し、
#                    ストロークごとに XZTrack にする
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
# ir_rx (firmware/ir_rx) は、送信機がまとめて送ってきた
# 1 ストロークを組み立て、欠けた点を補間してから 115200bps で次の行を PC に送る:
#   #stroke_begin,id=<sid>,n=<点数>,missing=<補間した点数>
#   pt,<yaw_deg>,<pitch_deg>              … ストローク開始点からの相対角 (25Hz)
#   #stroke_end
#   #drop,id=<sid>,reason=<理由>           … 届いた点が少なすぎて捨てた
#   #stats,strokes=..,dropped=..,crc_err=..,interp=..
#   #ir_rx ready                          … 起動 (ポートを開くと Arduino がリセットされて出る)
#
#   python -m magic_wand listen COM3      # 受信してストロークごとに座標を表示する
#
#   reader = SerialXZReader("COM3")       # Linux: /dev/ttyACM0 や /dev/ttyUSB0
#   reader.start()                         # 別スレッドで受信開始
#   track = reader.wait_stroke()           # 次のストロークが届くまで待つ
#   track.get_xz()                         # [(x, z), ...]
#   reader.close()
from __future__ import annotations

import argparse
import csv
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional

import serial  # pyserial

from . import style
from .parser import StrokeParser
from .projection import PointerProjector, Projector
from .track import StrokeDrop, XZTrack

RX_BAUD = 115200  # ir_rx の Serial.begin(115200)


class SerialXZReader:
    """ir_rx の出力を読んで、届いたストロークを XZTrack として溜める。"""

    def __init__(
        self,
        port: Optional[str] = None,
        baud: int = RX_BAUD,
        projector: Optional[Projector] = None,
        arm_length: float = 1.0,
        log_csv: Optional[str] = None,
        on_stroke: Optional[Callable[[XZTrack], None]] = None,
        on_drop: Optional[Callable[[StrokeDrop], None]] = None,
        on_line: Optional[Callable[[str], None]] = None,
        max_tracks: Optional[int] = 100,
        ser=None,
        clock: Callable[[], float] = time.monotonic,
    ):
        """
        port:       シリアルポート名 ("COM3", "/dev/ttyACM0" など)
        baud:       PC と ir_rx 間のボーレート (ir_rx は 115200)
        projector:  座標の出し方 (pitch, yaw, arm_length) -> (x, z)。既定は棒の先端 (project_xz)
        arm_length: 棒の長さ (棒の先端モードの座標のスケール)
        log_csv:    受け取ったストロークを CSV に保存するパス (load_tracks で読み直せる)
        on_stroke:  ストロークを受け取るたびに呼ぶ関数 f(track)
        on_drop:    ストロークを捨てたときに呼ぶ関数 f(drop)
        on_line:    #stats などストローク以外の行を受けたときに呼ぶ関数 f(line)
        max_tracks: 手元に残すストロークの数 (古いものから消す。None なら全部残す)
        ser:        pyserial の Serial 互換オブジェクトを直接渡す場合 (テスト用など)
        コールバックは受信スレッドから呼ばれる。
        """
        self.parser = StrokeParser(projector, arm_length)
        self.on_stroke = on_stroke
        self.on_drop = on_drop
        self.on_line = on_line
        self.tracks: Deque[XZTrack] = deque(maxlen=max_tracks)
        self.drops: Deque[StrokeDrop] = deque(maxlen=max_tracks)
        self.stroke_count = 0  # 受け取ったストロークの合計
        self.drop_count = 0  # 捨てたストロークの合計
        self._new: List[XZTrack] = []  # get_new() でまだ返していないストローク
        self._clock = clock
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._t0 = clock()
        self._buf = bytearray()

        if ser is None:
            ser = serial.Serial(port, baud, timeout=0.05)
        self.ser = ser

        self._log_file = None
        self._log = None
        if log_csv:
            self._log_file = open(log_csv, "w", newline="", encoding="utf-8")
            self._log = csv.writer(self._log_file)
            self._log.writerow(["stroke", "i", "yaw", "pitch"])

    def now(self) -> float:
        """受信開始からの秒数 (XZTrack.received_at と同じ基準)。"""
        return self._clock() - self._t0

    # ------------------------------------------------------------ 受信
    def poll(self) -> List[XZTrack]:
        """届いているバイトを読んで処理する。今回受け取ったストロークを返す。"""
        n = getattr(self.ser, "in_waiting", 0) or 1
        return self.process(self.ser.read(n))

    def process(self, data: bytes) -> List[XZTrack]:
        """受信したバイト列を処理する (シリアル以外から流し込むときにも使える)。"""
        t = self.now()
        self._buf += data
        got: List[XZTrack] = []
        dropped: List[StrokeDrop] = []
        others: List[str] = []
        with self._cond:
            while True:
                i = self._buf.find(b"\n")
                if i < 0:
                    break
                line = self._buf[:i].decode("ascii", errors="ignore").strip()
                del self._buf[:i + 1]
                if not line:
                    continue
                for e in self.parser.feed(line, t):
                    if isinstance(e, XZTrack):
                        got.append(e)
                    else:
                        dropped.append(e)
                if line.startswith("#") and not line.startswith(("#stroke_", "#drop")):
                    others.append(line)
            for tr in got:
                self.tracks.append(tr)
                self._new.append(tr)
                self.stroke_count += 1
                self._write_log(tr)
            for d in dropped:
                self.drops.append(d)
                self.drop_count += 1
            if got:
                self._cond.notify_all()
        for tr in got:
            if self.on_stroke:
                self.on_stroke(tr)
        for d in dropped:
            if self.on_drop:
                self.on_drop(d)
        for line in others:
            if self.on_line:
                self.on_line(line)
        return got

    def _write_log(self, tr: XZTrack) -> None:
        if not self._log:
            return
        sid = tr.id if tr.id is not None else self.stroke_count
        for p in tr:
            self._log.writerow([sid, p.i, f"{p.yaw:.1f}", f"{p.pitch:.1f}"])
        self._log_file.flush()

    def run(self, duration: Optional[float] = None) -> None:
        """このスレッドで受信し続ける。duration 秒経つか stop() で終わる。"""
        self._running = True
        end = None if duration is None else self._clock() + duration
        try:
            while self._running and (end is None or self._clock() < end):
                self.poll()
        finally:
            self._running = False

    def start(self) -> None:
        """別スレッドで受信を始める。"""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join()
            self._thread = None

    def close(self) -> None:
        self.stop()
        if self._log_file:
            self._log_file.close()
            self._log_file = None
            self._log = None
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ 取得 (スレッドセーフ)
    def latest(self) -> Optional[XZTrack]:
        """最後に受け取ったストローク。まだなければ None。"""
        with self._lock:
            return self.tracks[-1] if self.tracks else None

    def get_tracks(self) -> List[XZTrack]:
        """手元に残っているストロークのリスト (古い順)。"""
        with self._lock:
            return list(self.tracks)

    def get_new(self) -> List[XZTrack]:
        """前回 get_new() / wait_stroke() を呼んでから届いたストローク (古い順)。"""
        with self._lock:
            out, self._new = self._new, []
            return out

    def wait_stroke(self, timeout: Optional[float] = None) -> Optional[XZTrack]:
        """次のストロークが届くまで待って返す。timeout 秒で届かなければ None。

        まだ get_new() / wait_stroke() で返していないストロークがあれば、その一番古いものをすぐ返す。
        start() していなければ、この中で受信しながら待つ。
        """
        end = None if timeout is None else self._clock() + timeout
        while True:
            with self._cond:
                if self._new:
                    return self._new.pop(0)
                threaded = self._thread is not None and self._thread.is_alive()
                if threaded:
                    left = None if end is None else end - self._clock()
                    if left is not None and left <= 0:
                        return None
                    self._cond.wait(0.5 if left is None else min(left, 0.5))
                    continue
            if end is not None and self._clock() >= end:
                return None
            self.poll()

    @property
    def stats(self) -> Dict[str, int]:
        """Arduino が送ってくる集計 {'strokes', 'dropped', 'crc_err', 'interp'}。"""
        with self._lock:
            return dict(self.parser.stats)

    @property
    def resets(self) -> int:
        """Arduino が起動した (#ir_rx ready を受けた) 回数。"""
        with self._lock:
            return self.parser.resets


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m magic_wand listen",
                                 description="受信機 (firmware/ir_rx) から受信して xz 座標を表示する")
    ap.add_argument("port", help="例: COM3, /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=RX_BAUD)
    ap.add_argument("--arm-length", type=float, default=1.0)
    ap.add_argument("--log", help="受け取ったストロークを保存する CSV")
    ap.add_argument("--pointer", action="store_true", help="ポインター風 (向いている先の画面上の位置)")
    ap.add_argument("--distance", type=float, default=1.0, help="--pointer の感度")
    args = ap.parse_args(argv)
    proj = PointerProjector(distance=args.distance) if args.pointer else None

    def show(tr: XZTrack) -> None:
        print_track(tr)

    def drop(d: StrokeDrop) -> None:
        print(f"  {style.stamp(d.received_at)}  {style.red(style.DROP)} {style.red('受信に失敗')}  "
              f"{style.gray(f'id={d.id}  {d.reason}')}")

    def line(text: str) -> None:
        print(f"  {style.gray(text)}")

    style.banner("listen", args.port, "ポインター風" if args.pointer else "棒の先端",
                 *([f"保存 {args.log}"] if args.log else []))
    with SerialXZReader(args.port, args.baud, projector=proj, arm_length=args.arm_length,
                        log_csv=args.log, on_stroke=show, on_drop=drop, on_line=line) as reader:
        try:
            reader.run()
        except KeyboardInterrupt:
            pass
        st = "  ".join(f"{k}={v}" for k, v in reader.stats.items())
        print(f"\n  {style.gray(f'受信 {reader.stroke_count}  失敗 {reader.drop_count}  {st}')}")


def print_track(tr: XZTrack) -> None:
    """1 ストロークの見出しと点の一覧を表示する (listen と csv で共通)。"""
    note = f"  補間 {tr.missing}" if tr.missing else ""
    print(f"  {style.stamp(tr.received_at)}  {style.green(style.OK)} "
          f"{style.bold(f'stroke {tr.id}')}  {style.gray(f'{len(tr)} 点 · {tr.duration:.2f} 秒{note}')}")
    for p in tr:
        print(f"  {' ' * 8}  {style.gray(f'{p.i:3d}')}  x {p.x:+.4f}  z {p.z:+.4f}")

