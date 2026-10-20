// protocol.h — IR IMU Link のパケット定義 (v2: ストローク一括送信 / 0.2° 固定 / 最大 4 秒)
// ir_tx / ir_rx の両方に同じファイルを置いている。変更したら両方そろえること。
//
// 送信機はストローク (最大 4 秒) を手元にため込み、終わってからまとめて送る。
// 1 ストロークの送信は次の順:
//
//   INFO(begin) → DATA × ceil(n/4) → INFO(end)     (これを kRepeat 回)
//
// パケット (13 bytes, 1200bps 8N1, LSB first):
//   [0xAA][sid][idx][b0][b1][b2][b3][b4][b5][b6][b7][b8][CRC8]
//
//   sid : ストローク ID (送るたびに +1)。受信側はこれでストロークを区別し、再送の重複を捨てる
//   idx : 0..kMaxPoints-1 → DATA。点 idx〜idx+3 の 4 点
//           b0..b2 = 点 idx の絶対座標 (アンカー)。x, y を 12bit の符号付きで
//                    b0 = x の上位 8bit, b1 = y の上位 8bit, b2 = (x の下位 4bit << 4) | y の下位 4bit
//           b3..b8 = 点 idx+1〜idx+3 の、1 つ前の点からの差分 (dx, dy) を int8 で
//                    kNoPoint (-128) は「点なし」(最後の DATA パケットの詰め物)
//         0xFF            → INFO。b0 = 点数 n, b1 = 種類 (0 = begin, 1 = end),
//                                 b2 = このあと残っている再送の回数, b3..b8 = 0
//
//   座標 (x = yaw, y = pitch) は「ストローク開始点からの相対角」で、単位は 0.2° (kUnitCdeg)
//     12bit なので ±409.4°、差分の int8 は ±25.4° / 40ms (= ±635 deg/s。ジャイロの上限 500 deg/s より広い)
//   パケットごとにアンカー (絶対座標) が入っているので、パケットを落としても
//   そのパケットの 4 点が欠けるだけで、後ろの点はずれない。
//
//   - CRC8 (多項式 0x07, 初期値 0x00) はバイト 0〜11 から計算
//   - ヘッダ以外の 12 バイトは 0x55 で XOR して送る
//     (値が 0 付近のときにキャリアが長く連続して AGC が反応するのを防ぐ)
#pragma once
#include <stdint.h>

namespace irproto {

constexpr uint32_t kBaud          = 1200;  // IR 上のビットレート
constexpr uint8_t  kHeader        = 0xAA;
constexpr uint8_t  kWhitenMask    = 0x55;
constexpr uint8_t  kPacketSize    = 13;
constexpr uint8_t  kPayloadSize   = 9;
constexpr uint8_t  kPointsPerPkt  = 4;     // アンカー 1 点 + 差分 3 点
constexpr uint8_t  kIdxInfo       = 0xFF;
constexpr int8_t   kNoPoint       = -128;

constexpr uint8_t  kSampleHz      = 25;    // 点のサンプリング周波数
constexpr uint8_t  kMaxPoints     = 100;   // 4 秒 × 25Hz
constexpr uint8_t  kUnitCdeg      = 20;    // 座標の単位 = 0.2° (= 20 × 0.01°)
constexpr int16_t  kCoordMax      = 2047;  // 12bit 符号付き
constexpr int16_t  kCoordMin      = -2048;

enum : uint8_t { kInfoBegin = 0, kInfoEnd = 1 };

struct Packet {
  uint8_t sid;
  uint8_t idx;
  uint8_t b[kPayloadSize];

  bool isInfo() const { return idx == kIdxInfo; }
};

using Frame = uint8_t[kPacketSize];

inline uint8_t crc8(const uint8_t* data, uint8_t len) {
  uint8_t crc = 0x00;
  while (len--) {
    crc ^= *data++;
    for (uint8_t i = 0; i < 8; ++i) {
      crc = (crc & 0x80) ? static_cast<uint8_t>((crc << 1) ^ 0x07)
                         : static_cast<uint8_t>(crc << 1);
    }
  }
  return crc;
}

inline void encode(const Packet& pk, Frame& out) {
  out[0] = kHeader;
  out[1] = pk.sid;
  out[2] = pk.idx;
  for (uint8_t i = 0; i < kPayloadSize; ++i) out[3 + i] = pk.b[i];
  out[kPacketSize - 1] = crc8(out, kPacketSize - 1);
  for (uint8_t i = 1; i < kPacketSize; ++i) {
    out[i] = static_cast<uint8_t>(out[i] ^ kWhitenMask);
  }
}

inline bool decode(const Frame& in, Packet& pk) {
  uint8_t raw[kPacketSize];
  raw[0] = in[0];
  for (uint8_t i = 1; i < kPacketSize; ++i) {
    raw[i] = static_cast<uint8_t>(in[i] ^ kWhitenMask);
  }
  if (raw[0] != kHeader) return false;
  if (crc8(raw, kPacketSize - 1) != raw[kPacketSize - 1]) return false;

  pk.sid = raw[1];
  pk.idx = raw[2];
  for (uint8_t i = 0; i < kPayloadSize; ++i) pk.b[i] = raw[3 + i];
  if (!pk.isInfo() && pk.idx >= kMaxPoints) return false;
  return true;
}

// ---- アンカー (12bit × 2) の詰め方
inline void packAnchor(int16_t x, int16_t y, uint8_t* b) {
  const uint16_t ux = static_cast<uint16_t>(x) & 0x0FFF;
  const uint16_t uy = static_cast<uint16_t>(y) & 0x0FFF;
  b[0] = static_cast<uint8_t>(ux >> 4);
  b[1] = static_cast<uint8_t>(uy >> 4);
  b[2] = static_cast<uint8_t>(((ux & 0x0F) << 4) | (uy & 0x0F));
}

inline int16_t signExtend12(uint16_t v) {
  return static_cast<int16_t>(v & 0x800 ? v | 0xF000 : v);
}

inline void unpackAnchor(const uint8_t* b, int16_t& x, int16_t& y) {
  x = signExtend12(static_cast<uint16_t>((b[0] << 4) | (b[2] >> 4)));
  y = signExtend12(static_cast<uint16_t>((b[1] << 4) | (b[2] & 0x0F)));
}

inline Packet makeInfo(uint8_t sid, uint8_t n, uint8_t kind, uint8_t repeatsLeft) {
  Packet pk{};
  pk.sid = sid;
  pk.idx = kIdxInfo;
  pk.b[0] = n;
  pk.b[1] = kind;
  pk.b[2] = repeatsLeft;
  return pk;
}

// 1 パケットの送信時間 [ms] (8N1 = 1 バイト 10 ビット) — 見積もり用
constexpr uint32_t packetMs(uint8_t gapBits) {
  return (kPacketSize * 10UL + gapBits) * 1000UL / kBaud;
}

}  // namespace irproto
