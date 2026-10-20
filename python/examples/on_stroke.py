# on_stroke.py — 自分のプログラムでジェスチャーを使ういちばん短い例
#
#   pip install -e python      # リポジトリのいちばん上で 1 回だけ
#   python examples/on_stroke.py COM3
#
# ストロークが届くたびに on_stroke() が呼ばれるので、ジェスチャーごとの処理をここに書く。
import sys

from magic_wand import GestureRecognizer, PointerProjector, SerialXZReader, XZTrack

recognizer = GestureRecognizer()  # 丸・三角・四角・チェック・Z


def on_stroke(track: XZTrack) -> None:
    """ストロークが 1 本届くたびに呼ばれる (受信スレッドから)。"""
    r = recognizer.recognize(track)
    if not r.accepted:
        return
    if r.name == "circle":
        print("丸を描いた")
    elif r.name == "zigzag":
        print("Z を描いた")
    else:
        print(r.label, r.score)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python on_stroke.py <シリアルポート>")
    with SerialXZReader(sys.argv[1], projector=PointerProjector(), on_stroke=on_stroke) as reader:
        reader.run()
