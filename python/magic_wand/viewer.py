# viewer.py — 杖から届いたストロークを、tkinter の画面に描いて再生し、ジェスチャーを判定する
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
#   python -m magic_wand view COM3      # 実機
#   python -m magic_wand view --demo    # 実機なし (ダミーデータ) で動作確認
#
# 杖を振って止めると、送信機がストロークをまとめて送ってくる (送信に 1〜2 秒かかる)。
# 届いたら、その軌跡を実際の速さ (25Hz) でカーソルがなぞり、線が描かれていく。
# ストロークの書き始めが画面の中央になる (ポインター風 = PointerProjector)。
# 判定したジェスチャーを画面の左上に出す (--no-gesture で判定しない)。
# --on で、ジェスチャーを描いたときに実行するものを決められる (gestures コマンドと同じ。actions.py)。
#
# 操作: R キー / 「もう一度再生」ボタン → 最後のストロークを再生、Esc で終了
from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from typing import List, Optional

from .demo import DemoSerial
from .actions import GestureActions
from .gestures import REASONS_JA, add_cli_args, from_cli_args
from .projection import PointerProjector
from .protocol import SAMPLE_HZ
from .reader import SerialXZReader
from .track import XZTrack

W, H = 800, 600       # 画面サイズ [px]
LIMIT = 1.0           # x, z がこの値で画面の端 (はみ出した分は画面の外に描かれる)
FPS_MS = 16           # 画面の更新間隔 (約 60fps)
SPEED = 1.0           # 再生の速さ (1 = 実際の速さ、0.5 = ゆっくり)
KEEP = 3              # 薄く残しておく過去のストロークの数

# 色
BG = "#0d0f14"        # 背景
GRID = "#1a1e27"      # 方眼
CROSS = "#3a4150"     # 中央の十字
INK = "#7cf5c4"       # 描いている線
TRAIL = "#24453b"     # 過去のストロークと、線の光
MISS = "#ff6b7a"      # 受け付けなかった
SUB = "#8a93a6"       # 小さい文字
BAR = "#151821"       # 下の帯
FONT = "Segoe UI" if sys.platform == "win32" else "Helvetica"


