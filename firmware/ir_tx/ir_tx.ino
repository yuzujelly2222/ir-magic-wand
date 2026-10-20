// ir_tx.ino — IR IMU Link 送信機 (ATtiny85 版 / ストローク一括送信)
//
// ボード : ATtiny85, 8MHz 内蔵 (または 16MHz PLL)  — ATTinyCore
//          「Burn Bootloader」でクロックのヒューズを書いてから使うこと (出荷時は 1MHz)
// IMU    : GY-521 / MPU-6050 (I2C: PB0 = SDA, PB2 = SCL。GY-521 のプルアップを使う)
// IR LED : PB1 (OC1A) → トランジスタ → 940nm IR LED
// LED    : PB3 (状態表示, 任意)
//
// しくみ
//   - 3 軸のジャイロ (gx, gy, gz) を 200Hz で読み、整数のクォータニオンで向きを積分する
//     送るのは「ストローク開始時の向きから見た、杖の先が指している向き (yaw, pitch)」。
//     手首のひねり (gx) や大きな振りでも正しく出る。開始点からの相対角なので
//     加速度による絶対姿勢の補正は不要。加速度は読まない
//   - 動きの量 m = |gy| + |gz| でストロークの開始・終了を自動判定
//       開始: m > kStartDps が kStartTicks 回連続
//       終了: m < kEndDps が kEndQuietMs 続く / 4 秒 (kMaxPoints 点) に達した
//   - ストローク中は 25Hz で点をスタック (直前の点もプリトリガとして含める)
//   - 終わったら protocol.h の形式でまとめて IR 送信 (ブロッキング)
//   - Timer1 で 38kHz キャリアを PB1 に出し、ビット幅は micros() で測る
//
// Flash 節約のため
//   - 浮動小数点を一切使わない (float ライブラリだけで 1.5KB 以上ある)
//   - Wire ライブラリの代わりに数十行のソフトウェア I2C
//   - digitalWrite / pinMode を使わずレジスタを直接操作

#include <avr/pgmspace.h>
#include <util/delay.h>
#include "protocol.h"

#if !defined(__AVR_ATtiny85__) && !defined(__AVR_ATtiny45__) && !defined(__AVR_ATtiny25__)
#error "ボードが ATtiny85 になっていない。ATTinyCore を入れて「ATtiny25/45/85 (No bootloader)」を選ぶこと"
#endif

#if F_CPU < 8000000UL
#error "8MHz 以上で動かすこと (Tools > Clock で選んで Burn Bootloader)"
#endif

// ---------------------------------------------------------------- 設定
namespace cfg {
// ジャイロは ±500dps で 65.5 LSB/(deg/s)。しきい値は「dps × 10」で書いて LSB に直す
constexpr uint16_t dps10ToLsb(uint16_t dps10) { return static_cast<uint16_t>(dps10 * 655UL / 100); }

constexpr uint8_t  kMpuAddr       = 0x68;

// GY-521 の取り付け向き (部品の面を上にして、杖とまっすぐにそろえて付ける前提)。既定は Y が持ち手側
//   kMountXTip    : 基板の X の矢印が杖の先 (IR LED 側) を向いている
//   kMountYTip    : 基板の Y の矢印が杖の先を向いている (X は横向き)
//   kMountYHandle : 基板の Y の矢印が持ち手 (電池) 側を向いている (X は横向き)
// 違っていると上下の動きがほとんど出ない。Y の向き (先 / 持ち手) を逆にすると、
// 左右はそのままで上下だけが反転した絵 (鏡像) になる。ジェスチャーの判定には影響しない
enum Mount : uint8_t { kMountXTip, kMountYTip, kMountYHandle };
constexpr Mount    kMount         = kMountYHandle;
constexpr uint16_t kImuPeriodUs   = 5000;     // 200Hz (積分の dt はこの値で固定)
constexpr uint8_t  kDecimation    = 200 / irproto::kSampleHz;  // 8 → 25Hz で点を記録

constexpr uint16_t kStartLsb      = dps10ToLsb(300);  // 開始しきい値 30 dps
constexpr uint8_t  kStartTicks    = 6;                // 開始の確定に必要な連続回数 (30ms)
constexpr uint16_t kEndLsb        = dps10ToLsb(100);  // 終了しきい値 10 dps
constexpr uint8_t  kEndQuietTicks = 40;               // 200ms 静止したら終了
constexpr uint8_t  kMinPoints     = 4;                // これ未満 (160ms 未満) のストロークは捨てる
constexpr uint8_t  kPrePoints     = 2;                // プリトリガで含める直前の点数

constexpr uint16_t kBiasTrackLsb  = dps10ToLsb(20);   // 2 dps 以下の静止中はゼロ点を追従
constexpr uint8_t  kBiasShift     = 6;                // 追従の速さ (1/64)

constexpr uint8_t  kGapBits       = 18;       // パケット間の休止 (≈15ms, AGC 対策)
constexpr uint8_t  kRepeat        = 1;        // 1 ストロークを何回送るか (2 にすると取りこぼしに強いが倍の時間)

static_assert(kImuPeriodUs == 5000, "att::integrate の係数は 200Hz / ±500dps 前提");
static_assert(irproto::kUnitCdeg == 20, "Stroke::toUnit は 0.2° 単位前提");
}  // namespace cfg

