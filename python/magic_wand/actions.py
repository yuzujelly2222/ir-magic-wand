# actions.py — 「このジェスチャーを、このスコア以上で描いたら、これを実行する」を決める
# SPDX-License-Identifier: MIT  Copyright (c) 2026 yuzujelly2222
#
# コマンドラインでは --on で指定する (何度でも書ける):
#
#   python -m magic_wand gestures COM3 \
#       --on circle=lights.py                  丸        → Python のファイルを実行
#       --on square@0.9=notepad.exe            四角 0.9 以上 → プログラム (コマンド) を実行
#       --on zigzag=mymod:on_zigzag            Z        → 関数を呼ぶ (モジュール名:関数名)
#       --on check=tools/spells.py:check       チェック → ファイルの中の関数を呼ぶ
#       --on wave="cmd:echo {label} {score}"     → シェルのコマンド
#       --on "*=open:chime.wav"                どれでも  → ファイルを関連付けられたアプリで開く
#
# 書き方: ジェスチャー名[@しきい値]=実行するもの
#   ジェスチャー名  TEMPLATES の名前 (circle, square, ...)。* はどのジェスチャーでも
#   しきい値        このスコア以上で実行する (省略すると GestureRecognizer の threshold)。
#                   判定のしきい値より低くしてもよい (そのジェスチャーにだけ甘くする)
#   実行するもの    先頭に種類を書くと、その種類として扱う:
#                     func:モジュール:関数 / func:ファイル.py:関数   関数を呼ぶ
#                     py:ファイル.py [引数...]                       Python で実行する
#                     cmd:コマンド                                   シェルで実行する
#                     open:ファイル                                  関連付けられたアプリで開く
#                   書かなければ形から決める:
#                     xxx.py:関数 / パッケージ.モジュール:関数 → func
#                     xxx.py [引数...]                        → py
#                     存在するファイル                         → open (Windows) / 実行 (実行権限あり)
#                     それ以外                                 → cmd
#
# コマンドと引数の中の {gesture} {label} {score} {id} は、判定結果に置き換わる。
# 実行するプログラムには環境変数 MAGIC_WAND_GESTURE / _LABEL / _SCORE / _STROKE_ID も渡す。
# 関数は f() / f(result) / f(result, track) のどれでもよい (受け取れる数だけ渡す)。
#
# Python から使う場合:
#   actions = GestureActions(recognizer)
#   actions.on("square", "notepad.exe", threshold=0.9)
#   @actions.on("circle")
#   def lights(result, track): ...
#   reader = SerialXZReader("COM3", projector=PointerProjector(), on_stroke=actions.handle)
from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Union

if TYPE_CHECKING:  # gestures.py がこのモジュールを使うので、実行時には import しない
    from .gestures import GestureRecognizer, GestureResult
    from .track import XZTrack

ANY = "*"
KINDS = ("func", "py", "cmd", "open")

_SPEC = re.compile(r"^\s*(?P<name>[^=@\s]+)\s*(?:@\s*(?P<th>[0-9.]+)\s*)?=(?P<target>.+)$", re.S)
_FUNC = re.compile(r"^(?P<src>.+\.py|[A-Za-z_][\w.]*):(?P<func>[A-Za-z_]\w*)$")

Target = Union[str, Callable[..., object]]


@dataclass
class Action:
    gesture: str                       # ジェスチャー名 (* はどれでも)
    target: Target                     # 実行するもの (文字列か関数)
    threshold: Optional[float] = None  # None なら判定のしきい値
    kind: str = "func"                 # func / py / cmd / open
    cooldown: float = 0.0              # 実行してからこの秒数は、同じ Action を実行しない
    desc: str = ""                     # 表示用の説明 (省略すると target から作る)
    _last: float = field(default=-1e9, repr=False, compare=False)

    @property
    def text(self) -> str:
        """表示用の短い説明。"""
        if self.desc:
            return self.desc
        if callable(self.target):
            return f"{getattr(self.target, '__module__', '?')}.{getattr(self.target, '__name__', '?')}()"
        return str(self.target)

    def matches(self, r: GestureResult, default_threshold: float) -> bool:
        if r.name is None or self.gesture not in (ANY, r.name):
            return False
        # しきい値より下で落とされたものも、この Action のしきい値を超えていれば実行する。
        # 「小さすぎ」「閉じていない」などで落とされたものは実行しない
        if not (r.accepted or r.reason == "low_score"):
            return False
        th = default_threshold if self.threshold is None else self.threshold
        return r.score >= th


