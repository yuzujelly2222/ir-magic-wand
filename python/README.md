# Python ライブラリ magic_wand (python/)

杖 ([firmware/ir_tx](../firmware/ir_tx)) が送ってくる**ストローク**を受け取って、**x, z の座標**の点列に変換する Python ライブラリです。

- 杖を振り始めてから止めるまでが **1 ストローク**（最大 4 秒、25Hz、**0.2° 刻み**）。送信機が自動で区切って、終わってからまとめて送ってきます
- 受信機 Arduino (ir_rx) から **シリアルで受信**できます
- 保存した **CSV** からも読めます
- 受け取れなかったストロークは **理由つき**で知らせます
- 座標の出し方は 2 種類: **棒の先端**（根元を固定）と **ポインター風**（向いている先の画面上の位置）
- **ジェスチャーの判定**（$1 Unistroke Recognizer）と、判定したら **関数・ファイル・コマンドを実行** するところまでできます

```
[杖 (ATtiny85 + IMU)] ~~ IR ~~> [受信機 Arduino (ir_rx)] --USB--> PC: SerialXZReader --> XZTrack (1 ストロークの点列)
                                                                       │                    └─ XZPoint (x, z, t, ...)
                                                                       ▼
                                          GestureRecognizer ($1) --> GestureResult --> GestureActions (--on)
```

