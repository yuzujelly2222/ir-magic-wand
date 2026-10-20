# python -m unittest  (python/ ディレクトリで実行)
import random
import unittest

from magic_wand.assembler import Dropped, Framer, StrokeAssembler
from magic_wand.protocol import INFO_BEGIN, NO_POINT, decode, encode_stroke

from .helpers import circle, run_frames


class AssemblerTest(unittest.TestCase):
    def test_lost_data_is_interpolated(self):
        frames = encode_stroke(1, circle(50, 30))
        out = run_frames(frames, drop={5})
        self.assertEqual(out[0].missing, 4)
        self.assertEqual(len(out[0].points), 50)

    def test_lost_packet_does_not_shift_later_points(self):
        # アンカーがあるので、落としたパケットより後ろの点はロスなしと同じ
        frames = encode_stroke(1, circle(100, 40))
        full = run_frames(frames)[0].points
        lost = run_frames(frames, drop={3})[0].points
        self.assertEqual(full[16:], lost[16:])

    def test_end_lost_finalizes_on_timeout(self):
        frames = encode_stroke(2, circle(20, 10))
        asm = StrokeAssembler()
        t = 0.0
        for f in frames[:-1]:
            t += 0.1
            self.assertEqual(asm.push(decode(f), t), [])
        self.assertEqual(asm.poll(t + 0.1), [])
        out = asm.poll(t + StrokeAssembler.TIMEOUT)
        self.assertEqual(len(out[0].points), 20)

    def test_both_info_lost_still_ok(self):
        # 点数は DATA から分かるので、INFO を両方落としても捨てない
        frames = encode_stroke(3, circle(20, 10))
        out = run_frames(frames, drop={0, len(frames) - 1})
        self.assertNotIsInstance(out[0], Dropped)
        self.assertEqual(len(out[0].points), 20)

    def test_too_many_lost(self):
        frames = encode_stroke(4, circle(50, 30))
        out = run_frames(frames, drop=set(range(1, 9)))
        self.assertEqual(out[0].reason, "too_many_lost")

    def test_repeat_fills_and_outputs_once(self):
        frames = encode_stroke(5, circle(50, 30), repeat=2)
        out = run_frames(frames, drop={3, 9})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].missing, 0)

    def test_next_stroke_before_end(self):
        a = encode_stroke(6, circle(20, 10))[:-1]
        b = encode_stroke(7, circle(30, 20))
        out = run_frames(a + b)
        self.assertEqual([len(s.points) for s in out], [20, 30])

    def test_same_sid_after_reboot(self):
        f = encode_stroke(0, circle(10, 5))
        asm = StrokeAssembler()
        got = []
        for t0 in (0.0, 10.0):
            t = t0
            for x in f:
                t += 0.1
                got += asm.push(decode(x), t)
        self.assertEqual(len(got), 2)

    def test_framer_resync(self):
        frames = encode_stroke(8, circle(20, 10))
        noise = bytes([0x12, 0xAA, 0x00, 0x99])
        data = noise + b"".join(frames[:2]) + bytes([0xAA, 0x01]) + b"".join(frames[2:])
        fr = Framer()
        pks = fr.push(data[:7]) + fr.push(data[7:])
        self.assertEqual(len(pks), len(frames))
        self.assertGreater(fr.crc_errors, 0)

    def test_random_loss(self):
        rnd = random.Random(1)
        ok = 0
        for s in range(200):
            frames = encode_stroke(s & 255, circle(50, 30))
            out = run_frames(frames, drop={k for k in range(len(frames)) if rnd.random() < 0.05})
            ok += sum(1 for e in out if not isinstance(e, Dropped))
        self.assertGreater(ok, 190)

    def test_no_point_marker(self):
        self.assertEqual(NO_POINT, -128)
        self.assertEqual(INFO_BEGIN, 0)


if __name__ == "__main__":
    unittest.main()
