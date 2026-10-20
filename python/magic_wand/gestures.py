# gestures.py — 杖のストローク (XZTrack) を $1 Unistroke Recognizer でジェスチャーとして判定する
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
#   python -m magic_wand gestures COM3      # ストロークが届くたびに判定して表示する
#   python -m magic_wand gestures --demo    # 実機なし (ダミーデータ)
#   python -m magic_wand gestures COM3 --on circle=lights.py --on square@0.9=notepad.exe
#                                           # 丸を描いたら lights.py、四角を 0.9 以上で描いたら notepad
#                                           # (--on の書き方は actions.py)
#
#   from magic_wand import GestureRecognizer, PointerProjector, SerialXZReader
#   rec = GestureRecognizer()
#   reader = SerialXZReader("COM3", projector=PointerProjector(), on_stroke=lambda t: print(rec.recognize(t)))
#
# 座標は PointerProjector で出したもの (x = 右が +, z = 上が +) を前提にしている。
# 棒の先端モード (project_xz) は上下の動きがほとんど出ないので使わないこと。
#
# $1 の性質 (ジェスチャーを選ぶときの注意):
#   - 回転を区別しない (向きをそろえてから比べる)。「右へ払う」と「上へ払う」は見分けられない
#   - 縦横の大きさを別々にそろえる。まっすぐな線は高さがほぼ 0 なので、ノイズが拡大されて不安定
#   - 描き始めの位置 (丸のどこから描くか、四角のどの角から描くか) は関係ない
#   - 鏡に映した形 (時計回りと反時計回り) は別物になる。ここでは鏡像も同じジェスチャーとして
#     登録しているので、どちら回りで描いても、ジャイロの左右の符号が逆でも認識できる
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from dollar_one_recognizer_py import dollar_one_recognizer

from . import style
from .actions import Action, GestureActions, parse_action
from .demo import DemoSerial
from .projection import PointerProjector
from .reader import SerialXZReader
from .templates import CLOSED, LABELS_JA, TEMPLATES, Point
from .track import StrokeDrop, XZTrack


_MIRROR = "~mirror"


@dataclass(frozen=True)
class GestureResult:
    name: Optional[str]  # 認識したジェスチャー。accepted が False でも一番近かったものが入る
    score: float         # 0〜1 ($1 のスコア。1 に近いほど似ている)
    accepted: bool       # score がしきい値以上で、ストロークが小さすぎない
    reason: str = ""     # 受け付けなかった理由: "low_score" / "too_small" / "too_short" /
    #                      "not_closed" (閉じた形のはずが閉じていない) / "closed" (その逆)

    @property
    def label(self) -> str:
        return LABELS_JA.get(self.name or "", self.name or "")

    def __str__(self) -> str:
        mark = "OK" if self.accepted else f"NG({self.reason})"
        return f"{self.label} {self.score:.2f} {mark}"