// ---------------------------------------------------------------- ピン
namespace pins {
inline void ledOn()     { PORTB |=  _BV(PB3); }
inline void ledOff()    { PORTB &= ~_BV(PB3); }
inline void ledToggle() { PINB   =  _BV(PB3); }  // PINx への書き込みでトグル
}  // namespace pins

// ---------------------------------------------------------------- IR 送信
namespace irtx {

// Timer1: CTC (OCR1C で一周), 分周 1, OC1A トグル → F_CPU / (2 * (OCR1C + 1)) ≈ 38kHz
constexpr uint8_t kOcr = static_cast<uint8_t>((F_CPU + 38000UL) / (2UL * 38000UL) - 1);

inline void carrierOn()  { TCCR1 |=  _BV(COM1A0); }
inline void carrierOff() { TCCR1 &= ~_BV(COM1A0); PORTB &= ~_BV(PB1); }

void begin() {
  DDRB |= _BV(PB1);
  GTCCR = 0;
  TCCR1 = _BV(CTC1) | _BV(CS10);
  OCR1C = kOcr;
  OCR1A = kOcr;
  carrierOff();
}

// 1 フレームを送る。UART の '0' / スタートビット = キャリア ON
// (受光モジュールの出力はキャリアありで LOW なので、受信側で反転は不要)
// 1 ビット = 1e6 / 1200 = 833.33µs。833µs ずつ進め、3 ビットごとに 1µs 足して誤差をなくす
void sendFrame(const irproto::Frame& f) {
  const uint32_t t0 = micros();
  uint32_t target = 0;
  uint8_t  frac = 0;
  auto waitBit = [&]() {
    target += 833;
    if (++frac == 3) { frac = 0; ++target; }
    while (micros() - t0 < target) {}
  };

  for (uint8_t i = 0; i < irproto::kPacketSize; ++i) {
    uint8_t b = f[i];
    carrierOn(); waitBit();                       // スタートビット
    for (uint8_t k = 0; k < 8; ++k, b >>= 1) {
      if (b & 1) carrierOff(); else carrierOn();
      waitBit();
    }
    carrierOff(); waitBit();                      // ストップビット
  }
  for (uint8_t k = 0; k < cfg::kGapBits; ++k) waitBit();  // 休止
}

void sendPacket(const irproto::Packet& pk) {
  irproto::Frame f;
  irproto::encode(pk, f);
  sendFrame(f);
}

static_assert(irproto::kBaud == 1200, "sendFrame のビット幅 (833.33µs) は 1200bps 前提");

}  // namespace irtx

