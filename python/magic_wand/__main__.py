# python -m magic_wand <コマンド> [引数...]
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
#   python -m magic_wand listen   COM3            受信して座標を表示する
#   python -m magic_wand gestures COM3 | --demo   受信してジェスチャーを判定する
#        ... --on circle=lights.py                 丸を描いたら lights.py を実行する
#   python -m magic_wand view     COM3 | --demo   描いた形と判定結果を画面に出す (tkinter)
#   python -m magic_wand csv      sample.csv      保存した CSV の中身を表示する
import sys

from . import __version__, csv_io, gestures, reader, style, viewer

COMMANDS = {
    "listen": (reader.main, "受信して座標を表示する"),
    "gestures": (gestures.main, "受信してジェスチャーを判定し、--on で決めたものを実行する"),
    "view": (viewer.main, "描いた形と判定結果を画面に出す"),
    "csv": (csv_io.main, "保存した CSV の中身を表示する"),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"\n  {style.magenta(style.SPARK)} {style.bold('magic_wand')} {style.gray(__version__)}"
              f"   {style.gray('杖で描いたジェスチャーを受け取って判定する')}\n")
        print(f"  {style.bold('usage')}  python -m magic_wand {style.cyan('<コマンド>')} [引数...]\n")
        for name, (_, desc) in COMMANDS.items():
            print(f"    {style.cyan(f'{name:9s}')} {desc}")
        print(f"\n  {style.gray('例')}     python -m magic_wand gestures --demo --on circle=cmd:echo 丸!")
        print(f"  {style.gray('くわしくは python -m magic_wand <コマンド> -h')}\n")
        sys.exit(0 if len(sys.argv) < 2 else 2)
    COMMANDS[sys.argv[1]][0](sys.argv[2:])


if __name__ == "__main__":
    main()
