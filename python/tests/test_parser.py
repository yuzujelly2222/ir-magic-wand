# python -m unittest  (python/ ディレクトリで実行)
import unittest

from magic_wand.parser import StrokeParser, parse_stats
from magic_wand.track import StrokeDrop, XZTrack

from .helpers import RX_OUTPUT


class ParserTest(unittest.TestCase):
    def feed_all(self, lines):
        p = StrokeParser()
        return p, [e for ln in lines for e in p.feed(ln, 1.0)]

    def test_rx_output(self):
        p, ev = self.feed_all(RX_OUTPUT)
        tr, drop = ev
        self.assertIsInstance(tr, XZTrack)
        self.assertEqual((tr.id, len(tr), tr.missing), (3, 4, 1))
        self.assertEqual(tr.get_angles()[2], (10.0, 20.0))
        self.assertEqual(drop, StrokeDrop(4, "too_many_lost", 1.0))
        self.assertEqual(p.stats, {"strokes": 1, "dropped": 0, "crc_err": 2, "interp": 1})
        self.assertEqual(p.resets, 1)

    def test_broken_line(self):
        lines = ["#stroke_begin,id=1,n=2,missing=0", "pt,1.0,2.0", "pt,1.0,x", "#stroke_end"]
        _, ev = self.feed_all(lines)
        self.assertEqual(ev[0].reason, "broken_line")

    def test_missing_lines(self):
        lines = ["#stroke_begin,id=1,n=3,missing=0", "pt,1.0,2.0", "#stroke_end"]
        _, ev = self.feed_all(lines)
        self.assertEqual(ev[0].reason, "incomplete")

    def test_begin_without_end(self):
        lines = ["#stroke_begin,id=1,n=1,missing=0", "pt,1.0,2.0",
                 "#stroke_begin,id=2,n=1,missing=0", "pt,3.0,4.0", "#stroke_end"]
        _, ev = self.feed_all(lines)
        self.assertEqual(ev[0], StrokeDrop(1, "incomplete", 1.0))
        self.assertEqual(ev[1].id, 2)

    def test_started_mid_stroke(self):
        _, ev = self.feed_all(["pt,1.0,2.0", "#stroke_end"])
        self.assertEqual(ev, [])

    def test_parse_stats(self):
        self.assertEqual(parse_stats("#stats,strokes=2,dropped=x"), {"strokes": 2})


if __name__ == "__main__":
    unittest.main()