// ---------------------------------------------------------------- ソフトウェア I2C
// オープンドレイン: '0' = 出力 LOW / '1' = 入力 (GY-521 のプルアップで HIGH)。約 100kHz
namespace i2c {

inline void sdaLow()  { DDRB |=  _BV(PB0); }
inline void sdaHigh() { DDRB &= ~_BV(PB0); }
inline void sclLow()  { DDRB |=  _BV(PB2); }
inline void sclHigh() { DDRB &= ~_BV(PB2); }
inline bool sda()     { return PINB & _BV(PB0); }
inline void wait()    { _delay_us(4); }

void begin() { PORTB &= ~(_BV(PB0) | _BV(PB2)); sdaHigh(); sclHigh(); }

void start() { sdaHigh(); sclHigh(); wait(); sdaLow(); wait(); sclLow(); }
void stop()  { sdaLow(); wait(); sclHigh(); wait(); sdaHigh(); wait(); }

bool write(uint8_t b) {  // ACK が返れば true
  for (uint8_t i = 0; i < 8; ++i, b <<= 1) {
    if (b & 0x80) sdaHigh(); else sdaLow();
    wait(); sclHigh(); wait(); sclLow();
  }
  sdaHigh(); wait(); sclHigh(); wait();
  const bool ack = !sda();
  sclLow();
  return ack;
}

uint8_t read(bool ack) {
  uint8_t b = 0;
  sdaHigh();
  for (uint8_t i = 0; i < 8; ++i) {
    wait(); sclHigh(); wait();
    b = static_cast<uint8_t>((b << 1) | (sda() ? 1 : 0));
    sclLow();
  }
  if (ack) sdaLow();
  wait(); sclHigh(); wait(); sclLow();
  sdaHigh();
  return b;
}

}  // namespace i2c

// ---------------------------------------------------------------- IMU
class Mpu6050 {
 public:
  bool begin() {
    i2c::begin();
    if (!writeReg(0x6B, 0x00)) return false;  // PWR_MGMT_1: スリープ解除
    writeReg(0x1A, 0x02);                     // CONFIG: DLPF 98Hz (200Hz で読むので帯域を広げる)
    writeReg(0x1B, 0x08);                     // GYRO_CONFIG: ±500dps
    _delay_ms(100);
    return true;
  }

  // GYRO_XOUT〜GYRO_ZOUT (0x43〜0x48) の 6 バイトを読む
  bool read() {
    i2c::start();
    if (!i2c::write(cfg::kMpuAddr << 1)) { i2c::stop(); return false; }
    i2c::write(0x43);
    i2c::start();                              // リピーテッドスタート
    i2c::write((cfg::kMpuAddr << 1) | 1);
    for (uint8_t i = 0; i < 3; ++i) {
      const uint8_t h = i2c::read(true);
      const uint8_t l = i2c::read(i < 2);
      raw_[i] = static_cast<int16_t>((static_cast<uint16_t>(h) << 8) | l);
    }
    i2c::stop();
    return true;
  }

  // 静止状態でゼロ点を測る (256 サンプル ≈ 1.3 秒)
  void calibrate() {
    for (auto& b : bias_) b = 0;
    for (uint16_t n = 0; n < 256; ++n) {
      read();
      for (uint8_t i = 0; i < 3; ++i) bias_[i] += raw_[i];  // 平均 × 256 = 合計
      _delay_ms(5);
    }
  }

  // 静止中にゼロ点をゆっくり追従させる (温度ドリフト対策)
  void trackBias() {
    for (uint8_t i = 0; i < 3; ++i) {
      bias_[i] += ((static_cast<int32_t>(raw_[i]) << 8) - bias_[i]) >> cfg::kBiasShift;
    }
  }

  // ゼロ点を引いた値 [LSB]。0 = x (ひねり), 1 = y, 2 = z
  int16_t g(uint8_t i) const {
    return static_cast<int16_t>(raw_[i] - static_cast<int16_t>(bias_[i] >> 8));
  }

