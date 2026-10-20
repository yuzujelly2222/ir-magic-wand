# python -m unittest  (python/ ディレクトリで実行)
import unittest

from magic_wand.projection import PointerProjector
from magic_wand.track import XZTrack


class TrackTest(unittest.TestCase):
    def test_track(self):
        tr = XZTrack([(0, 0), (90, 0)], id=5, missing=1, arm_length=2.0)
        self.assertEqual(len(tr), 2)
        self.assertEqual(tr.id, 5)
        self.assertAlmostEqual(tr[1].x, 2.0)
        self.assertAlmostEqual(tr[1].t, 1 / 25)
        self.assertAlmostEqual(tr.duration, 1 / 25)
        self.assertEqual(tr.get_angles(), [(0, 0), (90, 0)])
        self.assertEqual(len(tr.get_xz()), 2)
        tr2 = tr.reproject(PointerProjector())
        self.assertAlmostEqual(tr2[0].x, 0.0)
        self.assertEqual(tr2.id, 5)

    def test_custom_projector(self):
        tr = XZTrack([(1.0, 2.0)], projector=lambda p, y, L: (y * L, p * L), arm_length=3.0)
        self.assertEqual(tr.get_xz(), [(3.0, 6.0)])


if __name__ == "__main__":
    unittest.main()
