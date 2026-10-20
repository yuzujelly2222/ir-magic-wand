# テストで共通に使うもの
import math
import threading
import time

from magic_wand.assembler import StrokeAssembler
from magic_wand.protocol import decode

# 受信機 (firmware/ir_rx) が USB シリアルに出す行の例
RX_OUTPUT = """#ir_rx ready
#stroke_begin,id=3,n=4,missing=1
pt,0.0,0.0
pt,10.0,0.0
pt,10.0,20.0
pt,90.0,0.0
#stroke_end
#stats,strokes=1,dropped=0,crc_err=2,interp=1
#drop,id=4,reason=too_many_lost
""".splitlines()


def circle(n, r):
    return [(r * math.sin(2 * math.pi * i / (n - 1)), r * (1 - math.cos(2 * math.pi * i / (n - 1))))
            for i in range(n)]


def run_frames(frames, drop=(), dt=0.098, start=0.0):
    """フレーム列を受信したことにして、確定したものを返す。drop に入れた番号のフレームは落とす。"""
    asm = StrokeAssembler()
    out, t = [], start
    for k, f in enumerate(frames):
        t += dt
        if k in drop:
            continue
        pk = decode(f)
        assert pk is not None
        out += asm.push(pk, t)
    out += asm.poll(t + 1.0)
    return out


def stroke_lines(sid, angles, missing=0):
    lines = [f"#stroke_begin,id={sid},n={len(angles)},missing={missing}"]
    lines += [f"pt,{y:.1f},{p:.1f}" for y, p in angles]
    lines += ["#stroke_end"]
    return ("\r\n".join(lines) + "\r\n").encode()


class FakeSerial:
    def __init__(self):
        self.rx = bytearray()
        self.closed = False
        self.lock = threading.Lock()

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, n):
        with self.lock:
            out = bytes(self.rx[:n])
            del self.rx[:n]
        if not out:
            time.sleep(0.001)
        return out

    def feed(self, data):
        with self.lock:
            self.rx += data

    def close(self):
        self.closed = True
