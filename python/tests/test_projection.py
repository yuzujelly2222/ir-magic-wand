# python -m unittest  (python/ ディレクトリで実行)
import unittest

from magic_wand.projection import PointerProjector, project_xz


class ProjectionTest(unittest.TestCase):
    def test_axes(self):
        x, z = project_xz(0, 0, 1.0)
        self.assertAlmostEqual(x, 0)
        self.assertAlmostEqual(z, 1)
        x, z = project_xz(0, 90, 2.0)  # 右を向くと x = +L
        self.assertAlmostEqual(x, 2)
        self.assertAlmostEqual(z, 0)
        x, z = project_xz(60, 0, 1.0)  # 上に傾けると根元に近づく
        self.assertAlmostEqual(z, 0.5)

    def test_pointer(self):
        pp = PointerProjector(distance=2.0)
        self.assertEqual(pp(0, 0, 1.0), (0.0, 0.0))  # ストロークの書き始め = 中央
        x, z = pp(0, 45, 1.0)
        self.assertAlmostEqual(x, 2.0)
        x, z = pp(45, 0, 1.0)
        self.assertAlmostEqual(z, 2.0)
        x, z = PointerProjector(max_angle=30, limit=0.5)(80, -80, 1.0)
        self.assertEqual((x, z), (-0.5, 0.5))


if __name__ == "__main__":
    unittest.main()
