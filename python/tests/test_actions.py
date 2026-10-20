# python -m unittest  (python/ ディレクトリで実行)
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from magic_wand.actions import Action, GestureActions, load_function, parse_action
from magic_wand.gestures import GestureRecognizer, GestureResult
from magic_wand.templates import TEMPLATES

seen = []


def record(result, track):
    seen.append((result.name, track))


class ParseTest(unittest.TestCase):
    def test_kinds(self):
        a = parse_action("square@0.9=notepad.exe")
        self.assertEqual((a.gesture, a.threshold, a.kind, a.target), ("square", 0.9, "cmd", "notepad.exe"))
        self.assertEqual(parse_action("circle=lights.py --fast").kind, "py")
        self.assertEqual(parse_action("circle=cmd:echo {label}").target, "echo {label}")
        self.assertEqual(parse_action("*=open:chime.wav").kind, "open")
        a = parse_action("zigzag = tests.test_actions:record")
        self.assertEqual((a.kind, a.target, a.text), ("func", record, "tests.test_actions:record"))
        self.assertIsNone(a.threshold)

    def test_function_in_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "spells.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("def lights_on():\n    return 'ok'\n")
            a = parse_action(f"circle={path}:lights_on")  # Windows のドライブ名 (C:) があっても関数になる
            self.assertEqual((a.kind, a.target()), ("func", "ok"))
            self.assertEqual(parse_action(f"circle={path}").kind, "py")
            with self.assertRaises(ValueError):
                load_function(f"{path}:nope")

    def test_errors(self):
        for spec in ("circle", "=x", "circle@1.5=x", "circle@abc=x", "circle="):
            with self.assertRaises(ValueError, msg=spec):
                parse_action(spec)
        with self.assertRaises(ValueError):
            parse_action("nope=x", known=["circle"])
        self.assertEqual(parse_action("*=x", known=["circle"]).gesture, "*")


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.t = 0.0
        self.acts = GestureActions(GestureRecognizer(), clock=lambda: self.t)

    def test_threshold(self):
        hi = self.acts.add(Action("circle", "x", 0.95, "cmd"))
        lo = self.acts.add(Action("circle", "x", 0.5, "cmd"))
        default = self.acts.add(Action("circle", "x", None, "cmd"))
        anything = self.acts.add(Action("*", "x", None, "cmd"))
        sel = self.acts.select
        self.assertEqual(sel(GestureResult("circle", 0.97, True)), [hi, lo, default, anything])
        self.assertEqual(sel(GestureResult("circle", 0.85, True)), [lo, default, anything])
        # 判定のしきい値 (0.80) より下でも、Action のしきい値を超えていれば実行する
        self.assertEqual(sel(GestureResult("circle", 0.6, False, "low_score")), [lo])
        self.assertEqual(sel(GestureResult("circle", 0.99, False, "not_closed")), [])
        self.assertEqual(sel(GestureResult("square", 0.99, True)), [anything])
        self.assertEqual(sel(GestureResult(None, 0.0, False, "too_small")), [])

    def test_cooldown(self):
        a = self.acts.add(Action("circle", "x", None, "cmd", cooldown=2.0))
        r = GestureResult("circle", 0.9, True)
        self.assertEqual(self.acts.select(r), [a])
        self.t = 1.0
        self.assertEqual(self.acts.select(r), [])
        self.t = 2.5
        self.assertEqual(self.acts.select(r), [a])

    def test_handle_calls_function(self):
        got = []
        self.acts.on("circle", lambda: got.append("no args"))
        self.acts.on("circle", lambda r: got.append(r.name))

        @self.acts.on("circle", threshold=0.5)
        def both(r, track):
            got.append((r.name, track))

        r = self.acts.handle(TEMPLATES["circle"])
        self.acts.wait()
        self.assertEqual(r.name, "circle")
        self.assertEqual(got, ["no args", "circle", ("circle", TEMPLATES["circle"])])
        self.acts.handle(TEMPLATES["square"])
        self.acts.wait()
        self.assertEqual(len(got), 3)

    def test_error_does_not_stop(self):
        errors = []
        acts = GestureActions(GestureRecognizer(), on_error=lambda a, e: errors.append(str(e)))
        acts.on("circle", lambda: 1 / 0)
        ok = []
        acts.on("circle", lambda: ok.append(1))
        acts.handle(TEMPLATES["circle"])
        acts.wait()
        self.assertEqual((len(errors), ok), (1, [1]))

    def test_dry_run(self):
        acts = GestureActions(GestureRecognizer(), dry_run=True)
        a = acts.on("circle", "cmd:exit 1")
        with mock.patch("subprocess.Popen") as popen:
            self.assertEqual(acts.dispatch(GestureResult("circle", 0.9, True)), [a])
        popen.assert_not_called()

    def test_command_placeholders_and_env(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.txt")
            script = os.path.join(d, "hello.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write("import os, sys\n"
                        "open(sys.argv[1], 'w', encoding='utf-8').write("
                        "' '.join(sys.argv[2:] + [os.environ['MAGIC_WAND_LABEL']]))\n")
            self.acts.on("circle", f'"{script}" "{out}" {{gesture}} {{score}}', kind="py")
            # 起動だけして終わるのを待たないので、渡されたものを受け取って、ここで実行して待つ
            with mock.patch("subprocess.Popen") as popen:
                self.acts.dispatch(GestureResult("circle", 0.9, True))
            args = popen.call_args.args[0]
            self.assertEqual(args[0], sys.executable)
            subprocess.run(args, env=popen.call_args.kwargs["env"], check=True)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(f.read(), "circle 0.90 丸")


if __name__ == "__main__":
    unittest.main()