class App:
    def __init__(self, root, reader, recognizer=None, actions: Optional[GestureActions] = None):
        self.root = root
        self.reader = reader
        self.recognizer = recognizer
        self.actions = actions
        self.track = None          # 再生中 (または最後に再生した) ストローク
        self.play_start = 0.0
        self.old_lines = []        # 過去のストロークの線 (canvas の id)
        self.received = 0

        root.title("magic_wand · viewer")
        root.configure(bg=BAR)
        self.canvas = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
        self.canvas.pack()
        bar = tk.Frame(root, bg=BAR, padx=12, pady=8)
        bar.pack(fill="x")
        tk.Button(bar, text="↻  もう一度再生 (R)", command=self.replay, relief="flat", bd=0,
                  bg="#232836", fg="#e6e9ef", activebackground="#2f3546", activeforeground="#fff",
                  font=(FONT, 10), padx=10, pady=3, cursor="hand2").pack(side="left")
        self.status = tk.Label(bar, text="ストロークを待っています… (杖を振って止める)", anchor="w",
                               bg=BAR, fg=SUB, font=(FONT, 10), padx=12)
        self.status.pack(side="left", fill="x", expand=True)

        # 方眼と中央の十字 (= ストロークの書き始め)
        for gx in range(0, W + 1, 50):
            self.canvas.create_line(gx, 0, gx, H, fill=GRID)
        for gy in range(0, H + 1, 50):
            self.canvas.create_line(0, gy, W, gy, fill=GRID)
        self.canvas.create_line(W / 2 - 12, H / 2, W / 2 + 12, H / 2, fill=CROSS)
        self.canvas.create_line(W / 2, H / 2 - 12, W / 2, H / 2 + 12, fill=CROSS)
        # 線の下に太くて暗い線を重ねて、光っているように見せる
        self.glow = self.canvas.create_line(0, 0, 0, 0, fill=TRAIL, width=12,
                                            capstyle="round", joinstyle="round", state="hidden")
        self.line = self.canvas.create_line(0, 0, 0, 0, fill=INK, width=3,
                                            capstyle="round", joinstyle="round", state="hidden")
        self.dot = self.canvas.create_oval(0, 0, 0, 0, fill="#fff", outline=INK, width=3,
                                           state="hidden")
        # 判定したジェスチャー (左上) と、実行したもの
        self.result = self.canvas.create_text(28, 24, anchor="nw", fill=INK,
                                              font=(FONT, 34, "bold"), text="")
        self.result_sub = self.canvas.create_text(30, 82, anchor="nw", fill=SUB,
                                                  font=(FONT, 11), text="")
        self.result_act = self.canvas.create_text(30, 106, anchor="nw", fill=INK,
                                                  font=(FONT, 11), text="")

        root.bind("<Key-r>", lambda e: self.replay())
        root.bind("<Escape>", lambda e: root.destroy())
        self.last_drops = 0
        self.drop_msg_until = 0.0   # 受信失敗のメッセージを出しておく時刻
        self.update()

    def to_px(self, x, z):
        # x: 右が +, z: 上が + → 画面座標 (y は下が +)
        return W / 2 + x / LIMIT * (W / 2), H / 2 - z / LIMIT * (H / 2)

    def start(self, track: XZTrack):
        # 前のストロークは薄くして残す
        if self.track is not None and len(self.track) >= 2:
            pts = [c for p in self.track for c in self.to_px(p.x, p.z)]
            self.old_lines.append(self.canvas.create_line(*pts, fill=TRAIL, width=2,
                                                          capstyle="round", joinstyle="round"))
            for old in self.old_lines[:-KEEP]:
                self.canvas.delete(old)
            self.old_lines = self.old_lines[-KEEP:]
            self.canvas.tag_raise(self.glow)
            self.canvas.tag_raise(self.line)
            self.canvas.tag_raise(self.dot)
        self.track = track
        self.play_start = time.monotonic()
        if self.recognizer is not None:
            r = self.recognizer.recognize(track)
            fired = self.actions.select(r) if self.actions else []
            ok = r.accepted or bool(fired)
            self.canvas.itemconfig(self.result, text=r.label if ok else "？", fill=INK if ok else MISS)
            why = "" if ok else f"   ·   {REASONS_JA.get(r.reason, r.reason)}" + (
                f"   ·   一番近いのは {r.label}" if r.name else "")
            self.canvas.itemconfig(self.result_sub, text=f"スコア {r.score:.2f}{why}")
            dry = "(dry-run) " if self.actions and self.actions.dry_run else ""
            self.canvas.itemconfig(self.result_act, text="\n".join(f"▸ {dry}{a.text}" for a in fired))
            if fired:
                self.actions.run(fired, r, track)
        self.canvas.itemconfig(self.glow, state="normal")
        self.canvas.itemconfig(self.line, state="normal")
        self.canvas.itemconfig(self.dot, state="normal")

    def replay(self):
        if self.track is not None:
            self.play_start = time.monotonic()

    def position(self, k):
        """k 番目 (小数) の点の位置 [px]。点と点の間は直線でつなぐ。"""
        pts = self.track.points
        k = max(0.0, min(k, len(pts) - 1))
        i = min(int(k), len(pts) - 2) if len(pts) >= 2 else 0
        f = k - i
        a = self.to_px(pts[i].x, pts[i].z)
        if len(pts) < 2:
            return a
        b = self.to_px(pts[i + 1].x, pts[i + 1].z)
        return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f

    def update(self):
        for tr in self.reader.get_new():   # 新しく届いたストローク
            self.received += 1
            self.start(tr)

        if self.track is not None and len(self.track) > 0:
            k = (time.monotonic() - self.play_start) * SAMPLE_HZ * SPEED  # 何点目まで進んだか
            done = int(min(k, len(self.track) - 1))
            pts = [c for p in self.track.points[:done + 1] for c in self.to_px(p.x, p.z)]
            cx, cy = self.position(k)
            pts += [cx, cy]
            if len(pts) >= 4:
                self.canvas.coords(self.glow, *pts)
                self.canvas.coords(self.line, *pts)
            r = 9
            self.canvas.coords(self.dot, cx - r, cy - r, cx + r, cy + r)
        if self.track is not None and time.monotonic() >= self.drop_msg_until:
            tr = self.track
            note = f"  (補間 {tr.missing} 点)" if tr.missing else ""
            self.status.config(
                text=f"ストローク id={tr.id}  {len(tr)} 点 / {tr.duration:.2f} 秒{note}   "
                     f"受信 {self.received}  失敗 {self.reader.drop_count}",
                fg=SUB)

        if self.reader.drop_count != self.last_drops:  # 受信に失敗したストロークがあった
            self.last_drops = self.reader.drop_count
            d = self.reader.drops[-1]
            self.drop_msg_until = time.monotonic() + 2.0
            self.status.config(text=f"ストロークを受け取れませんでした (id={d.id}, {d.reason})", fg=MISS)

        self.root.after(FPS_MS, self.update)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m magic_wand view",
                                 description="届いたストロークを画面に描いて、ジェスチャーを判定する")
    ap.add_argument("port", nargs="?", help="例: COM3, /dev/ttyACM0")
    ap.add_argument("--distance", type=float, default=0.6, help="感度 (大きいほど大きく描かれる)")
    ap.add_argument("--demo", action="store_true", help="実機なしのダミーデータで動かす")
    ap.add_argument("--no-gesture", action="store_true", help="ジェスチャー判定をしない")
    add_cli_args(ap)
    args = ap.parse_args(argv)
    if not args.port and not args.demo:
        ap.error("ポート名か --demo を指定してください")
    recognizer, actions = from_cli_args(ap, args)

    with SerialXZReader(
        args.port,
        projector=PointerProjector(distance=args.distance),
        ser=DemoSerial() if args.demo else None,
    ) as reader:
        reader.start()                 # 受信は別スレッド
        root = tk.Tk()
        App(root, reader, None if args.no_gesture else recognizer, actions)
        root.mainloop()                # 画面はメインスレッド (ウィンドウを閉じると with を抜けて close)

