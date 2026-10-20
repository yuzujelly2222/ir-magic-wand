# python -m unittest  (python/ ディレクトリで実行)
import os
import tempfile
import unittest

from magic_wand.csv_io import load_tracks, parse_tracks, save_tracks
from magic_wand.track import XZTrack

from .fixture_firmware import RX_POINTS, TX_FRAMES
from .helpers import RX_OUTPUT


class CsvTest(unittest.TestCase):
    def tmp(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_save_and_load(self):
        a = XZTrack([(0, 0), (1.5, -2.5)], id=3)
        b = XZTrack([(10, 20)], id=4)
        path = self.tmp("")
        save_tracks(path, [a, b])
        tracks = load_tracks(path)
        self.assertEqual([t.id for t in tracks], [3, 4])
        self.assertEqual(tracks[0].get_angles(), [(0, 0), (1.5, -2.5)])

    def test_rx_output_file(self):
        tracks = load_tracks(self.tmp("\n".join(RX_OUTPUT)), arm_length=2.0)
        self.assertEqual(len(tracks), 1)
        self.assertAlmostEqual(tracks[0][3].x, 2.0)

    def test_headerless_and_unsorted(self):
        tracks = parse_tracks(["1,1,5,6", "1,0,1,2", "2,0,7,8"])
        self.assertEqual([t.get_angles() for t in tracks], [[(1, 2), (5, 6)], [(7, 8)]])
        one = parse_tracks(["yaw,pitch", "1,2", "3,4", "bad,row"])
        self.assertEqual(one[0].get_angles(), [(1, 2), (3, 4)])

    def test_packet_column(self):
        rows = ["time_ms,packet"] + [f"{100 * k},{h}" for k, h in enumerate(TX_FRAMES)]
        tracks = parse_tracks(rows)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0]), len(RX_POINTS))
        self.assertAlmostEqual(tracks[0].get_angles()[5][0], RX_POINTS[5][0], places=4)

    def test_sample_csv(self):
        here = os.path.dirname(os.path.abspath(__file__))
        tracks = load_tracks(os.path.join(here, "..", "examples", "sample.csv"))
        self.assertGreaterEqual(len(tracks), 2)
        for tr in tracks:
            self.assertEqual(tr.get_angles()[0], (0.0, 0.0))  # 開始点は相対角 0

    def test_bad_header(self):
        with self.assertRaises(ValueError):
            parse_tracks(["stroke,foo", "1,2"])


if __name__ == "__main__":
    unittest.main()
