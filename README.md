# ir-magic-wand — 赤外線で飛ばす魔法の杖

ATtiny85 + MPU-6050 の杖を振ると、その軌跡が **赤外線で PC に届き**、**ジェスチャーとして判定され**、**決めておいた処理が実行されます**。

- 送信機はストロークの始まりと終わりを **自動で判定**し、最大 4 秒分の点列をため込んでから **まとめて送ります**
- 受信機は 1 ストロークの 2D 点列に組み立て、欠けた点を補間して USB で PC に渡します
- PC の Python ライブラリ `magic_wand` が x, z 座標の軌跡にして、**$1 Unistroke Recognizer** で判定します
- `--on circle=lights.py` のように書くだけで、ジェスチャーごとに関数・ファイル・コマンドを実行できます

```
[MPU-6050] → [ATtiny85 送信機] ~~~ 940nm IR (38kHz, 1200bps) ~~~> [OSRB38C9AA] → [Arduino 受信機] → USB → PC (Python)
 firmware/ir_tx                                                                     firmware/ir_rx           python/
 └─────────── パケット: ir-imu-protocol を拡張した v2 ───────────────────────────┘                        └─ 判定: dollar_one_recognizer_python
```

## 関連リポジトリ

このプロジェクトは、同じ作者の 2 つのリポジトリの上に組み立てています。

