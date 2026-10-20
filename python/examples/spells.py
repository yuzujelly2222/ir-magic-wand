# spells.py — ジェスチャーを描いたら呼ばれる関数の例
#
# コマンドラインから (ファイル名:関数名 で指定する):
#   python -m magic_wand gestures --demo --on circle=examples/spells.py:lights_on \
#                                        --on wave@0.85=examples/spells.py:on_wave
#
# 自分のプログラムから:
#   python examples/spells.py COM3      (--demo なら実機なし)
#
# 関数は f() / f(result) / f(result, track) のどれでもよい。
#   result: GestureResult (result.name, result.label, result.score)
#   track:  XZTrack (描いた軌跡。track.get_xz() で [(x, z), ...])
import sys

from magic_wand import DemoSerial, GestureActions, GestureRecognizer, PointerProjector, SerialXZReader


def lights_on(result):
    print(f"  ✦ 明かりをつける! ({result.label} {result.score:.2f})")


def on_wave(result, track):
    print(f"  ✦ 波を描いた! {len(track)} 点 / {track.duration:.2f} 秒")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python spells.py <シリアルポート | --demo>")
    actions = GestureActions(GestureRecognizer())
    actions.on("circle", lights_on)
    actions.on("wave", on_wave, threshold=0.85)
    actions.on("square", "cmd:echo 四角を {score} で描いた")  # --on の右辺と同じ書き方もできる

    @actions.on("zigzag")
    def on_zigzag():
        print("  ✦ Z!")

    demo = DemoSerial() if sys.argv[1] == "--demo" else None
    port = None if demo else sys.argv[1]
    with SerialXZReader(port, projector=PointerProjector(), ser=demo, on_stroke=actions.handle) as reader:
        reader.run()