 private:
  bool writeReg(uint8_t reg, uint8_t val) {
    i2c::start();
    const bool ok = i2c::write(cfg::kMpuAddr << 1) && i2c::write(reg) && i2c::write(val);
    i2c::stop();
    return ok;
  }

  int16_t raw_[3] = {0, 0, 0};
  int32_t bias_[3] = {0, 0, 0};  // ゼロ点 × 256
};

// ---------------------------------------------------------------- 姿勢 (クォータニオン)
// 3 軸のジャイロを 200Hz で積分して、杖の向きをクォータニオン q = (w, x, y, z) で持つ。
// 値は Q28 の固定小数点 (1.0 = 2^28) の int32。浮動小数点は使わない。
//
// 送る角度は「ストローク開始時の向きから見た、杖の先 (x 軸) が指している向き」:
//   d = (開始時の向き)^-1 · (今の向き) · x̂
//   yaw   = atan2(-dy, dx)              … 右を指すと + (y は杖の左なので符号を反転)
//   pitch = atan2(dz, √(dx² + dy²))      … 上を指すと +
// 受信側 (PointerProjector) の「x = 右が +、z = 上が +」と同じ向き。
// 手首のひねり (gx) で軸が回っても、大きく振っても、指している向きは正しく出る。
//
// ジャイロの軸は loop() で杖の座標 (x = 杖の先, y = 左, z = 上) にそろえてから渡す
// (取り付け向きは cfg::kMount で選ぶ)。
namespace att {

constexpr int32_t kOne = 1L << 28;

// v[0..3] = (w, x, y, z)。Flash を節約するため、成分はループで回す
struct Quat {
  int32_t v[4] = {kOne, 0, 0, 0};
};

// ハミルトン積 r = a ⊗ b の各成分 (掛ける前の a, b を渡す)。
// r_i = Σ_j ±a_j b_(i xor j)。符号は kNeg[i] の bit j が 1 なら −
__attribute__((noinline, noclone))
void qmul(const int32_t* a, const int32_t* b, int32_t* r) {
  static const uint8_t kNeg[4] = {0x0E, 0x08, 0x02, 0x04};
  for (uint8_t i = 0; i < 4; ++i) {
    int32_t s = 0;
    for (uint8_t j = 0; j < 4; ++j) {
      const int32_t t = a[j] * b[i ^ j];
      s += (kNeg[i] >> j) & 1 ? -t : t;
    }
    r[i] = s;
  }
}

// Q28 → Q15
__attribute__((noinline, noclone))
void toQ15(const Quat& q, int32_t* o) {
  for (uint8_t i = 0; i < 4; ++i) o[i] = q.v[i] >> 13;
}

// q ← q + ½ q ⊗ (0, ω) dt。ω はゼロ点を引いたジャイロの値 [LSB]
// 1 LSB × ½ × 5ms = 6.66e-7 rad。Q15 × LSB の積を Q28 に直す係数は 5.4572e-3 ≈ 715.28 / 2^17
// 各成分は |q| ≤ 1 なので ±1.9e9 に収まる (3 軸すべて ±500dps で振り切れても int32 を超えない)
__attribute__((noinline, noclone))
void integrate(Quat& q, const int16_t* g) {
  int32_t a[4], b[4] = {0, g[0], g[1], g[2]}, d[4];
  toQ15(q, a);
  qmul(a, b, d);
  int32_t n2 = 0;
  for (uint8_t i = 0; i < 4; ++i) {
    q.v[i] += ((d[i] >> 10) * 715) >> 7;
    const int32_t c = q.v[i] >> 14;
    n2 += c * c;
  }
  // 長さを 1 に戻す (1 次近似: q ← q · (3 − |q|²) / 2)。err = (1 − |q|²) / 2 を Q19 で
  const int32_t err = (kOne - n2) >> 9;
  for (uint8_t i = 0; i < 4; ++i) q.v[i] += ((q.v[i] >> 14) * err) >> 5;
}

// ---- CORDIC (atan2 と長さ)
// 角度の単位は 1/1280 度 (= 0.2° / 256)。atan(2^-i) の表
const uint16_t kAtan[16] PROGMEM = {57600, 34003, 17966, 9120, 4578, 2291, 1146, 573,
                                    286,   143,   72,    36,   18,   9,    4,    2};
constexpr int32_t k90 = 90L * 1280;
constexpr int32_t k180 = 180L * 1280;

// (X, Y) を x 軸に回して atan2(Y, X) を返す。X には長さ × 1.6468 (CORDIC の利得) が残る
__attribute__((noinline, noclone))
int32_t cordic(int32_t& X, int32_t Y) {
  int32_t ang = 0;
  if (X < 0) {  // 左半分は先に 180° 回しておく
    X = -X; Y = -Y; ang = 2 * k90;
  }
  for (uint8_t i = 0; i < 16; ++i) {
    int32_t dX = Y >> i, dY = X >> i;
    int32_t a = pgm_read_word(&kAtan[i]);
    if (Y < 0) { dX = -dX; dY = -dY; a = -a; }
    X += dX; Y -= dY; ang += a;
  }
  return ang > k180 ? ang - 2 * k180 : ang;
}

// ストローク開始時の向き q0 から見た、今の向き q の (yaw, pitch) [1/1280 度]
__attribute__((noinline, noclone))
void direction(const Quat& q0, const Quat& q, int32_t& yaw, int32_t& pitch) {
  int32_t a[4], b[4], r[4];
  toQ15(q0, a);
  for (uint8_t i = 1; i < 4; ++i) a[i] = -a[i];  // conj(q0)
  toQ15(q, b);
  qmul(a, b, r);                                 // r = conj(q0) ⊗ q (Q30)
  // 指している向き d = r ⊗ (0, x̂) ⊗ conj(r)。積を 2 回とる (Q15 × Q15 → Q30)
  for (uint8_t i = 0; i < 4; ++i) { r[i] >>= 15; a[i] = i ? -r[i] : r[i]; }
  const int32_t ex[4] = {0, 1L << 15, 0, 0};
  qmul(r, ex, b);
  for (uint8_t i = 0; i < 4; ++i) b[i] >>= 15;
  qmul(b, a, r);                                 // r[1..3] = d (Q30)
  int32_t dx = r[1] >> 2;                        // Q28 (CORDIC の利得 1.65 × 2 回でも溢れない)
  yaw = cordic(dx, -(r[2] >> 2));                // 右が +。dx には √(dx² + dy²) × 1.6468 が残る
  pitch = cordic(dx, (r[3] >> 16) * 26981);      // 上が +。dz にも同じ利得 (26981 / 2^14) を掛けてそろえる
}

}  // namespace att

