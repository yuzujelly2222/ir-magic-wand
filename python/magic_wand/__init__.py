# magic_wand — 杖 (ATtiny85 + MPU-6050) から赤外線で届いたストロークを受け取り、
#              x, z 座標の軌跡にして、ジェスチャーとして判定するライブラリ
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
#   from magic_wand import GestureRecognizer, PointerProjector, SerialXZReader
#
# モジュール:
#   protocol    IR パケットの定義 (firmware の protocol.h の Python 版)
#   assembler   パケットから 1 ストロークを組み立てる (firmware/ir_rx の Python 版)
#   projection  角度を x, z 座標に直す方法 (project_xz / PointerProjector)
#   track       1 ストロークの点列 XZTrack / XZPoint / StrokeDrop
#   parser      受信機が USB シリアルに出す行を読む StrokeParser
#   csv_io      CSV の読み書き (load_tracks / save_tracks)
#   reader      シリアルから受信する SerialXZReader
#   templates   ジェスチャーの見本
#   gestures    ジェスチャーの判定 GestureRecognizer
#   actions     ジェスチャーを描いたら関数・ファイル・コマンドを実行する GestureActions
#   demo        実機なしで試すためのダミーの受信機 DemoSerial
#   viewer      届いたストロークを画面に描く tkinter のビューア
#   style       コマンドラインの見た目 (色・記号)
#
# コマンド (python -m magic_wand <コマンド> -h でくわしく):
#   listen   COM3 [--pointer] [--log log.csv]   受信して座標を表示する
#   gestures COM3 | --demo [--on 名前=実行するもの]   受信してジェスチャーを判定し、実行する
#   view     COM3 | --demo                      描いた形と判定結果を画面に出す
#   csv      file.csv [--pointer]               保存した CSV の中身を表示する
from .actions import Action, GestureActions, parse_action
from .assembler import AssembledStroke, Dropped, Framer, StrokeAssembler
from .csv_io import load_tracks, parse_tracks, save_tracks
from .demo import DemoSerial
from .gestures import GestureRecognizer, GestureResult
from .parser import StrokeParser, parse_stats
from .projection import PointerProjector, Projector, project_xz
from .reader import RX_BAUD, SerialXZReader
from .templates import CLOSED, LABELS_JA, TEMPLATES
from .track import StrokeDrop, XZPoint, XZTrack

__version__ = "1.1.0"

__all__ = [
    "Action", "GestureActions", "parse_action",
    "AssembledStroke", "Dropped", "Framer", "StrokeAssembler",
    "load_tracks", "parse_tracks", "save_tracks",
    "DemoSerial",
    "GestureRecognizer", "GestureResult",
    "StrokeParser", "parse_stats",
    "PointerProjector", "Projector", "project_xz",
    "RX_BAUD", "SerialXZReader",
    "CLOSED", "LABELS_JA", "TEMPLATES",
    "StrokeDrop", "XZPoint", "XZTrack",
]