class GestureRecognizer:
    """XZTrack (または [(x, z), ...]) を受け取り、TEMPLATES のどれに近いかを返す。"""

    def __init__(
        self,
        gestures: Optional[Iterable[str]] = None,
        threshold: float = 0.80,
        mirror: bool = True,
        min_size: float = 0.05,
        min_points: int = 5,
        templates: Optional[Dict[str, Sequence[Point]]] = None,
        closed: Optional[Dict[str, bool]] = None,
        n: int = 64,
        size: float = 250,
    ):
        """
        gestures:   使うジェスチャーの名前 (既定は TEMPLATES 全部)
        threshold:  これ以上のスコアで受け付ける
        mirror:     鏡像 (逆回り) も同じジェスチャーとして受け付ける
        min_size:   縦横の大きい方がこれ未満のストロークは「小さすぎ」として受け付けない
                    (PointerProjector(distance=1) なら 0.05 ≈ 3°)
        min_points: 点がこれ未満のストロークは受け付けない
        templates:  自分のテンプレート {名前: [(x, y), ...]} を足す (y は上が +)
        closed:     自分のテンプレートが閉じた形かどうか {名前: True/False} (省略すると調べない)
        """
        all_t = dict(TEMPLATES)
        if templates:
            all_t.update(templates)
        names = list(gestures) if gestures is not None else list(all_t)
        unknown = [g for g in names if g not in all_t]
        if unknown:
            raise ValueError(f"知らないジェスチャー: {unknown} (使えるもの: {list(all_t)})")

        self.closed = dict(CLOSED)
        if closed:
            self.closed.update(closed)
        self.threshold = threshold
        self.min_size = min_size
        self.min_points = min_points
        pts, keys = [], []
        for g in names:
            pts.append(all_t[g])
            keys.append(g)
            if mirror:
                pts.append([(-x, y) for x, y in all_t[g]])
                keys.append(g + _MIRROR)
        self._rec = dollar_one_recognizer(size=size, templates=pts, templates_name=keys, n=n)
        self.gestures = names

    def recognize(self, stroke: Union[XZTrack, Sequence[Point]]) -> GestureResult:
        xy = stroke.get_xz() if hasattr(stroke, "get_xz") else [tuple(p) for p in stroke]
        if len(xy) < self.min_points:
            return GestureResult(None, 0.0, False, "too_short")
        xs = [p[0] for p in xy]
        ys = [p[1] for p in xy]
        extent = max(max(xs) - min(xs), max(ys) - min(ys))
        if extent < self.min_size:
            return GestureResult(None, 0.0, False, "too_small")
        try:
            _, key, score = self._rec.recognize(xy)
        except ValueError:
            return GestureResult(None, 0.0, False, "too_small")  # 全部同じ点など
        name = key.split(_MIRROR)[0]
        score = float(score)
        if score < self.threshold:
            return GestureResult(name, score, False, "low_score")
        # 始点と終点の距離 (大きさに対する割合) で、閉じた形かどうかを確かめる
        gap = math.dist(xy[0], xy[-1]) / extent
        want = self.closed.get(name)
        if want is True and gap > 0.35:
            return GestureResult(name, score, False, "not_closed")
        if want is False and gap < 0.5:
            return GestureResult(name, score, False, "closed")
        return GestureResult(name, score, True)

    __call__ = recognize


# ---------------------------------------------------------------- コマンドライン
REASONS_JA = {
    "low_score": "スコア不足", "too_small": "小さすぎ", "too_short": "短すぎ",
    "not_closed": "閉じていない", "closed": "閉じてしまった",
}


def add_cli_args(ap: argparse.ArgumentParser) -> None:
    """判定と --on のオプションを足す (gestures と view で共通)。"""
    g = ap.add_argument_group("判定")
    g.add_argument("--threshold", type=float, default=0.80, metavar="0〜1",
                   help="このスコア以上で受け付ける (既定 0.80)")
    g.add_argument("--only", metavar="名前,名前", help="使うジェスチャーをしぼる (例: circle,square)")
    a = ap.add_argument_group("実行 (--on は何度でも書ける)")
    a.add_argument("--on", action="append", default=[], metavar="名前[@しきい値]=実行するもの",
                   help="例: circle=lights.py / square@0.9=notepad.exe / zigzag=mymod:func / "
                        '"*=cmd:echo {label}"。くわしくは README の「ジェスチャーで何かを実行する」')
    a.add_argument("--cooldown", type=float, default=1.0, metavar="秒",
                   help="同じ --on を続けて実行しない時間 (既定 1.0)")
    a.add_argument("--dry-run", action="store_true", help="実行せず、何が実行されるかだけ表示する")


def from_cli_args(ap: argparse.ArgumentParser, args) -> Tuple[GestureRecognizer, GestureActions]:
    """add_cli_args() で足したオプションから、判定器と GestureActions を作る。"""
    if not 0.0 <= args.threshold <= 1.0:
        ap.error("--threshold は 0〜1 で指定してください")
    only = [g.strip() for g in args.only.split(",") if g.strip()] if args.only else None
    try:
        recognizer = GestureRecognizer(gestures=only, threshold=args.threshold)
        actions = [parse_action(spec, args.cooldown, recognizer.gestures) for spec in args.on]
    except (ValueError, ImportError, OSError, SyntaxError) as e:
        ap.error(str(e))
    return recognizer, GestureActions(recognizer, actions, dry_run=args.dry_run)