// ---------------------------------------------------------------- ストローク
// 点は「開始点からの相対角」を 0.2° 単位で量子化し、1 つ前の点との差分 (int8) でためる。
// 100 点 × 2 軸 × 1 バイト = 200 バイト (ATtiny85 の RAM は 512 バイト)。
// 差分は「量子化した値どうしの差」なので、足し戻すと誤差が積み上がらずに元の値に戻る。
class Stroke {
 public:
  void clear() { n_ = 0; }

  void begin(const att::Quat& origin) { origin_ = origin; n_ = 0; qx_ = qy_ = 0; prevYaw_ = 0; }

  void add(const att::Quat& q) {
    if (n_ >= irproto::kMaxPoints) return;
    int32_t yaw, pitch;
    att::direction(origin_, q, yaw, pitch);
    // yaw は atan2 なので ±180° で折り返す。前の点から 180° 以上飛んだら 1 周ずらしてつなぐ
    const int32_t jump = yaw - prevYaw_;
    if (jump > att::k180) yaw -= 2 * att::k180;
    else if (jump < -att::k180) yaw += 2 * att::k180;
    prevYaw_ = yaw;
    dx_[n_] = step(qx_, toUnit(yaw));
    dy_[n_] = step(qy_, toUnit(pitch));
    ++n_;
  }

