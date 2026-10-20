# python -m unittest  (python/ ディレクトリで実行)
import random
import unittest

from magic_wand.demo import DemoSerial
from magic_wand.parser import StrokeParser
from magic_wand.templates import TEMPLATES
from magic_wand.track import StrokeDrop, XZTrack


class DemoSerialTest(unittest.TestCase):
    def test_points_start_at_origin(self):
        rnd = random.Random(1)
        for name in list(TEMPLATES) + ["line"]:
            pts = DemoSerial.make_points(name, rnd)
            self.assertEqual(pts[0], (0.0, 0.0))
            self.assertTrue(12 <= len(pts) <= 100, (name, len(pts)))

    def test_output_is_parseable(self):
        demo = DemoSerial(period=0.0, seed=2)
        parser = StrokeParser()
        events = []
        buf = b""
        while len(events) < 10:
            demo.next = 0.0  # すぐに次のストロークを出す
            buf += demo.read(4096)
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                events += parser.feed(ln.decode())
        self.assertTrue(all(isinstance(e, (XZTrack, StrokeDrop)) for e in events))
        self.assertTrue(any(isinstance(e, XZTrack) for e in events))
        self.assertEqual(parser.resets, 1)


if __name__ == "__main__":
    unittest.main()
