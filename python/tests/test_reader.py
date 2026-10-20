# python -m unittest  (python/ ディレクトリで実行)
import os
import tempfile
import threading
import unittest

from magic_wand.csv_io import load_tracks
from magic_wand.projection import PointerProjector
from magic_wand.reader import SerialXZReader

from .helpers import FakeSerial, stroke_lines


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.ser = FakeSerial()
        self.got, self.drops, self.lines = [], [], []
        self.reader = SerialXZReader(ser=self.ser, on_stroke=self.got.append,
                                     on_drop=self.drops.append, on_line=self.lines.append)

    def test_split_reads(self):
        data = b"#ir_rx ready\r\n" + stroke_lines(1, [(0, 0), (90, 0)])
        for k in range(0, len(data), 7):
            self.reader.process(data[k:k + 7])
        self.assertEqual(len(self.got), 1)
        tr = self.reader.latest()
        self.assertEqual((tr.id, len(tr)), (1, 2))
        self.assertAlmostEqual(tr[1].x, 1.0)
        self.assertEqual(self.reader.resets, 1)
        self.assertEqual(self.lines, ["#ir_rx ready"])

    def test_drop_and_stats(self):
        self.reader.process(b"#drop,id=2,reason=no_info\r\n#stats,strokes=0,dropped=1,crc_err=3,interp=0\r\n")
        self.assertEqual(self.drops[0].reason, "no_info")
        self.assertEqual(self.reader.drop_count, 1)
        self.assertEqual(self.reader.stats["crc_err"], 3)
        self.assertEqual(self.lines, ["#stats,strokes=0,dropped=1,crc_err=3,interp=0"])

    def test_get_new_and_history(self):
        self.reader.process(stroke_lines(1, [(0, 0)]) + stroke_lines(2, [(0, 0)]))
        self.assertEqual([t.id for t in self.reader.get_new()], [1, 2])
        self.assertEqual(self.reader.get_new(), [])
        self.reader.process(stroke_lines(3, [(0, 0)]))
        self.assertEqual([t.id for t in self.reader.get_tracks()], [1, 2, 3])
        self.assertEqual(self.reader.stroke_count, 3)

    def test_max_tracks(self):
        r = SerialXZReader(ser=FakeSerial(), max_tracks=2)
        r.process(b"".join(stroke_lines(i, [(0, 0)]) for i in range(5)))
        self.assertEqual([t.id for t in r.get_tracks()], [3, 4])
        self.assertEqual(r.stroke_count, 5)

    def test_wait_stroke_without_thread(self):
        self.ser.feed(stroke_lines(7, [(0, 0), (1, 1)]))
        tr = self.reader.wait_stroke(timeout=1.0)
        self.assertEqual(tr.id, 7)
        self.assertIsNone(self.reader.wait_stroke(timeout=0.05))

    def test_wait_stroke_with_thread(self):
        self.reader.start()
        try:
            threading.Timer(0.05, lambda: self.ser.feed(stroke_lines(9, [(0, 0)]))).start()
            tr = self.reader.wait_stroke(timeout=2.0)
            self.assertEqual(tr.id, 9)
            self.assertIsNone(self.reader.wait_stroke(timeout=0.05))
        finally:
            self.reader.stop()

    def test_pointer_projector(self):
        r = SerialXZReader(ser=FakeSerial(), projector=PointerProjector(distance=2.0))
        r.process(stroke_lines(1, [(0, 0), (45, 0)]))
        self.assertAlmostEqual(r.latest()[1].x, 2.0)

    def test_log_csv_roundtrip(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        self.addCleanup(os.remove, path)
        r = SerialXZReader(ser=FakeSerial(), log_csv=path)
        r.process(stroke_lines(1, [(0, 0), (1.5, -2.5)]) + stroke_lines(2, [(3, 4)]))
        r.close()
        tracks = load_tracks(path)
        self.assertEqual([t.id for t in tracks], [1, 2])
        self.assertEqual(tracks[0].get_angles(), [(0, 0), (1.5, -2.5)])

    def test_close(self):
        with SerialXZReader(ser=self.ser) as r:
            r.process(b"")
        self.assertTrue(self.ser.closed)


if __name__ == "__main__":
    unittest.main()
