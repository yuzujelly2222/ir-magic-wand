# python -m unittest  (python/ ディレクトリで実行)
import random
import unittest

from magic_wand.demo import DemoSerial
from magic_wand.gestures import GestureRecognizer
from magic_wand.projection import PointerProjector
from magic_wand.templates import TEMPLATES
from magic_wand.track import XZTrack


# ほぼ同じ形なので、手ぶれがあると取り違えることがある (GESTURES.md の「区別できないもの」)
SAME_SHAPE = {"keyhole", "circle_down"}


def same(a, b):
    return a == b or {a, b} <= SAME_SHAPE


class GestureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rec = GestureRecognizer()
        cls.proj = PointerProjector()

    def track(self, pts):
        return XZTrack(pts, projector=self.proj)

    def test_templates_match_themselves(self):
        for name, pts in TEMPLATES.items():
            r = self.rec.recognize(pts)
            self.assertEqual((r.name, r.accepted), (name, True), name)

    def test_noisy_wand_strokes(self):
        # 手ぶれ・ゆがみ・速さのむらを足した杖のストローク (度) を、XZTrack 経由で判定する
        rnd = random.Random(3)
        for name in TEMPLATES:
            ok = 0
            for _ in range(20):
                ok += same(self.rec.recognize(self.track(DemoSerial.make_points(name, rnd))).name, name)
            self.assertGreaterEqual(ok, 18, name)

    def test_mirror_and_flipped_axes(self):
        # 逆回りに描いた / ジャイロの左右や上下の符号が逆でも同じジェスチャーになる
        rnd = random.Random(4)
        for name in TEMPLATES:
            pts = DemoSerial.make_points(name, rnd)
            for fx, fy in ((-1, 1), (1, -1), (-1, -1)):
                r = self.rec.recognize(self.track([(fx * x, fy * y) for x, y in pts]))
                self.assertTrue(same(r.name, name), (r.name, name, fx, fy))

    def test_reject(self):
        self.assertEqual(self.rec.recognize([(0, 0), (0.01, 0.01)] * 5).reason, "too_small")
        self.assertEqual(self.rec.recognize([(0, 0), (1, 1)]).reason, "too_short")
        # まっすぐな線: チェックを外せば受け付けない
        # (チェックがあるとチェックと判定されやすい。GESTURES.md の「確かめた結果」)
        line = [(i * 0.5, i * 0.1) for i in range(40)]
        rec = GestureRecognizer(gestures=["circle", "triangle", "square", "zigzag"])
        self.assertFalse(rec.recognize(self.track(line)).accepted)

    def test_subset_and_custom(self):
        rec = GestureRecognizer(gestures=["circle", "check"])
        self.assertEqual(rec.gestures, ["circle", "check"])
        with self.assertRaises(ValueError):
            GestureRecognizer(gestures=["nope"])
        heart = [(0, -1), (1, 0.3), (0.5, 1), (0, 0.5), (-0.5, 1), (-1, 0.3), (0, -1)]
        rec2 = GestureRecognizer(templates={"heart": heart}, closed={"heart": True})
        self.assertEqual(rec2.recognize(heart).name, "heart")


if __name__ == "__main__":
    unittest.main()
