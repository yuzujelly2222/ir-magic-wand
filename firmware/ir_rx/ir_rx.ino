// ir_rx.ino — IR IMU Link 受信機 (ストローク一括受信版)
//
// ボード : Arduino Uno / Nano  → IR は SoftwareSerial (D8)
//          Leonardo / Micro / Nano Every など Serial1 を持つボード → Serial1 (RX ピン)
// 受信   : OSRB38C9AA (38kHz リモコン受光モジュール) の OUT を上記ピンへ
//
// 送信機はストロークが終わってからまとめて送ってくる (protocol.h 参照)。
// 受信機はそれを 1 ストロークに組み立て、欠けた点を補間して PC へ流す:
//
//   #stroke_begin,id=<sid>,n=<点数>,missing=<補間した点数>
//   pt,<x_deg>,<y_deg>                 … 開始点からの相対角。x = yaw, y = pitch (上が +)
//   ...
//   #stroke_end
//   #drop,id=<sid>,reason=<理由>        … 届いた点が少なすぎて捨てたとき
//   #stats,strokes=..,dropped=..,crc_err=..,interp=..
//
// 受光モジュールの出力は「キャリアあり = LOW」なので、UART の極性
// (アイドル HIGH / スタートビット LOW) とそのまま一致する。反転は不要。

#include "protocol.h"
#include "stroke_assembler.h"

#if defined(HAVE_HWSERIAL1)
  #define IR_SERIAL Serial1
#else
  #include <SoftwareSerial.h>
  constexpr uint8_t kPinIrRx = 8;
  SoftwareSerial gIrSerial(kPinIrRx, -1);  // RX のみ
  #define IR_SERIAL gIrSerial
#endif

constexpr uint8_t kPinStatusLed = LED_BUILTIN;

// ---------------------------------------------------------------- フレーマ
// バイト列からパケットを切り出す。CRC 不一致のときは次の 0xAA まで
// ずらして再同期する（途中から聞き始めた場合もここで復帰する）。
class Framer {
 public:
  // 1パケット完成したら true
  bool push(uint8_t b, irproto::Packet& out) {
    if (len_ == 0 && b != irproto::kHeader) return false;
    buf_[len_++] = b;
    if (len_ < irproto::kPacketSize) return false;

    if (irproto::decode(buf_, out)) {
      len_ = 0;
      return true;
    }
    ++crcErrors;
    resync();
    return false;
  }

  uint32_t crcErrors = 0;

 private:
  void resync() {
    uint8_t start = 1;
    while (start < len_ && buf_[start] != irproto::kHeader) ++start;
    const uint8_t remain = len_ - start;
    for (uint8_t i = 0; i < remain; ++i) buf_[i] = buf_[start + i];
    len_ = remain;
  }

  irproto::Frame buf_{};
  uint8_t len_ = 0;
};

// ---------------------------------------------------------------- 出力
Framer          gFramer;
StrokeAssembler gAsm;

struct Stats {
  uint32_t strokes = 0;
  uint32_t dropped = 0;
  uint32_t interp  = 0;  // 補間した点の合計
} gStats;

void printStats() {
  Serial.print(F("#stats,strokes="));
  Serial.print(gStats.strokes);
  Serial.print(F(",dropped="));
  Serial.print(gStats.dropped);
  Serial.print(F(",crc_err="));
  Serial.print(gFramer.crcErrors);
  Serial.print(F(",interp="));
  Serial.println(gStats.interp);
}

void printStroke() {
  Serial.print(F("#stroke_begin,id="));
  Serial.print(gAsm.sid());
  Serial.print(F(",n="));
  Serial.print(gAsm.size());
  Serial.print(F(",missing="));
  Serial.println(gAsm.missing());
  for (uint8_t i = 0; i < gAsm.size(); ++i) {
    Serial.print(F("pt,"));
    Serial.print(gAsm.xDeg(i), 1);
    Serial.print(',');
    Serial.println(gAsm.yDeg(i), 1);
  }
  Serial.println(F("#stroke_end"));
}

// Ready / Dropped を出力し、保留中のパケットがあれば続けて処理する
void handle(StrokeAssembler::Result r) {
  while (r != StrokeAssembler::Result::None) {
    if (r == StrokeAssembler::Result::Ready) {
      ++gStats.strokes;
      gStats.interp += gAsm.missing();
      printStroke();
    } else {
      ++gStats.dropped;
      Serial.print(F("#drop,id="));
      Serial.print(gAsm.sid());
      Serial.print(F(",reason="));
      Serial.println(gAsm.dropReason());
    }
    printStats();
    digitalWrite(kPinStatusLed, LOW);
    r = gAsm.consume();
  }
}

void setup() {
  pinMode(kPinStatusLed, OUTPUT);
  Serial.begin(115200);
  IR_SERIAL.begin(irproto::kBaud);
  Serial.println(F("#ir_rx ready"));
}

void loop() {
  while (IR_SERIAL.available()) {
    irproto::Packet pk;
    if (gFramer.push(static_cast<uint8_t>(IR_SERIAL.read()), pk)) {
      digitalWrite(kPinStatusLed, HIGH);  // 受信中は点灯
      handle(gAsm.push(pk, millis()));
    }
  }
  handle(gAsm.poll(millis()));
}