  uint8_t size() const { return n_; }
  bool full() const { return n_ >= irproto::kMaxPoints; }
  void truncate(uint8_t n) { if (n < n_) n_ = n; }

  // 送信。DATA パケットごとに 1 点目の絶対座標 (アンカー) と、残り 3 点の差分を入れる
  void send(uint8_t sid) const {
    for (uint8_t r = 0; r < cfg::kRepeat; ++r) {
      const uint8_t left = cfg::kRepeat - 1 - r;
      irtx::sendPacket(irproto::makeInfo(sid, n_, irproto::kInfoBegin, left));
      int16_t x = 0, y = 0;  // 差分を足し戻した絶対座標
      for (uint8_t i = 0; i < n_; i += irproto::kPointsPerPkt) {
        irproto::Packet pk{};
        pk.sid = sid;
        pk.idx = i;
        x += dx_[i];
        y += dy_[i];
        irproto::packAnchor(x, y, pk.b);
        for (uint8_t k = 1; k < irproto::kPointsPerPkt; ++k) {
          const uint8_t j = i + k;
          const bool has = j < n_;
          if (has) { x += dx_[j]; y += dy_[j]; }
          pk.b[1 + k * 2] = static_cast<uint8_t>(has ? dx_[j] : irproto::kNoPoint);
          pk.b[2 + k * 2] = static_cast<uint8_t>(has ? dy_[j] : irproto::kNoPoint);
        }
        irtx::sendPacket(pk);
        pins::ledToggle();
      }
      irtx::sendPacket(irproto::makeInfo(sid, n_, irproto::kInfoEnd, left));
    }
  }

 private:
  // 1/1280 度 → 0.2° 単位 (四捨五入、12bit に収める)
  static int16_t toUnit(int32_t ang) {
    int32_t v = ang >= 0 ? (ang + 128) >> 8 : -((-ang + 128) >> 8);
    if (v > irproto::kCoordMax) v = irproto::kCoordMax;
    if (v < irproto::kCoordMin) v = irproto::kCoordMin;
    return static_cast<int16_t>(v);
  }

  // q まで進む差分を返し、prev を進める。1 回で届かない分は次の点に回す
  // (-128 は「点なし」用に空けておく。±127 = ±635 deg/s でジャイロの上限より広いので、ふつうは起きない)
  static int8_t step(int16_t& prev, int16_t q) {
    int16_t d = q - prev;
    if (d > 127) d = 127;
    if (d < -127) d = -127;
    prev += d;
    return static_cast<int8_t>(d);
  }

  int8_t    dx_[irproto::kMaxPoints];
  int8_t    dy_[irproto::kMaxPoints];
  uint8_t   n_ = 0;
  int16_t   qx_ = 0, qy_ = 0;  // 最後にためた点 (0.2° 単位)
  int32_t   prevYaw_ = 0;
  att::Quat origin_;
};

// 静止中の直近の向き (プリトリガ用リングバッファ)
class PreRing {
 public:
  void clear() { n_ = 0; head_ = 0; }
  void push(const att::Quat& q) {
    buf_[head_] = q;
    if (++head_ == cfg::kPrePoints) head_ = 0;
    if (n_ < cfg::kPrePoints) ++n_;
  }
  uint8_t size() const { return n_; }
  // i = 0 が一番古い点
  const att::Quat& at(uint8_t i) const {
    uint8_t k = head_ + cfg::kPrePoints - n_ + i;
    if (k >= cfg::kPrePoints) k -= cfg::kPrePoints;
    return buf_[k];
  }

 private:
  att::Quat buf_[cfg::kPrePoints];
  uint8_t   n_ = 0, head_ = 0;
};

// ---------------------------------------------------------------- main
enum class State : uint8_t { Idle, Stroke, Cooldown };

Mpu6050   gImu;
att::Quat gQ;
Stroke    gStroke;
PreRing   gPre;
State     gState = State::Idle;
uint8_t   gSid = 0;