| 使っているもの | どこで |
| --- | --- |
| [ir-imu-protocol](https://github.com/yuzujelly2222/ir-imu-protocol) | `protocol.py` のパケット形式の土台 (ヘッダ・CRC8・whitening・丸め方が共通。v2 はストロークをまとめて送る拡張版) |
| [dollar_one_recognizer_python](https://github.com/yuzujelly2222/dollar_one_recognizer_python) | `gestures.py` の判定の本体 (PyPI の `dollar-one-recognizer-py`) |

---

## 目次

1. [準備](#準備)
2. [まずはこれだけ](#まずはこれだけ)
3. [やりたいこと別の早見表](#やりたいこと別の早見表)
4. [関数一覧 (リファレンス)](#関数一覧-リファレンス)
   - [SerialXZReader — シリアルから受信する](#serialxzreader--シリアルから受信する)
   - [XZTrack — 1 ストロークの点列](#xztrack--1-ストロークの点列)
   - [XZPoint — 1 つの点](#xzpoint--1-つの点)
   - [StrokeDrop — 受け取れなかったストローク](#strokedrop--受け取れなかったストローク)
   - [PointerProjector — ポインター風の座標](#pointerprojector--ポインター風の座標)
   - [CSV の読み書き](#csv-の読み書き)
   - [その他](#その他)
5. [座標の考え方](#座標の考え方)
6. [受け取れなかったとき](#受け取れなかったとき)
7. [CSV の形式](#csv-の形式)
8. [ジェスチャーで何かを実行する](#ジェスチャーで何かを実行する)
9. [コマンドライン](#コマンドライン)
10. [ファイル構成・テスト](#ファイル構成テスト)

---

## 準備

- Python 3.9 以上
- 受信機の Arduino に [firmware/ir_rx/ir_rx.ino](../firmware/ir_rx/ir_rx.ino) を書き込み、USB で PC につなぐ

リポジトリのいちばん上で、パッケージとして入れます（1 回だけ）。

```
pip install -e python
```

`pyserial` と、PyPI の [dollar-one-recognizer-py](https://pypi.org/project/dollar-one-recognizer-py/)（ソースは [dollar_one_recognizer_python](https://github.com/yuzujelly2222/dollar_one_recognizer_python)。`numpy` も入る）も一緒に入ります。
`-e` を付けているので、`python/magic_wand/` の中を書き換えると、入れ直さなくてもそのまま反映されます。

あとはどこからでも import できます。

```python
from magic_wand import SerialXZReader, XZTrack, PointerProjector, GestureRecognizer, load_tracks
```

---

## まずはこれだけ

### A. ストロークが届くたびに座標を取る

```python
reader = SerialXZReader("COM3")   # Linux: "/dev/ttyACM0" など
reader.start()                    # 裏で受信が始まる

while True:
    track = reader.wait_stroke()  # 次のストロークが届くまで待つ
    print(track.get_xz())         # [(x, z), (x, z), ...]

reader.close()                    # 終わるときに必ず呼ぶ
```

### B. ゲームのループなど、待たずに確認する

```python
reader = SerialXZReader("COM3", projector=PointerProjector(distance=1.0))
reader.start()

while True:                        # 画面の更新ループ
    for track in reader.get_new(): # 前回から届いたストローク (なければ空)
        draw(track.get_xz())       # x = 横 (右が +), z = 縦 (上が +)
```

### C. 保存した CSV を読む

```python
tracks = load_tracks("log.csv")   # ストロークのリスト
tracks[0].get_xz()                # 1 本目の [(x, z), ...]
tracks[0][0].x                    # 1 本目の 1 点目の x
```

---

### D. ジェスチャーとして判定する

```python
from magic_wand import GestureRecognizer, PointerProjector, SerialXZReader

recognizer = GestureRecognizer()           # 丸・三角・四角・チェック・Z・鍵穴 など 8 種類

def on_stroke(track):
    r = recognizer.recognize(track)
    print(r.label if r.accepted else "？", r.score)

reader = SerialXZReader("COM3", projector=PointerProjector(), on_stroke=on_stroke)
reader.run()
```

座標は **`PointerProjector()` で出す** こと（棒の先端モードは上下の動きがほとんど出ないので判定できません）。
`GestureRecognizer` は [dollar_one_recognizer_python](https://github.com/yuzujelly2222/dollar_one_recognizer_python) の `dollar_one_recognizer` を包んで、鏡像の登録・しきい値・大きさや閉じ具合の確認を足したものです。
ジェスチャーの描き方・判定のしくみ・`r.reason` の意味・自分の見本の足し方は [GESTURES.md](../GESTURES.md) にまとめています。

### E. ジェスチャーを描いたら何かを実行する

コードを書かなくても、`--on` で決められます（[くわしく](#ジェスチャーで何かを実行する)）。

```
python -m magic_wand gestures COM3 --on circle=lights.py --on square@0.9=notepad.exe
```

---

## やりたいこと別の早見表

`reader` は `SerialXZReader`、`track` は `XZTrack`、`p` は `XZPoint` です。

| やりたいこと | 書き方 |
| --- | --- |
| **受信を始める / 止める** | `reader.start()` / `reader.close()` |
| **次のストロークを待つ** | `reader.wait_stroke()` (秒数を決めるなら `wait_stroke(timeout=5)`) |
| **前回から届いたストローク** | `reader.get_new()` → `[XZTrack, ...]` |
| **最後に届いたストローク** | `reader.latest()` |
| これまでのストローク | `reader.get_tracks()` |
| ストロークが届くたびに何かしたい | `SerialXZReader(..., on_stroke=関数)` |
| **座標のリスト** | `track.get_xz()` → `[(x, z), ...]` |
| x だけ / z だけ | `track.get_x()` / `track.get_z()` |
| 元の角度 | `track.get_angles()` → `[(yaw, pitch), ...]` |
| ストロークの長さ [秒] | `track.duration` |
| 補間された点の数 | `track.missing` |
| ストロークの開始からの時刻 | `p.t` |
| **ポインター風にする** | `SerialXZReader(..., projector=PointerProjector())` |
| 届いた後で座標の出し方を変える | `track.reproject(PointerProjector())` |
| 棒の長さ (座標のスケール) を決める | `SerialXZReader(..., arm_length=0.3)` |
| 受け取れなかったことを知りたい | `SerialXZReader(..., on_drop=関数)` |
| **受信データをファイルに保存** | `SerialXZReader(..., log_csv="log.csv")` |
| 保存したファイルを読む | `load_tracks("log.csv")` |
| 通信品質 (Arduino の集計) | `reader.stats` → `{'strokes': .., 'dropped': .., 'crc_err': .., 'interp': ..}` |

---

## 関数一覧 (リファレンス)

### SerialXZReader — シリアルから受信する

`magic_wand/reader.py`。受信機 Arduino (ir_rx) の出力を読んで、届いたストロークを `XZTrack` にします。
`start()` すると別スレッドで受信し続けるので、自分のプログラムからはいつでも取り出せます。

#### 作り方

```python
reader = SerialXZReader(port, projector=..., arm_length=..., on_stroke=..., ...)
```

| 引数 | 既定値 | 説明 |
| --- | --- | --- |
| `port` | — | シリアルポート名。Windows `"COM3"`、Linux `"/dev/ttyACM0"` / `"/dev/ttyUSB0"`、macOS `"/dev/cu.usbmodem…"` |
| `baud` | `115200` | PC と Arduino 間の速さ (ir_rx に合わせてあるので普通は変えない) |
| `projector` | 棒の先端 | 座標の出し方。ポインター風なら `PointerProjector()` |
| `arm_length` | `1.0` | 棒の長さ (棒の先端モードの座標のスケール) |
| `log_csv` | `None` | 受け取ったストロークを保存する CSV のパス。あとで `load_tracks` で読める |
| `on_stroke` | `None` | ストロークを受け取るたびに `関数(track)` を呼ぶ |
| `on_drop` | `None` | ストロークを捨てたときに `関数(drop)` を呼ぶ ([StrokeDrop](#strokedrop--受け取れなかったストローク)) |
| `on_line` | `None` | `#stats` など、ストローク以外の行が来たら `関数(行の文字列)` を呼ぶ |
| `max_tracks` | `100` | 手元に残すストロークの数 (古いものから消す。`None` なら全部残す) |

> `on_stroke` / `on_drop` / `on_line` は受信スレッドから呼ばれます。tkinter や pygame の画面を直接いじると不具合が出ることがあるので、その場合は画面の更新ループで `reader.get_new()` を呼ぶ方が安全です。

#### 受信の開始・終了

| 関数 | 説明 |
| --- | --- |
| `reader.start()` | 別スレッドで受信を始める |
| `reader.stop()` | 受信スレッドを止める (ポートは開いたまま) |
| `reader.close()` | 止めてポートとログファイルを閉じる。**最後に必ず呼ぶ** |
| `with SerialXZReader(...) as reader:` | `with` を抜けると自動で `close()` |
| `reader.poll()` | スレッドを使わず自分のループで回すときに呼び続ける。今回受け取ったストロークのリストを返す |
| `reader.run(duration=None)` | 今のスレッドで受信し続ける (`duration` 秒で終了、`None` なら `stop()` まで) |
| `reader.process(data)` | バイト列を直接流し込む (シリアル以外のデータ源やテスト用) |

#### ストロークを取る

| 関数 | 戻り値 | 説明 |
| --- | --- | --- |
| `reader.wait_stroke(timeout=None)` | `XZTrack` / `None` | **次のストロークが届くまで待つ**。まだ取り出していないものがあればすぐ返す。`timeout` 秒で届かなければ `None`。`start()` していなければこの中で受信する |
| `reader.get_new()` | `[XZTrack, ...]` | **前回 `get_new()` / `wait_stroke()` を呼んでから届いたもの**。なければ空のリスト |
| `reader.latest()` | `XZTrack` / `None` | 最後に届いたストローク |
| `reader.get_tracks()` | `[XZTrack, ...]` | 手元に残っているストローク (古い順、最大 `max_tracks` 個) |

#### 状態を知る

| 名前 | 型 | 説明 |
| --- | --- | --- |
| `reader.stroke_count` | int | 受け取ったストロークの数 |
| `reader.drop_count` | int | 捨てたストロークの数 |
| `reader.drops` | `[StrokeDrop, ...]` | 捨てたストロークの記録 (最大 `max_tracks` 個) |
| `reader.stats` | dict | Arduino が送ってくる集計 `{'strokes', 'dropped', 'crc_err', 'interp'}` |
| `reader.resets` | int | Arduino が起動した (`#ir_rx ready` を受けた) 回数 |
| `reader.now()` | float | 受信開始からの秒数 (`track.received_at` と同じ基準) |

---

### XZTrack — 1 ストロークの点列

`magic_wand/track.py`。1 ストロークぶんの点 (`XZPoint`) を時間の順に持っています。

| 名前 | 戻り値 | 説明 |
| --- | --- | --- |
| `track.get_xz()` | `[(x, z), ...]` | 座標のリスト |
| `track.get_x()` / `track.get_z()` | `[x, ...]` / `[z, ...]` | x だけ / z だけ |
| `track.get_angles()` | `[(yaw, pitch), ...]` | 元の角度 [度] (ストローク開始点からの相対角) |
| `track.points` | `[XZPoint, ...]` | 点のリスト本体 |
| `track[i]` / `track.get_point(i)` | `XZPoint` | i 番目の点 (`track[-1]` で最後) |
| `len(track)` | int | 点の数 (最大 100) |
| `for p in track:` | | 全部の点を順に取り出す |
| `track.id` | int / None | ストローク ID (送信機が 0〜255 で振る) |
| `track.missing` | int | **届かずに受信機が補間した点の数** (0 なら全部届いた) |
| `track.duration` | float | ストロークの長さ [秒] |
| `track.received_at` | float / None | 受信した時刻 (`reader.now()` と同じ基準) |
| `track.reproject(projector=None, arm_length=None)` | `XZTrack` | 同じ角度から、別の座標の出し方で作り直す |

自分で作る場合: `XZTrack([(yaw, pitch), ...], id=None, missing=0, projector=None, arm_length=1.0)`

---

### XZPoint — 1 つの点

読み取り専用です。

| 名前 | 型 | 説明 |
| --- | --- | --- |
| `p.x` | float | 座標 x (棒の先端: 右が + / ポインター風: 画面の横、右が +) |
| `p.z` | float | 座標 z (棒の先端: 前が + / ポインター風: 画面の縦、上が +) |
| `p.i` | int | ストロークの中で何番目か (0 から) |
| `p.t` | float | ストロークの開始からの秒 (`i / 25`) |
| `p.yaw`, `p.pitch` | float | 元の角度 [度] (ストローク開始点からの相対角) |

---

### StrokeDrop — 受け取れなかったストローク

`on_drop` に渡されます。`reader.drops` にも残ります。

| 名前 | 説明 |
| --- | --- |
| `d.id` | ストローク ID (分かれば) |
| `d.reason` | 理由 ([一覧](#受け取れなかったとき)) |
| `d.received_at` | 受信した時刻 |

---

### PointerProjector — ポインター風の座標

`magic_wand/projection.py`。向いている方向の先にある画面上の位置を出します。**ストロークの書き始めが画面の中央 (0, 0)** になります。

```python
reader = SerialXZReader("COM3", projector=PointerProjector(distance=1.0, max_angle=60.0, limit=None))
```

| 引数 | 既定値 | 説明 |
| --- | --- | --- |
| `distance` | `1.0` | **感度**。大きいほど少し傾けただけで大きく動く (座標の単位もこれと同じ) |
| `max_angle` | `60.0` | 中央からこの角度 [度] より大きく振ると端で止まる |
| `limit` | `None` | x, z をこの値で止める (例 `1.0` なら -1〜1 の範囲) |

---

### CSV の読み書き

| 関数 | 説明 |
| --- | --- |
| `load_tracks(path, projector=None, arm_length=1.0)` | ファイルを読んで `[XZTrack, ...]` を返す ([形式](#csv-の形式)) |
| `save_tracks(path, tracks)` | `stroke,i,yaw,pitch` の形式で保存する |
| `parse_tracks(lines, ...)` | ファイルではなく文字列の行のリストから読む |

---

### その他

| 名前 | ファイル | 説明 |
| --- | --- | --- |
| `project_xz(pitch, yaw, arm_length)` | projection.py | 棒の先端モードの計算。`(x, z)` を返す (既定の座標の出し方) |
| `StrokeParser(projector, arm_length)` | parser.py | ir_rx の出力を 1 行ずつ `feed(line)` すると、確定した `XZTrack` / `StrokeDrop` のリストを返す |
| `parse_stats("#stats,strokes=1,...")` | parser.py | `{'strokes': 1, ...}` に変換 |
| `RX_BAUD` | reader.py | `115200` |
| `encode(Packet)` / `decode(bytes)` | protocol.py | IR パケット (13 バイト) の作成 / 読み取り。不正なら `decode` は `None` |
| `Framer` | assembler.py | バイト列から 13 バイトのパケットを切り出す (ずれたら再同期) |
| `StrokeAssembler` | assembler.py | パケットから 1 ストロークを組み立てて欠けを補間する (ir_rx と同じ処理) |
| `encode_stroke(sid, [(yaw, pitch), ...])` | protocol.py | 送信機と同じ手順でパケット列を作る (テスト用) |

`protocol.py` と `assembler.py` は、firmware の `protocol.h` と `ir_rx/stroke_assembler.h` の Python 版です。ふつうは受信機の Arduino がパケットを組み立ててくれるので使う必要はありません。Raspberry Pi などで受光モジュールの出力を直接読むときや、パケットを 16 進で保存した CSV を読むときに使います。

`protocol.py` の `crc8` と whitening、角度の丸め方は [ir-imu-protocol](https://github.com/yuzujelly2222/ir-imu-protocol) の `python/protocol.py` と同じです（違いはトップの [README の「ir-imu-protocol との違い」](../README.md#ir-imu-protocol-との違い)）。

---

## 座標の考え方

届くのは **角度 (向き) だけ** で、しかも **ストロークの開始点からの相対角** です（ストロークの 1 点目は必ず yaw = 0, pitch = 0）。
角度は 0.2° 刻みで届きます（送信機のシミュレーションでは、真の角度との差が最大 0.13°、RMS 0.07°）。
移動した距離は測れないので、向きから座標を計算しています。手を平行に動かした分 (向きが変わらない動き) は座標に出ません。

### 棒の先端 (既定)

根元を原点に固定した長さ `arm_length` の棒が、受け取った角度の方向を向いていると考え、その **先端を真上から見た位置** を出します。
z の正の向きは、ストロークを書き始めたときに向いていた方向です。

```
        真上から見た図

              +z (ストロークの書き始めに向いていた方向)
               ↑
               |   ● 棒の先端 (x, z)
               |  /
               | /  ← 長さ L (arm_length)
               |/  yaw
  ─────────────●──────────→ +x
             根元 (原点)

  x = L · cos(pitch) · sin(yaw)
  z = L · cos(pitch) · cos(yaw)
```

- 座標の単位は `arm_length` と同じ (`arm_length=0.3` なら m)。書き始めは必ず `(0, L)`
- 上下に傾けると原点に近づく (上下の動きは区別できない)。**ジェスチャ認識などで上下の動きも使うなら ポインター風の方が向いています**

### ポインター風 (`PointerProjector`)

向いている方向の先にある仮想の画面上の位置を出します。書き始めが画面の中央 (0, 0) です。

```
  x = distance · tan(yaw)                 … 横 (右が +)
  z = distance · tan(pitch) / cos(yaw)    … 縦 (上が +)
```

### 自分で計算方法を決める

`projector` に `(pitch, yaw, arm_length) -> (x, z)` を返す関数を渡せます。角度は度です。

```python
SerialXZReader("COM3", projector=lambda pitch, yaw, L: (yaw, pitch))   # 角度をそのまま座標に
```

---

## 受け取れなかったとき

欠けた点は受信機 (ir_rx) が前後から補間するので、少しのパケットロスなら普通に届きます (`track.missing` が補間した点の数)。
届いた点が少なすぎるなどで使えないストロークは、`on_drop` / `reader.drops` で知らせます。

| `reason` | 判断する所 | 意味 |
| --- | --- | --- |
| `too_many_lost` | ir_rx | 届いた点が 6 割未満 |
| `too_short` | ir_rx | 点が 2 つ未満 |
| `broken_line` | PC | シリアルの行が壊れていた |
| `incomplete` | PC | `#stroke_end` の前に途切れた (行の取りこぼし・Arduino のリセットなど) |

受信が不安定なら、まず `reader.stats` の `crc_err` と `dropped` を見て、送信機の向きや距離を調整してください。

---

## CSV の形式

`load_tracks()` は次のどれでも読めます。

**1. 保存したファイル** (`log_csv=` / `save_tracks()`)。1 行目のヘッダで列を判別します (大文字小文字・列の順番は自由、関係ない列は無視)。

```
stroke,i,yaw,pitch
0,0,0.0,0.0
0,1,10.8,3.2
1,0,0.0,0.0
```

| 列名 | 内容 |
| --- | --- |
| `yaw`, `pitch` (必須) | 角度 [度] (ストローク開始点からの相対角) |
| `stroke` / `id` / `sid` | ストローク ID (同じ値の行が 1 本のストローク。なければ全体で 1 本) |
| `i` / `index` | ストロークの中の順番 (なければ行の順) |

ヘッダがない場合: 2 列なら `yaw,pitch`、3 列なら `stroke,yaw,pitch`、4 列なら `stroke,i,yaw,pitch`。

**2. シリアルモニタの出力をそのまま保存したもの** (`#stroke_begin` / `pt,...` / `#stroke_end` の行)。

**3. IR パケットを 16 進で並べたもの** (`packet` / `raw` 列、例 `aa555555555555555f5f5b5b35`)。受信機と同じ手順で組み立てます。
時刻の列 (`t` / `time` [秒] か `time_ms` / `millis` [ミリ秒]) があれば使い、なければ 0.1 秒間隔とみなします。

---

## ジェスチャーで何かを実行する

`gestures` と `view` に **`--on`** を付けると、「このジェスチャーを、このスコア以上で描いたら、これを実行する」を決められます。
`--on` は何度でも書けます。

```
python -m magic_wand gestures COM3 \
    --on circle=lights.py \
    --on square@0.9=notepad.exe \
    --on zigzag=examples/spells.py:lights_on \
    --on "*=cmd:echo {label} {score}"
```

書き方は **`ジェスチャー名[@しきい値]=実行するもの`** です。

| 部分 | 説明 |
| --- | --- |
| ジェスチャー名 | `circle` `square` など ( `python -m magic_wand gestures --list` で一覧)。`*` はどのジェスチャーでも |
| `@しきい値` | このスコア以上で実行する (0〜1)。省略すると `--threshold` (既定 0.80)。`--threshold` より低くしてもよく、そのジェスチャーにだけ甘くできる |
| 実行するもの | 下の表のどれか |

実行するものは、形から自動で決まります。はっきりさせたいときは先頭に `func:` `py:` `cmd:` `open:` を付けます。

| 書き方 | 種類 | 何が起きるか |
| --- | --- | --- |
| `spells.py:lights_on` / `mypkg.mymod:lights_on` | `func` | その関数を呼ぶ (`f()` / `f(result)` / `f(result, track)` のどれでもよい) |
| `lights.py` / `lights.py --fast` | `py` | 同じ Python で実行する (引数も渡せる) |
| `notepad.exe` / `echo hi` | `cmd` | シェルのコマンドとして実行する |
| `chime.wav` (存在するファイル) | `open` | 関連付けられたアプリで開く (Linux/macOS で実行権限があれば実行) |

- コマンドと引数の中の `{gesture}` `{label}` `{score}` `{id}` は判定結果に置き換わります
- 実行するプログラムには環境変数 `MAGIC_WAND_GESTURE` `MAGIC_WAND_LABEL` `MAGIC_WAND_SCORE` `MAGIC_WAND_STROKE_ID` も渡します
- プログラムは起動するだけで、終わるのは待ちません。関数は 1 本の作業スレッドで順に呼ぶので、受信は止まりません
- 「小さすぎ」「閉じていない」で受け付けなかったストロークでは、しきい値に関係なく実行しません
- 関数の読み込みに失敗したとき (ファイルがない・関数がない) は、受信を始める前にエラーで止まります

| オプション | 既定値 | 説明 |
| --- | --- | --- |
| `--on 名前[@しきい値]=実行するもの` | — | 上のとおり。何度でも |
| `--threshold 0〜1` | `0.80` | 判定のしきい値 (`@` を省略した `--on` もこれを使う) |
| `--only circle,square` | 全部 | 使うジェスチャーをしぼる |
| `--cooldown 秒` | `1.0` | 同じ `--on` を続けて実行しない時間 |
| `--dry-run` | — | 実行せずに、何が実行されるかだけ表示する |
| `--list` | — | 使えるジェスチャーの名前を表示して終わる (`gestures` のみ) |
| `--no-color` | — | 色を付けない (`gestures` のみ。環境変数 `NO_COLOR` でも同じ) |

### Python から

`--on` と同じことを `GestureActions` でできます。`handle` を `on_stroke` にそのまま渡します。

```python
from magic_wand import GestureActions, GestureRecognizer, PointerProjector, SerialXZReader

actions = GestureActions(GestureRecognizer(threshold=0.8))
actions.on("square", "notepad.exe", threshold=0.9)       # --on の右辺と同じ書き方

@actions.on("circle")
def lights_on(result, track):
    print("明かりをつける!", result.score)

with SerialXZReader("COM3", projector=PointerProjector(), on_stroke=actions.handle) as reader:
    reader.run()
```

| 関数 | 説明 |
| --- | --- |
| `GestureActions(recognizer, dry_run=False, on_error=None)` | 作る。`on_error(action, error)` は実行に失敗したときに呼ぶ (既定は標準エラーに出す) |
| `actions.on(名前, 実行するもの, threshold=None, cooldown=0)` | 登録する。実行するものは関数か文字列。省略するとデコレータになる |
| `actions.handle(track)` | 判定して、合うものを実行する。`GestureResult` を返す |
| `actions.dispatch(result, track)` | 判定済みの結果で実行する。実行したもののリストを返す |
| `actions.wait()` | 登録した関数の実行が全部終わるまで待つ |
| `parse_action("circle@0.9=lights.py")` | `--on` の文字列を `Action` にする |

例は [examples/spells.py](examples/spells.py) にあります。

---

## コマンドライン

`pip install -e python` のあとは、どこからでも動きます。

```
python -m magic_wand listen COM3                     # 受信してストロークごとに座標を表示
python -m magic_wand listen COM3 --log log.csv       # 保存しながら表示
python -m magic_wand listen COM3 --pointer           # ポインター風
python -m magic_wand gestures COM3                   # 受信してジェスチャーを判定する
python -m magic_wand gestures COM3 --on circle=a.py  # 丸を描いたら a.py を実行する
python -m magic_wand gestures --list                 # 使えるジェスチャーの名前
python -m magic_wand view COM3                       # 描いた形と判定結果を画面に出す (tkinter)
python -m magic_wand view --demo                     # 実機なし (ダミーデータ)
python -m magic_wand csv python/examples/sample.csv  # CSV の中身を表示
```

それぞれ `-h` でオプションが出ます（例: `python -m magic_wand listen -h`）。Ctrl+C で終了します。

- ポートを開くと Arduino がリセットされるので、最初の 1〜2 秒は何も来ません
- シリアルポートは 1 つのプログラムしか開けません (Arduino IDE のシリアルモニタを開いたままだと失敗します)

---

## ファイル構成・テスト

```
python/
├── pyproject.toml          パッケージの設定 (pip install -e python で入れる)
├── magic_wand/             ライブラリ本体
│   ├── __init__.py         よく使うものをまとめて import できるようにする
│   ├── __main__.py         python -m magic_wand <コマンド>
│   ├── protocol.py         IR パケットの定義 (firmware の protocol.h の Python 版。ir-imu-protocol の拡張)
│   ├── assembler.py        パケットから 1 ストロークを組み立てる StrokeAssembler / Framer
│   ├── projection.py       角度を x, z 座標に直す project_xz / PointerProjector
│   ├── track.py            1 ストロークの点列 XZTrack / XZPoint / StrokeDrop
│   ├── parser.py           受信機の出力を読む StrokeParser
│   ├── csv_io.py           CSV の読み書き load_tracks / save_tracks
│   ├── reader.py           シリアルから受信する SerialXZReader
│   ├── templates.py        ジェスチャーの見本 TEMPLATES / CLOSED
│   ├── gestures.py         ジェスチャーの判定 GestureRecognizer (dollar_one_recognizer_python を使う)
│   ├── actions.py          ジェスチャーを描いたら実行する GestureActions (--on)
│   ├── demo.py             実機なしで試すためのダミーの受信機 DemoSerial
│   ├── viewer.py           描いた形と判定結果を出す tkinter のビューア
│   └── style.py            コマンドラインの見た目 (色・記号)
├── examples/
│   ├── on_stroke.py        自分のプログラムでジェスチャーを使ういちばん短い例
│   ├── spells.py           --on や GestureActions から呼ぶ関数の例
│   └── sample.csv          サンプル CSV (円と直線の 2 ストローク)
└── tests/                  テスト (モジュールごとに test_<モジュール名>.py)
    ├── helpers.py          テストで共通に使うもの (FakeSerial など)
    └── fixture_firmware.py 送信機 (C++) が実際に出すフレームと、受信機の組み立て結果
```

テストの実行:

```
cd python
python -m unittest
```

`tests/test_protocol.py` では、送信機 (C++) の出力を Python 版で組み立てて、受信機 (C++) と同じ結果になることも確かめています。

## ライセンス

[MIT License](../LICENSE) © 2026 yuzujelly2222

依存している [dollar_one_recognizer_python](https://github.com/yuzujelly2222/dollar_one_recognizer_python) は New BSD License です。