# ---------------------------------------------------------------- 文字列からの組み立て
def parse_action(spec: str, cooldown: float = 0.0, known: Optional[List[str]] = None) -> Action:
    """'circle@0.9=lights.py' のような文字列を Action にする。関数はこの時点で読み込む。

    known: 使えるジェスチャー名 (指定すると、それ以外の名前はエラーにする)
    """
    m = _SPEC.match(spec)
    if not m:
        raise ValueError(f"--on の書き方が違います: {spec!r} (例: circle=lights.py, square@0.9=notepad.exe)")
    name, th, target = m["name"], m["th"], m["target"].strip()
    if known is not None and name != ANY and name not in known:
        raise ValueError(f"知らないジェスチャー: {name!r} (使えるもの: {', '.join(known)}, *)")
    threshold = None
    if th is not None:
        threshold = float(th)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"しきい値は 0〜1 で指定してください: {spec!r}")
    if not target:
        raise ValueError(f"実行するものがありません: {spec!r}")

    kind, body = _split_kind(target)
    if kind == "func":
        return Action(name, load_function(body), threshold, "func", cooldown, body)
    return Action(name, body, threshold, kind, cooldown)


def _split_kind(target: str):
    head, sep, rest = target.partition(":")
    if sep and head in KINDS:
        return head, rest.strip()
    if _FUNC.match(target):
        return "func", target
    first = _split_args(target)[0] if target.strip() else ""
    if first.lower().endswith(".py"):
        return "py", target
    if os.path.isfile(target):
        return "open", target
    return "cmd", target


def load_function(ref: str) -> Callable[..., object]:
    """'モジュール:関数' か 'ファイル.py:関数' から関数を読み込む。"""
    m = _FUNC.match(ref)
    if not m:
        raise ValueError(f"関数の指定が違います: {ref!r} (例: mymod:func, spells.py:func)")
    src, fname = m["src"], m["func"]
    if src.endswith(".py"):
        path = os.path.abspath(src)
        if not os.path.isfile(path):
            raise ValueError(f"ファイルがありません: {src}")
        mod_name = "_magic_wand_action_" + re.sub(r"\W", "_", path)
        spec = importlib.util.spec_from_file_location(mod_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    else:
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())
        module = importlib.import_module(src)
    fn = getattr(module, fname, None)
    if not callable(fn):
        raise ValueError(f"{src} に関数 {fname} がありません")
    return fn


def _split_args(s: str) -> List[str]:
    if os.name != "nt":
        return shlex.split(s)
    out = shlex.split(s, posix=False)
    return [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in out]