void setup() {
  DDRB |= _BV(PB3);
  irtx::begin();

  if (!gImu.begin()) {
    for (;;) { pins::ledToggle(); _delay_ms(100); }  // MPU-6050 が見つからない
  }

  pins::ledOn();   // 補正中は点灯。動かさないこと
  gImu.calibrate();
  pins::ledOff();
}

void loop() {
  static uint32_t lastImuUs   = micros();
  static uint8_t  decim       = 0;
  static uint8_t  startRun    = 0;   // m > kStartLsb の連続回数
  static uint8_t  quietRun    = 0;   // m < kEndLsb の連続回数
  static uint8_t  activeCount = 0;   // 最後に動いていたときの点数

  if (micros() - lastImuUs < cfg::kImuPeriodUs) return;
  lastImuUs += cfg::kImuPeriodUs;    // 周期を固定 (dt = 5ms として積分する)
  if (!gImu.read()) return;

  // 杖の座標 (x = 杖の先, y = 左, z = 上) にそろえる
  const int16_t sx = gImu.g(0), sy = gImu.g(1), sz = gImu.g(2);
  int16_t g[3];  // x (ひねり), y, z
  if (cfg::kMount == cfg::kMountYTip) {
    g[0] = sy; g[1] = static_cast<int16_t>(-sx); g[2] = sz;
  } else if (cfg::kMount == cfg::kMountYHandle) {
    g[0] = static_cast<int16_t>(-sy); g[1] = sx; g[2] = sz;
  } else {
    g[0] = sx; g[1] = sy; g[2] = sz;
  }
  const uint16_t m = static_cast<uint16_t>(g[1] < 0 ? -g[1] : g[1]) +
                     static_cast<uint16_t>(g[2] < 0 ? -g[2] : g[2]);
  att::integrate(gQ, g);

  const bool sampleTick = (++decim >= cfg::kDecimation);
  if (sampleTick) decim = 0;

  switch (gState) {
    case State::Idle: {
      if (m < cfg::kBiasTrackLsb) gImu.trackBias();
      if (sampleTick) gPre.push(gQ);

      startRun = (m > cfg::kStartLsb) ? startRun + 1 : 0;
      if (startRun >= cfg::kStartTicks) {
        // 開始。プリトリガの一番古い向きを原点にする
        gStroke.begin(gPre.size() > 0 ? gPre.at(0) : gQ);
        for (uint8_t i = 0; i < gPre.size(); ++i) gStroke.add(gPre.at(i));
        gStroke.add(gQ);
        decim = 0;
        quietRun = 0;
        activeCount = gStroke.size();
        gState = State::Stroke;
        pins::ledOn();
      }
      break;
    }

    case State::Stroke: {
      if (sampleTick) gStroke.add(gQ);

      if (m >= cfg::kEndLsb) { quietRun = 0; activeCount = gStroke.size(); }
      else                   { ++quietRun; }

      if (quietRun >= cfg::kEndQuietTicks || gStroke.full()) {
        // 終わりの静止区間は捨てる (最後に動いていた点 + 1 点まで残す)
        gStroke.truncate(activeCount + 1);
        if (gStroke.size() >= cfg::kMinPoints) gStroke.send(gSid++);
        gStroke.clear();
        // 送信中 (ブロッキング) は IMU を読んでいないので、周期を取り直す
        lastImuUs = micros();
        quietRun = 0;
        gState = State::Cooldown;
        pins::ledOff();
      }
      break;
    }

    case State::Cooldown: {
      // 送信中も手が動いていた場合に備え、いったん静止を待ってから次を受け付ける
      quietRun = (m < cfg::kEndLsb) ? quietRun + 1 : 0;
      if (quietRun >= cfg::kEndQuietTicks) {
        gQ = att::Quat{};
        gPre.clear();
        startRun = 0;
        gState = State::Idle;
      }
      break;
    }
  }
}
