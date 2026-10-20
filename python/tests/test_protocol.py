# python -m unittest  (python/ ディレクトリで実行)
import unittest

from magic_wand.protocol import (INFO_END, MAX_POINTS, PACKET_SIZE, PAYLOAD_SIZE, UNIT_DEG, Packet,
                                 crc8, decode, encode, encode_stroke, make_data, make_info,
                                 pack_anchor, quantize, unpack_anchor)

from .fixture_firmware import RX_MISSING, RX_POINTS, RX_SID, TX_FRAMES
from .helpers import circle, run_frames


class PacketTest(unittest.TestCase):
    def test_roundtrip_and_crc(self):
        pk = make_data(7, 3, (100, -2000), [(10, -20), (127, -127)])
        f = encode(pk)
        self.assertEqual(len(f), PACKET_SIZE)
        self.assertEqual(f[0], 0xAA)
        self.assertEqual(decode(f), pk)
        # アンカー + 差分を足し戻した絶対座標。4 点目は「点なし」
        self.assertEqual(pk.points(), [(3, 100, -2000), (4, 110, -2020), (5, 237, -2147)])
        bad = bytearray(f)
        bad[5] ^= 0x01
        self.assertIsNone(decode(bytes(bad)))
        self.assertIsNone(decode(f[:-1]))

    def test_idx_out_of_range_rejected(self):
        self.assertIsNone(decode(encode(make_data(0, MAX_POINTS, (0, 0), []))))
        info = decode(encode(make_info(1, 10, INFO_END, 2)))
        self.assertTrue(info.is_info)
        self.assertEqual(info.b[:3], (10, INFO_END, 2))

    def test_anchor_12bit(self):
        for x, y in [(0, 0), (2047, -2048), (-1, 1), (-1234, 567)]:
            self.assertEqual(unpack_anchor(pack_anchor(x, y)), (x, y))

    def test_crc8_known_value(self):
        self.assertEqual(crc8(b"123456789"), 0xF4)  # CRC-8 (poly 0x07) のチェック値

    def test_whitening(self):
        # 値が 0 でも、ヘッダ以外は 0x55 になる (キャリアが連続しないように)
        f = encode(Packet(0, 0, (0,) * PAYLOAD_SIZE))
        self.assertTrue(all(b == 0x55 for b in f[1:PACKET_SIZE - 1]))


class CompatibilityTest(unittest.TestCase):
    """C++ 版 (firmware) と同じ結果になるか。"""

    def test_same_as_firmware(self):
        frames = [bytes.fromhex(h) for h in TX_FRAMES]
        out = run_frames(frames)
        self.assertEqual(len(out), 1)
        s = out[0]
        self.assertEqual(s.sid, RX_SID)
        self.assertEqual(s.missing, RX_MISSING)
        self.assertEqual(len(s.points), len(RX_POINTS))
        for (x, y), (ex, ey) in zip(s.points, RX_POINTS):
            self.assertAlmostEqual(x, ex, places=4)
            self.assertAlmostEqual(y, ey, places=4)

    def test_encode_stroke_precision(self):
        # 送信機と同じ手順で作ったパケットを組み立て直すと、量子化誤差 (0.1°) 以内で戻る。
        # ストロークの大きさや長さ (4 秒 = 100 点) によらず同じ精度
        for n, r in [(50, 30), (100, 150), (MAX_POINTS, 5)]:
            pts = circle(n, r)
            out = run_frames(encode_stroke(1, pts))
            self.assertEqual(len(out[0].points), n)
            for (x, y), (ex, ey) in zip(out[0].points, pts):
                self.assertLessEqual(abs(x - ex), UNIT_DEG / 2 + 1e-9)
                self.assertLessEqual(abs(y - ey), UNIT_DEG / 2 + 1e-9)

    def test_fast_swing_catches_up(self):
        # 差分の上限 (±127 = 25.4°/点) を超える動きでも、次の点で追いつく
        pts = [(0, 0), (30, 0), (30, 0)]
        q = quantize(pts)
        self.assertEqual(q[1][0], 127)
        self.assertEqual(q[2][0], 150)


if __name__ == "__main__":
    unittest.main()