# ---------------------------------------------------------------- 実行
class GestureActions:
    """判定結果に合う Action を実行する。

    関数は 1 本の作業スレッドで順に呼ぶ (受信を止めないように)。
    プログラムは起動するだけで終わるのを待たない。
    """

    def __init__(self, recognizer: Optional[GestureRecognizer] = None,
                 actions: Optional[List[Action]] = None, dry_run: bool = False,
                 on_error: Optional[Callable[[Action, BaseException], None]] = None,
                 clock: Callable[[], float] = time.monotonic):
        """
        recognizer: handle() で使う判定器 (dispatch() だけ使うなら不要)
        actions:    最初から登録しておく Action
        dry_run:    実行せずに、実行したことにする (確かめる用)
        on_error:   実行に失敗したときに呼ぶ関数 f(action, error)。既定は標準エラーに出す
        """
        self.recognizer = recognizer
        self.actions: List[Action] = list(actions or [])
        self.dry_run = dry_run
        self.on_error = on_error or _print_error
        self._clock = clock
        self._queue: "queue.Queue" = queue.Queue()
        self._worker: Optional[threading.Thread] = None

    @property
    def threshold(self) -> float:
        return self.recognizer.threshold if self.recognizer is not None else 0.8

    def add(self, action: Action) -> Action:
        self.actions.append(action)
        return action

    def on(self, gesture: str, target: Optional[Target] = None, threshold: Optional[float] = None,
           kind: Optional[str] = None, cooldown: float = 0.0):
        """Action を登録する。target を省略するとデコレータになる。

        target が文字列なら --on の右辺と同じ書き方 (func:/py:/cmd:/open: も使える)。
        """
        if target is None:
            def deco(fn):
                self.on(gesture, fn, threshold, kind, cooldown)
                return fn
            return deco
        if callable(target):
            return self.add(Action(gesture, target, threshold, "func", cooldown))
        if kind is None:
            kind, target = _split_kind(target)
        if kind == "func":
            return self.add(Action(gesture, load_function(target), threshold, "func", cooldown, target))
        if kind not in KINDS:
            raise ValueError(f"kind は {KINDS} のどれか: {kind!r}")
        return self.add(Action(gesture, target, threshold, kind, cooldown))

    def handle(self, track: XZTrack) -> GestureResult:
        """判定して、合う Action を実行する (SerialXZReader の on_stroke にそのまま渡せる)。"""
        if self.recognizer is None:
            raise RuntimeError("handle() には recognizer が必要です")
        r = self.recognizer.recognize(track)
        self.dispatch(r, track)
        return r

    __call__ = handle

    def dispatch(self, r: GestureResult, track: Optional[XZTrack] = None) -> List[Action]:
        """判定結果に合う Action を実行して、実行したもののリストを返す。"""
        fired = self.select(r)
        self.run(fired, r, track)
        return fired

    def select(self, r: GestureResult) -> List[Action]:
        """判定結果に合う Action を選ぶ (cooldown の時刻はここで進める)。実行は run()。"""
        now = self._clock()
        fired = []
        for a in self.actions:
            if a.matches(r, self.threshold) and now - a._last >= a.cooldown:
                a._last = now
                fired.append(a)
        return fired

    def run(self, actions: List[Action], r: GestureResult, track: Optional[XZTrack] = None) -> None:
        """select() で選んだ Action を実行する (dry_run なら何もしない)。"""
        if self.dry_run:
            return
        for a in actions:
            self._run(a, r, track)

    def _run(self, a: Action, r: GestureResult, track: Optional[XZTrack]) -> None:
        try:
            if a.kind == "func":
                self._ensure_worker()
                self._queue.put((a, r, track))
            elif a.kind == "py":
                subprocess.Popen([sys.executable] + _split_args(_fill(a.target, r, track)),
                                 env=_env(r, track))
            elif a.kind == "cmd":
                subprocess.Popen(_fill(a.target, r, track), shell=True, env=_env(r, track))
            elif a.kind == "open":
                _open(_fill(a.target, r, track), _env(r, track))
        except Exception as e:  # 1 つ失敗しても受信は続ける
            self.on_error(a, e)

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work, daemon=True)
            self._worker.start()

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            a, r, track = item
            try:
                _call(a.target, r, track)
            except Exception as e:
                self.on_error(a, e)
            finally:
                self._queue.task_done()

    def wait(self) -> None:
        """登録した関数の実行が全部終わるまで待つ。"""
        self._queue.join()


def _call(fn: Callable[..., object], r: GestureResult, track: Optional[XZTrack]) -> object:
    args = (r, track)
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return fn(*args)
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return fn(*args)
    n = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
    return fn(*args[:n])


def _values(r: GestureResult, track: Optional[XZTrack]) -> Dict[str, str]:
    sid = "" if track is None or track.id is None else str(track.id)
    return {"gesture": r.name or "", "label": r.label, "score": f"{r.score:.2f}", "id": sid}


def _fill(s: str, r: GestureResult, track: Optional[XZTrack]) -> str:
    for k, v in _values(r, track).items():
        s = s.replace("{" + k + "}", v)
    return s


def _env(r: GestureResult, track: Optional[XZTrack]) -> Dict[str, str]:
    env = dict(os.environ)
    v = _values(r, track)
    env.update(MAGIC_WAND_GESTURE=v["gesture"], MAGIC_WAND_LABEL=v["label"],
               MAGIC_WAND_SCORE=v["score"], MAGIC_WAND_STROKE_ID=v["id"])
    return env


def _open(path: str, env: Dict[str, str]) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif os.access(path, os.X_OK) and not os.path.isdir(path):
        subprocess.Popen([os.path.abspath(path)], env=env)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path], env=env)


def _print_error(a: Action, e: BaseException) -> None:
    print(f"  ! {a.gesture} → {a.text} の実行に失敗: {e}", file=sys.stderr)