def print_actions(actions: GestureActions) -> None:
    if not actions.actions:
        print(f"  {style.gray('--on がないので判定結果を表示するだけです')}")
        return
    for a in actions.actions:
        name = "どれでも" if a.gesture == "*" else LABELS_JA.get(a.gesture, a.gesture)
        th = actions.threshold if a.threshold is None else a.threshold
        print(f"  {style.cyan(style.RUN)} {style.bold(style.pad(name, 16))}"
              f"{style.gray(f'≥{th:.2f}')}  {style.ARROW} {a.text}  {style.gray(a.kind)}")
    if actions.dry_run:
        print(f"  {style.yellow('--dry-run: 実行はしません')}")


def print_result(r: GestureResult, track: XZTrack, fired: Sequence[Action] = (),
                 threshold: float = 0.80, dry_run: bool = False) -> None:
    """1 ストロークの判定結果を 1 行 (+ 実行したもの) で表示する。"""
    if r.accepted or fired:
        mark, name = style.green(style.OK), style.bold(style.green(style.pad(r.label, 16)))
    else:
        mark = style.red(style.NG)
        near = f"{r.label}?" if r.name else "？"
        name = style.gray(style.pad(near, 16))
    note = "" if r.accepted else style.gray(REASONS_JA.get(r.reason, r.reason))
    print(f"  {style.stamp(track.received_at)}  {mark} {name}"
          f"{style.score_bar(r.score, threshold)} {style.bold(f'{r.score:.2f}')}  {note}", flush=True)
    for a in fired:
        verb = "(dry-run) " if dry_run else ""
        print(f"  {' ' * 8}    {style.cyan(style.RUN)} {style.gray(verb)}{a.text}", flush=True)


def print_drop(d: StrokeDrop) -> None:
    print(f"  {style.stamp(d.received_at)}  {style.red(style.DROP)} "
          f"{style.red(style.pad('受信に失敗', 16))}{style.gray(d.reason)}")


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m magic_wand gestures",
                                 description="ストロークが届くたびにジェスチャーを判定して、--on で決めたものを実行する")
    ap.add_argument("port", nargs="?", help="例: COM3, /dev/ttyACM0")
    ap.add_argument("--demo", action="store_true", help="実機なしのダミーデータで動かす")
    ap.add_argument("--list", action="store_true", help="使えるジェスチャーの名前を表示して終わる")
    ap.add_argument("--no-color", action="store_true", help="色を付けない")
    add_cli_args(ap)
    args = ap.parse_args(argv)
    if args.no_color:
        style.set_color(False)
    if args.list:
        for name in TEMPLATES:
            kind = "閉じた形" if CLOSED.get(name) else "開いた形"
            print(f"  {style.bold(style.pad(name, 13))} {style.pad(LABELS_JA.get(name, name), 14)}"
                  f"{style.gray(kind)}")
        return
    if not args.port and not args.demo:
        ap.error("ポート名か --demo を指定してください")
    recognizer, actions = from_cli_args(ap, args)

    def on_stroke(track: XZTrack) -> None:
        r = recognizer.recognize(track)
        fired = actions.select(r)
        print_result(r, track, fired, recognizer.threshold, actions.dry_run)
        actions.run(fired, r, track)

    style.banner("gestures", args.port or "demo", f"しきい値 {recognizer.threshold:.2f}",
                 f"{len(recognizer.gestures)} 種類")
    print_actions(actions)
    print(f"  {style.gray('杖を振って止めると判定します  (Ctrl+C で終了)')}\n")
    demo = DemoSerial() if args.demo else None
    with SerialXZReader(args.port, projector=PointerProjector(), ser=demo,
                        on_stroke=on_stroke, on_drop=print_drop) as reader:
        try:
            reader.run()
        except KeyboardInterrupt:
            pass
        print(f"\n  {style.gray(f'受信 {reader.stroke_count}  失敗 {reader.drop_count}')}")
