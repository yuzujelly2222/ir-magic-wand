// stroke_assembler.h — 受信したパケットから 1 ストロークを組み立てる (プロトコル v2)
//
// - sid が変わったら前のストロークを確定し、新しいストロークを始める
// - INFO(end) で残り再送が 0 なら確定。再送が残っていて欠けがあれば待つ
// - パケットが kTimeoutMs 来なければ確定 (end を取りこぼした場合)
// - DATA パケットはアンカー (絶対座標) から差分を足して 4 点を復元する。
//   パケットを落としても、そのパケットの 4 点が欠けるだけ
// - 欠けた点は前後の点から直線補間する (先頭・末尾の欠けは最寄りの点で埋める)
// - 受信できた点が少なすぎるときは破棄。INFO を両方落としても、点数は DATA から分かる
//
// Arduino に依存しないので PC でもテストできる。
#pragma once
#include <stdint.h>
#include "protocol.h"

class StrokeAssembler {
 public:
  static constexpr uint16_t kTimeoutMs  = 400;  // パケット間隔は約 120ms
  static constexpr uint8_t  kMinPercent = 60;   // これ未満しか届かなければ破棄
  static constexpr uint16_t kDoneHoldMs = 3000; // 確定後この時間は同じ sid の再送を無視

  enum class Result : uint8_t { None, Ready, Dropped };

  // パケットを 1 つ渡す。戻り値が None 以外なら、内容を読んでから consume() を呼ぶ
  Result push(const irproto::Packet& pk, uint32_t nowMs) {
    // 確定済みストロークの再送は無視 (送信機が再起動して sid が戻った場合に
    // 備えて、一定時間たったら忘れる)
    if (hasDone_ && pk.sid == doneSid_ &&
        static_cast<uint32_t>(nowMs - doneMs_) < kDoneHoldMs) {
      return Result::None;
    }
    if (active_ && pk.sid != sid_) {
      // 前のストロークの end を落とした。確定してから、このパケットを処理する
      pending_ = pk;
      hasPending_ = true;
      pendingMs_ = nowMs;
      return finalize();
    }
    if (!active_) start(pk.sid);
    lastMs_ = nowMs;

    if (pk.isInfo()) {
      n_ = pk.b[0] > irproto::kMaxPoints ? irproto::kMaxPoints : pk.b[0];
      if (pk.b[1] == irproto::kInfoEnd && (pk.b[2] == 0 || received() >= n_)) {
        return finalize();
      }
      return Result::None;
    }

    int16_t x, y;
    irproto::unpackAnchor(pk.b, x, y);
    for (uint8_t k = 0; k < irproto::kPointsPerPkt; ++k) {
      if (k > 0) {
        const int8_t dx = static_cast<int8_t>(pk.b[1 + k * 2]);
        const int8_t dy = static_cast<int8_t>(pk.b[2 + k * 2]);
        if (dx == irproto::kNoPoint) break;
        x += dx;
        y += dy;
      }
      const uint8_t j = pk.idx + k;
      if (j >= irproto::kMaxPoints) break;
      x_[j] = x;
      y_[j] = y;
      setHave(j);
      if (j + 1 > top_) top_ = j + 1;
    }
    return Result::None;
  }

  // 一定時間パケットが来なければ確定する。loop() から呼ぶ
  Result poll(uint32_t nowMs) {
    if (active_ && static_cast<uint32_t>(nowMs - lastMs_) >= kTimeoutMs) {
      lastMs_ = nowMs;
      return finalize();
    }
    return Result::None;
  }

  // push()/poll() が Ready / Dropped を返したあとに呼ぶ
  Result consume() {
    if (hasPending_) {
      hasPending_ = false;
      return push(pending_, pendingMs_);
    }
    return Result::None;
  }

  // ---- 確定したストロークの中身 (Ready のとき)
  uint8_t sid()     const { return sid_; }
  uint8_t size()    const { return n_; }
  uint8_t missing() const { return missing_; }
  // 角度 [0.01°] (整数)。yaw = 右が +、pitch = 上が +
  int16_t xCdeg(uint8_t i) const { return x_[i] * irproto::kUnitCdeg; }
  int16_t yCdeg(uint8_t i) const { return y_[i] * irproto::kUnitCdeg; }
  float xDeg(uint8_t i) const { return xCdeg(i) / 100.0f; }
  float yDeg(uint8_t i) const { return yCdeg(i) / 100.0f; }
  const char* dropReason() const { return dropReason_; }

 private:
  void start(uint8_t sid) {
    active_ = true;
    sid_ = sid;
    n_ = 0;
    top_ = 0;
    missing_ = 0;
    for (auto& b : have_) b = 0;
  }

  bool has(uint8_t i) const { return have_[i >> 3] & (1u << (i & 7)); }
  void setHave(uint8_t i) { have_[i >> 3] |= static_cast<uint8_t>(1u << (i & 7)); }

  uint8_t received() const {
    uint8_t c = 0;
    for (uint8_t i = 0; i < irproto::kMaxPoints; ++i) c += has(i);
    return c;
  }

  Result finalize() {
    active_ = false;
    hasDone_ = true;
    doneSid_ = sid_;
    doneMs_ = lastMs_;

    if (n_ == 0) n_ = top_;  // INFO が両方届かなかった場合
    if (n_ < 2) { dropReason_ = "too_short"; return Result::Dropped; }

    uint8_t got = 0;
    for (uint8_t i = 0; i < n_; ++i) got += has(i);
    missing_ = n_ - got;
    if (got * 100u < static_cast<uint16_t>(n_) * kMinPercent || got < 2) {
      dropReason_ = "too_many_lost";
      return Result::Dropped;
    }

    // 欠けを補間
    int16_t prev = -1;
    for (uint8_t i = 0; i < n_; ++i) {
      if (has(i)) { prev = i; continue; }
      int16_t next = i + 1;
      while (next < n_ && !has(static_cast<uint8_t>(next))) ++next;
      if (prev < 0) {                       // 先頭の欠け
        x_[i] = x_[next]; y_[i] = y_[next];
      } else if (next >= n_) {              // 末尾の欠け
        x_[i] = x_[prev]; y_[i] = y_[prev];
      } else {
        x_[i] = lerp(x_[prev], x_[next], i - prev, next - prev);
        y_[i] = lerp(y_[prev], y_[next], i - prev, next - prev);
      }
    }
    dropReason_ = "";
    return Result::Ready;
  }

  static int16_t lerp(int16_t a, int16_t b, int16_t num, int16_t den) {
    const int32_t d = static_cast<int32_t>(b - a) * num;
    const int32_t q = d >= 0 ? (d + den / 2) / den : -((-d + den / 2) / den);
    return static_cast<int16_t>(a + q);
  }

  int16_t x_[irproto::kMaxPoints] = {};  // 0.2° 単位
  int16_t y_[irproto::kMaxPoints] = {};
  uint8_t have_[(irproto::kMaxPoints + 7) / 8] = {};

  bool     active_ = false;
  uint8_t  sid_ = 0, n_ = 0, top_ = 0, missing_ = 0;
  uint32_t lastMs_ = 0;

  bool     hasDone_ = false;
  uint8_t  doneSid_ = 0;
  uint32_t doneMs_ = 0;

  bool             hasPending_ = false;
  irproto::Packet  pending_{};
  uint32_t         pendingMs_ = 0;

  const char* dropReason_ = "";
};
