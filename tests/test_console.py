import os
import subprocess
import sys
import unittest
from pathlib import Path

from countersign.llm import LLMUnavailable, pinned_provider

ROOT = Path(__file__).resolve().parents[1]


class ConsoleTests(unittest.TestCase):
    def test_a_reply_with_a_narrow_no_break_space_prints_through_a_windows_pipe(self):
        # the exact failure from a real run: cp1252 cannot encode U+202F
        code = (
            "import sys\n"
            "sys.stdout.reconfigure(errors='replace')\n"
            "print('You should see $9.50\\u202fshortly. \\u2011 done')\n"
        )
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        env.pop("PYTHONUTF8", None)
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr.decode(errors="replace"))
        self.assertIn(b"shortly", done.stdout)

    def test_without_the_setting_that_same_print_does_crash(self):
        code = "print('a\\u202fb')\n"
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env)
        self.assertNotEqual(done.returncode, 0)

    def test_the_runner_sets_it(self):
        self.assertIn('sys.stdout.reconfigure(errors="replace")', (ROOT / "scripts" / "run_inbox.py").read_text(encoding="utf-8"))


class PinnedProviderTests(unittest.TestCase):
    def test_a_provider_is_found_from_its_key_alone(self):
        p = pinned_provider("cerebras/gpt-oss-120b", {"CEREBRAS_API_KEY": "k"})
        self.assertEqual((p.name, p.models, p.key), ("cerebras", ["gpt-oss-120b"], "k"))
        self.assertTrue(p.base_url.startswith("https://api.cerebras.ai"))

    def test_a_model_name_may_contain_slashes(self):
        self.assertEqual(pinned_provider("groq/openai/gpt-oss-120b", {"GROQ_API_KEY": "k"}).models, ["openai/gpt-oss-120b"])

    def test_the_error_says_what_is_wrong(self):
        for spec, env, words in (("cerebras/x", {}, "CEREBRAS_API_KEY is missing"),
                                 ("nope/x", {"NOPE_API_KEY": "k"}, "provider/model"),
                                 ("groq", {"GROQ_API_KEY": "k"}, "provider/model")):
            with self.assertRaises(LLMUnavailable) as cm:
                pinned_provider(spec, env)
            self.assertIn(words, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