| リポジトリ | このプロジェクトでの役割 |
|---|---|
| [**ir-imu-protocol**](https://github.com/yuzujelly2222/ir-imu-protocol) | IMU の姿勢角を IR で送るための 9 バイトのパケット定義 (C++ / Python)。ヘッダ・CRC8・whitening・角度の丸め方をそのまま引き継ぎ、**ストロークをまとめて送れるように拡張したのが v2**（[パケット形式](#パケット形式v2)） |
| [**dollar_one_recognizer_python**](https://github.com/yuzujelly2222/dollar_one_recognizer_python) | $1 Unistroke Recognizer の Python 実装 ([PyPI: dollar-one-recognizer-py](https://pypi.org/project/dollar-one-recognizer-py/))。`magic_wand` の `GestureRecognizer` が中で使っています。`pip install -e python` で一緒に入ります（[GESTURES.md](GESTURES.md)） |

```
ir-imu-protocol (9 バイト / 1 サンプル)          dollar_one_recognizer_python ($1 本体)
        │ 拡張                                              │ 依存 (PyPI)
        ▼                                                   ▼
firmware/*/protocol.h ─ python/magic_wand/protocol.py   python/magic_wand/gestures.py
   (v2: 13 バイト / 4 点、ストローク一括送信)             (鏡像の登録・大きさや閉じ具合の確認を追加)
```

## 構成

```
ir-magic-wand/
├── firmware/
│   ├── ir_tx/                送信機スケッチ (ATtiny85)
│   │   ├── ir_tx.ino
│   │   └── protocol.h
│   └── ir_rx/                受信機スケッチ (Uno / Nano / Leonardo など)
│       ├── ir_rx.ino
│       ├── stroke_assembler.h   パケット → ストロークの組み立て・欠けの補間
│       └── protocol.h        （ir_tx と同じファイル。変更したら両方そろえる）
├── python/                   PC 側のライブラリ magic_wand (詳しくは python/README.md)
│   ├── pyproject.toml        pip install -e python で入れる (dollar-one-recognizer-py も入る)
│   ├── magic_wand/           ライブラリ本体 (受信・座標・CSV・ジェスチャー判定・実行・ビューア)
│   ├── examples/             使い方の例とサンプル CSV
│   └── tests/                テスト
└── GESTURES.md               ジェスチャーの描き方・判定のしくみ
```

## 必要なもの

| 役割 | 部品 |
|---|---|
| 送信機 | ATtiny85、GY-521 (MPU-6050)、940nm IR LED (5mm, 30°)、NPN トランジスタ (2SC1815 など)、33Ω、1kΩ、0.1µF、（状態表示用 LED + 1kΩ） |
| 受信機 | Arduino Uno / Nano / Leonardo など、OSRB38C9AA、100Ω、4.7µF |
| 書き込み | Arduino as ISP などの ISP ライター |

## 配線

### 送信機 (ATtiny85)

| ATtiny85 | 接続先 |
|---|---|
| 8 (VCC) / 4 (GND) | 5V / GND（VCC–GND 間に 0.1µF） |
| 5 (PB0, SDA) | GY-521 SDA |
| 7 (PB2, SCL) | GY-521 SCL |
| 6 (PB1, OC1A) | 1kΩ → トランジスタのベース |
| 2 (PB3) | 1kΩ → 状態表示 LED → GND（任意） |

- IR LED は **5V → 33Ω → IR LED → トランジスタのコレクタ**、エミッタは GND（約 100mA 流れるのでピン直結は不可）
- PB1 は Timer1 の出力ピン (OC1A) なので、ほかのピンには変更できません
- GY-521 には 4.7kΩ 程度のプルアップが載っているので、I2C の外付け抵抗は不要です

### 受信機

| 接続元 | 接続先 |
|---|---|
| OSRB38C9AA VCC | 100Ω を通して 5V（VCC–GND 間に 4.7µF） |
| OSRB38C9AA GND | GND |
| OSRB38C9AA OUT | Uno / Nano: **D8** ／ Leonardo など: **RX (Serial1)** |

ピン配置はデータシートで確認してください。

## 書き込み

1. Arduino IDE に **ATTinyCore** を入れ、ボードを「ATtiny25/45/85 (No bootloader)」、Chip = ATtiny85、**Clock = 8 MHz (internal)**（または 16 MHz PLL）にする
2. **最初に一度「ブートローダを書き込む」を実行**してクロックのヒューズを書く（出荷時は 1MHz で、そのままだとビルドエラーになる）
3. `firmware/ir_tx/ir_tx.ino` を「書き込み装置を使って書き込む」で書き込む
4. `firmware/ir_rx/ir_rx.ino` を受信機の Arduino に普通に書き込む

## 使い方

1. 送信機の電源を入れたら、**数秒間動かさずに置く**（ジャイロの補正中は状態 LED が点灯）
2. 杖を振ると自動でストロークが始まり（LED 点灯）、止めると終わって送信が始まる（LED 点滅）
3. 受信機のシリアルモニタを 115200bps で開くと、ストロークごとに次の行が出る

```
#ir_rx ready
#stroke_begin,id=0,n=42,missing=0
pt,0.0,0.0
pt,1.5,-0.5
...
#stroke_end
#stats,strokes=1,dropped=0,crc_err=0,interp=0
```

`pt` は開始点からの相対角 [度]（x = yaw、y = pitch で上が +）。`missing` は届かずに補間した点の数です。

4. PC 側では Python ライブラリ `magic_wand` でストロークを受け取ります（Python 3.9 以上）。リポジトリのいちばん上で 1 回だけ入れます

```
pip install -e python
```

```python
from magic_wand import PointerProjector, SerialXZReader

reader = SerialXZReader("COM3", projector=PointerProjector())
reader.start()
while True:
    track = reader.wait_stroke()          # 次のストロークが届くまで待つ
    print(track.get_xz())                 # [(x, z), ...]
```

5. ジェスチャーとして判定する（[dollar_one_recognizer_python](https://github.com/yuzujelly2222/dollar_one_recognizer_python) の $1 Unistroke Recognizer）

```python
from magic_wand import GestureRecognizer

recognizer = GestureRecognizer()          # 丸・三角・四角・チェック・Z・鍵穴 など 8 種類

def on_stroke(track):
    r = recognizer.recognize(track)
    if r.accepted:
        print(r.label, r.score)           # 例: 丸 0.95

reader = SerialXZReader("COM3", projector=PointerProjector(), on_stroke=on_stroke)
reader.run()
```

**ジェスチャーの描き方と杖の向きは [GESTURES.md](GESTURES.md) にまとめています。**

すぐ試せる例:

```
python -m magic_wand gestures COM3   # 判定結果を表示する
python -m magic_wand gestures COM3 --on circle=lights.py --on square@0.9=notepad.exe
                                     # 丸を描いたら lights.py、四角を 0.9 以上で描いたら notepad
python -m magic_wand view COM3       # 描いた形と判定結果を画面に出す
python -m magic_wand view --demo     # 実機なし (ダミーデータ)
```

6. 自分のジェスチャーを足すときは、dollar_one_recognizer_python の `export_gesture_app.py` でマウスで描いて CSV に保存し、`recognize_app.py` で判定のされ方を確かめてから杖で使えます（[GESTURES.md](GESTURES.md#自分でジェスチャーを足す)）

関数の一覧や座標の考え方は [python/README.md](python/README.md) を見てください。

## ストロークの判定

動きの量 `m = |gy| + |gz|` [deg/s] で判定します。値は `firmware/ir_tx/ir_tx.ino` の `cfg` で変えられます。

| 項目 | 既定値 | 意味 |
|---|---|---|
| `kStartLsb` / `kStartTicks` | 30 dps / 6 回 | これを超える状態が 6 回 (30ms) 続いたら開始 |
| `kEndLsb` / `kEndQuietTicks` | 10 dps / 40 回 | これを下回る状態が 40 回 (200ms) 続いたら終了 |
| `kMaxPoints` | 100 点 (4 秒) | 4 秒たったら強制的に終了 |
| `kMinPoints` | 4 点 (160ms) | これより短いストロークは捨てる |
| `kPrePoints` | 2 点 | 開始判定より前の点も含める（書き出しの取りこぼし防止） |

- 開始のしきい値を終了より高くして、境界付近でのチャタリングを防いでいます
- 終わりの静止区間 (200ms) は送る前に切り捨てます
- 静止中はジャイロのゼロ点をゆっくり追従させ、温度ドリフトで判定がずれないようにしています
- 3 軸のジャイロ（ひねりの gx も含む）を整数のクォータニオンで積分し、「書き始めの向きから見て、杖の先が今どこを指しているか」を送ります。描いている途中で手首がひねられても、大きく振っても、形が崩れません
- 送るのは開始点からの相対角なので、加速度による絶対姿勢の補正は不要です（振ったときの加速度の影響も受けません）
- 送信後は、いったん静止するまで次のストロークを受け付けません

## パケット形式（v2）

[ir-imu-protocol](https://github.com/yuzujelly2222/ir-imu-protocol) を土台に、ジェスチャー用に拡張した形式です。
1200bps 8N1。1 パケット 13 バイトで、パケットの間に約 15ms の休止を入れます（受光モジュールの AGC 対策）。

### ir-imu-protocol との違い

ir-imu-protocol は「1 パケット = その瞬間の roll / pitch / yaw 1 組」を流し続ける形式です。
1200bps では 1 パケット (9 バイト = 90bit) に約 75ms かかり、**最大 13.3Hz** しか送れません。
ジェスチャーは 25Hz で取りたいので、v2 では **ストロークをため込んでから、1 パケットに 4 点ずつ詰めて送る** ようにしました。

| | ir-imu-protocol | v2 (このプロジェクト) |
|---|---|---|
| 通信条件 | 1200bps 8N1, LSB first | 同じ |
| ヘッダ | `0xAA` | 同じ |
| CRC8 | 多項式 0x07, 初期値 0x00 | 同じ（範囲はバイト 0〜11） |
| Whitening | ヘッダ以外を `0x55` で XOR | 同じ |
| 角度の丸め | 四捨五入 (0 から遠い方へ) | 同じ |
| 長さ | 9 バイト | 13 バイト |
| 中身 | roll / pitch / yaw（度 × 100 の int16） | yaw / pitch の 4 点（0.2° 単位、アンカー 12bit + 差分 int8） |
| 番号 | `seq`（パケットごと） | `sid`（ストロークごと）+ `idx`（何点目か） |
| 送り方 | 測るたびに 1 パケット | ストロークが終わってから `INFO → DATA… → INFO` でまとめて（再送も可） |
| 1 点あたり | 約 75ms（最大 13.3 点/秒） | 約 31ms（4 点 / 123ms ≈ 32 点/秒） |
| 欠けたとき | そのサンプルがなくなる | 受信機が前後から補間する |

roll は送っていません。杖のひねりは送信機の中でクォータニオンとして積分に使い、送るのは「杖の先が指している向き」の yaw / pitch だけです。

### v2 のパケット

```
[0xAA][sid][idx][b0][b1][b2][b3][b4][b5][b6][b7][b8][CRC8]
```

| フィールド | 内容 |
|---|---|
| `0xAA` | ヘッダ |
| `sid` | ストローク ID（送るたびに +1） |
| `idx` | 0〜99: DATA（点 idx〜idx+3 の 4 点）／ 0xFF: INFO |
| DATA の b0〜b2 | 点 idx の**絶対座標**（アンカー）。x, y を 12bit 符号付きで詰める（b0 = x の上位 8bit、b1 = y の上位 8bit、b2 = x の下位 4bit ‖ y の下位 4bit） |
| DATA の b3〜b8 | 点 idx+1〜idx+3 の、1 つ前の点からの**差分** (dx, dy) を int8 で。-128 は「点なし」 |
| INFO | b0 = 点数、b1 = 0: begin / 1: end、b2 = 残りの再送回数 |
| `CRC8` | 多項式 0x07、バイト 0〜11 から計算 |

- 座標は x = yaw、y = pitch の、ストローク開始点からの相対角で、**単位は 0.2° 固定**です（12bit なので ±409°）
- 差分は 1 点 (40ms) あたり ±25.4°（= ±635 deg/s）まで表せます。ジャイロの上限 (±500 deg/s) より広いので、振り方で精度が落ちることはありません
- パケットごとに絶対座標が入っているので、パケットを落としても**そのパケットの 4 点が欠けるだけ**で、後ろの点はずれません
- 1 ストロークは `INFO(begin) → DATA × ⌈n/4⌉ → INFO(end)` の順に送ります
- ヘッダ以外は `0x55` で XOR して送っています（値が 0 付近のときにキャリアが長く連続しないように。ir-imu-protocol と同じ）

**送信時間**は 1 パケット約 123ms で、4 秒 (100 点) のストロークなら約 3.3 秒、2 秒なら約 1.7 秒です。
取りこぼしが多い場合は `kRepeat` を 2 にすると、受信側で欠けた点を 2 回目の送信から埋めます（送信時間は倍）。

受信側は、届かなかった点を前後から直線補間します。6 割未満しか届かなかったストロークは `#drop` を出して捨てます。
INFO を両方落としても、点数は DATA から分かるので捨てません。

### 精度

送信機を PC 上でシミュレートして、杖を実際に 3 次元で回したときの「杖の先が指す向き」と、受信機の出力を比べました。
形は、3.6 秒かけて描く 8 の字（左右 ±40°、上下 ±20°）です。誤差は、各点での真の向きとのユークリッド距離 √(Δyaw² + Δpitch²) です。

| 条件 | 平均 | 最大 |
|---|---|---|
| センサーが理想的な場合 | 0.14° | 0.28° |
| 描く途中で手首が ±20° ひねられる | 0.15° | 0.29° |
| よくありそうな組み合わせ（感度・軸の干渉・クロックの誤差 各 1%、ゼロ点のずれ 0.1°/s、ひねり ±10°） | 0.39° | 0.69° |
| 悪い組み合わせ（データシート上限の誤差、ゼロ点のずれ 0.5°/s、ひねり ±20°） | 1.6° | 2.7° |
| ひねりを 500°/s より速くする（ジャイロが振り切れる） | 3.2° | 9.3° |

精度のためにしていること:

- IMU を 200Hz で読んで積分する（DLPF 98Hz）
- 3 軸の回転をクォータニオンでまとめて積分する（上下と左右を別々に足すと、ひねりや大きな振りで形が崩れる）
- 点は 0.2° に四捨五入し、差分は「四捨五入した値どうしの差」でためる（足し戻しても誤差が積み上がらない）

## 注意

- **yaw は相対値**です。地磁気センサを使っていないので、ストロークの開始点を 0° とした相対角だけを送ります
- **GY-521 の取り付け向き**は `firmware/ir_tx/ir_tx.ino` の `cfg::kMount` で選びます（X が杖の先 / Y が杖の先 / Y が持ち手側。既定は Y が持ち手側）。合っていないと上下の動きがほとんど出ません（[GESTURES.md](GESTURES.md)）
- **書き始めの時点で杖がひねられている**と、描いた絵全体がその角度だけ回って出ます（形は崩れません）。ジェスチャーの判定は回転を区別しないので影響しません
- **ジャイロの範囲は ±500°/s** です。それより速くひねると振り切れて、形が崩れます
- LED の指向角は 30° なので、送信中に送信機を大きく傾けると受信が途切れます。**ストロークを描き終えたら受信機の方へ向けたまま止める**のが確実です
- ATtiny85 の内蔵発振器は個体差があります。受信が不安定なら `#stats` の `crc_err` と `dropped` を見て、距離や向きを調整し、それでもだめなら OSCCAL で校正してください
- 送信中（最大約 3.3 秒）は IMU を読んでいないので、その間の動きは記録されません

## Flash / RAM の使用量（ATtiny85）

| | 使用量 | 上限 |
|---|---|---|
| Flash | 約 5.3KB (64%) | 8KB（ATtiny45 の 4KB には入らない） |
| RAM（グローバル変数） | 324 バイト (63%) | 512 バイト |

小さく収めるために、送信機では次のことをしています。

- **浮動小数点を使わない**。ジャイロの生値を int32 のまま積分します（float ライブラリだけで 1.5KB 以上あるため）
- **Wire ライブラリを使わない**。数十行のソフトウェア I2C でジャイロの 6 バイトだけを読みます
- クォータニオンの積やループは使い回せる形にして、32 ビットの計算のコードを増やさないようにしています（それでも約 2KB 増えました）
- `digitalWrite` / `pinMode` を使わず、レジスタを直接操作します

点は 1 点 2 バイト（差分 × 2 軸）でためるので、4 秒 (100 点) でも 200 バイトで収まります。

## テスト

```
cd python
python -m unittest
```

`python/tests/test_protocol.py` では、送信機 (C++) を PC 上でシミュレートして得た実際の送信フレームを Python 版で組み立てて、受信機 (C++) と同じ結果になることも確かめています。

## ライセンス

[MIT License](LICENSE) © 2026 yuzujelly2222

- [ir-imu-protocol](https://github.com/yuzujelly2222/ir-imu-protocol) も MIT License です
- 依存している [dollar_one_recognizer_python](https://github.com/yuzujelly2222/dollar_one_recognizer_python) は New BSD License です。$1 Unistroke Recognizer の原典は Wobbrock, Wilson, Li (UIST '07) です
