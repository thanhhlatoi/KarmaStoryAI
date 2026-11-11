import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karma.__main__ import main
from karma.cli_loop import loop
from karma.cli_prep import prep
from karma.cli_score import CRITERIA, evaluate, parse_score, score_round
from karma.cli_skeleton import build
from karma.cli_write import write_round
from karma.common import atomic_write, save_json
from karma.llm import Completion
from karma.numbers import expand_numbers, integer_words
from tools.clean_srt import clean

PROJECT = Path(__file__).resolve().parent.parent


def grade(value=9, **overrides):
    criteria = dict.fromkeys(CRITERIA, value)
    criteria.update(overrides)
    return {"score": 10, "pass": True, "criteria": criteria, "fixes": ["Chapter 1: plant a fair clue."]}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("config.json", "rubric.md"):
            shutil.copy(PROJECT / name, self.root / name)
        shutil.copytree(PROJECT / "prompts", self.root / "prompts")
        self.environment = patch.dict(os.environ, {"KARMA_ROOT": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.folder = self.root / "stories" / "001"
        self.folder.mkdir(parents=True)
        atomic_write(self.folder / "skeleton.md", "A village, a debt, a fair twist.")
        # Kịch bản giả chỉ vài từ: nới thời lượng; độ dài được test riêng ở LengthTests.
        self.configure(target_minutes=[0.001, 1000])
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def configure(self, **updates):
        path = self.root / "config.json"
        data = json.loads(path.read_text())
        data.update(updates)
        save_json(path, data)


class LengthTests(Workspace):
    def setUp(self):
        super().setUp()
        self.configure(target_minutes=[30, 40], words_per_minute={"en": 150})

    def test_length_check_bounds(self):
        from karma.common import length_check
        self.assertTrue(length_check("word " * 5250, "en")["ok"])           # 35 phút
        short = length_check("## Chapter 1\n" + "word " * 3000, "en")     # 20 phút, bỏ dòng tiêu đề
        self.assertEqual((short["ok"], short["words"]), (False, 3000))
        self.assertIn("Viết thêm", short["fix"])
        self.assertIn("Cắt", length_check("word " * 7500, "en")["fix"])

    def test_long_script_fails_despite_high_score(self):
        atomic_write(self.folder / "en.round1.txt", "word " * 7500)       # 50 phút
        with patch("karma.llm.complete", return_value=json.dumps(grade(10))):
            result = score_round("001", "en", 1)
        self.assertFalse(result["pass"])
        self.assertEqual(result["length"]["minutes"], 50.0)
        self.assertTrue(result["fixes"][0].startswith("ĐỘ DÀI:"))

    def test_length_fix_reaches_next_round_prompt(self):
        prompts = []

        def fake(role, prompt):
            prompts.append(prompt)
            if role == "writer":
                return ("word " * (7500 if len(prompts) == 1 else 5250)) + "[[END_SCRIPT]]"
            return json.dumps(grade(9))

        with patch("karma.llm.complete", fake):
            result = loop("001", "en")
        self.assertTrue(result["pass"])
        self.assertIn("4,500–6,000 words", prompts[0])
        self.assertIn("ĐỘ DÀI:", prompts[2])

    def test_prep_rejects_final_with_wrong_length(self):
        script = "word " * 7500
        atomic_write(self.folder / "en.round1.txt", script)
        atomic_write(self.folder / "en.final.txt", script)
        save_json(self.folder / "en.round1.score.json", grade(10))
        with self.assertRaises(ValueError):
            prep("001", "en")

    def test_invalid_target_minutes(self):
        self.configure(target_minutes=[40, 30])
        with self.assertRaises(ValueError):
            from karma.common import config
            config()


class ScoreTests(Workspace):
    def test_json_wrappers(self):
        data = grade()
        for wrapper in ("{}", "```json\n{}\n```", "Lời dẫn {{không phải json}}\n{}\nHết."):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(parse_score(wrapper.format(json.dumps(data))), data)

    def test_missing_and_invalid_criteria(self):
        data = grade()
        del data["criteria"]["hook"]
        with self.assertRaisesRegex(ValueError, "6 tiêu chí"):
            evaluate(data)
        for value in (-1, 11, True, "9", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "0–10"):
                evaluate(grade(hook=value))
        with self.assertRaisesRegex(ValueError, "JSON hợp lệ"):
            parse_score("not JSON")

    def test_weighted_score_and_untrusted_pass(self):
        result = evaluate(grade(hook=5))
        self.assertAlmostEqual(result["score"], 8.2)
        self.assertFalse(result["pass"])
        self.assertTrue(evaluate(grade(8))["pass"])
        self.assertFalse(evaluate(grade(7))["pass"])

    def test_weights_come_from_rubric(self):
        rubric = self.root / "rubric.md"
        text = rubric.read_text().replace("| hook | 20%", "| hook | 30%").replace("| twist | 20%", "| twist | 10%")
        atomic_write(rubric, text)
        self.assertAlmostEqual(evaluate(grade(hook=5))["score"], 7.8)

    def test_raw_output_saved_and_cached(self):
        atomic_write(self.folder / "en.round1.txt", "A story.")
        with patch("karma.llm.complete", return_value="```json\n" + json.dumps(grade()) + "\n```") as model:
            self.assertTrue(score_round("001", "en", 1)["pass"])
            (self.folder / "en.round1.score.json").unlink()
            self.assertTrue(score_round("001", "en", 1)["pass"])
            self.assertEqual(model.call_count, 1)


class LoopTests(Workspace):
    def test_fail_then_pass_and_resume(self):
        responses = ["## Chapter 1\nFirst draft.\n[[END_SCRIPT]]", json.dumps(grade(7)),
                     "## Chapter 1\nBetter second draft.\n[[END_SCRIPT]]", json.dumps(grade(9))]
        with patch("karma.llm.complete", side_effect=responses) as model:
            loop("001", "en")
            self.assertEqual(model.call_count, 4)
            revision = model.call_args_list[2].args[1]
            self.assertIn("First draft.", revision)
            self.assertIn("plant a fair clue", revision)
        self.assertIn("Better second", (self.folder / "en.final.txt").read_text())
        self.assertFalse((self.folder / "en.NEEDS_REVIEW").exists())
        self.assertIn("hook", (self.folder / "report.md").read_text())
        with patch("karma.llm.complete", side_effect=AssertionError("Cache miss")):
            loop("001", "en")

    def test_best_failed_round_and_resume(self):
        self.configure(max_rounds=3)
        responses = []
        for index, score in enumerate((7.5, 7.8, 6), 1):
            responses += [f"Draft {index}. [[END_SCRIPT]]", json.dumps(grade(score))]
        with patch("karma.llm.complete", side_effect=responses):
            loop("001", "es")
        self.assertEqual((self.folder / "es.final.txt").read_text(), "Draft 2.\n")
        self.assertIn("vòng 2", (self.folder / "es.NEEDS_REVIEW").read_text())
        with patch("karma.llm.complete", side_effect=AssertionError("Cache miss")):
            loop("001", "es")
        with self.assertRaisesRegex(ValueError, "chưa đạt"):
            prep("001", "es")

    def test_interruption_after_write(self):
        with patch("karma.llm.complete", side_effect=["Draft. [[END_SCRIPT]]", RuntimeError("offline")]):
            with self.assertRaises(RuntimeError):
                loop("001", "de")
        with patch("karma.llm.complete", return_value=json.dumps(grade())) as model:
            loop("001", "de")
            self.assertEqual(model.call_count, 1)
            self.assertEqual(model.call_args.args[0], "scorer")

    def test_force_resets_selected_language(self):
        with patch("karma.llm.complete", side_effect=["Old. [[END_SCRIPT]]", json.dumps(grade())]):
            loop("001", "en")
        atomic_write(self.folder / "de.final.txt", "Keep me.")
        atomic_write(self.folder / "en.tts.txt", "Stale TTS.")
        with patch("karma.llm.complete", side_effect=["New. [[END_SCRIPT]]", json.dumps(grade())]):
            loop("001", "en", force=True)
        self.assertEqual((self.folder / "en.final.txt").read_text(), "New.\n")
        self.assertTrue((self.folder / "de.final.txt").exists())
        self.assertFalse((self.folder / "en.tts.txt").exists())


class PipelineTests(Workspace):
    def test_standalone_write_score_and_txt_clean(self):
        source = self.root / "source.txt"
        atomic_write(source, "Một truyện văn bản.\n")
        self.assertEqual(main(["clean", str(source), "--story", "002"]), 0)
        self.assertEqual((self.root / "stories/002/source.txt").read_text(), "Một truyện văn bản.\n")
        with patch("karma.llm.complete", side_effect=["A story. [[END_SCRIPT]]", json.dumps(grade())]):
            self.assertEqual(main(["write", "001", "--lang", "en", "--round", "1"]), 0)
            self.assertEqual(main(["score", "001", "--lang", "en", "--round", "1"]), 0)

    def test_cli_clean_skeleton_loop_all_prep(self):
        source = self.root / "x.srt"
        atomic_write(source, "1\n00:00:00,000 --> 00:00:01,000\nCâu chữ nguồn riêng tư.\n")

        def fake(role, prompt):
            if role == "scorer":
                return "Result:\n```json\n" + json.dumps(grade()) + "\n```"
            if "TRUYEN:" in prompt:
                return "A farmer makes a choice, faces consequences, and learns justice."
            self.assertNotIn("Câu chữ nguồn riêng tư", prompt)
            return "## Chapter 1\n" + "A quiet village had 21 houses. " * 30 + "\n[[END_SCRIPT]]"

        with patch("karma.llm.complete", side_effect=fake):
            for args in (["clean", str(source), "--story", "001"], ["skeleton", "001", "--force"],
                         ["loop", "001", "--lang", "all"]):
                self.assertEqual(main(args), 0)
            for lang in ("de", "en", "es"):
                self.assertEqual(main(["prep", "001", "--lang", lang]), 0)
                tts = (self.folder / f"{lang}.tts.txt").read_text()
                self.assertTrue(all(len(line) <= 400 for line in tts.splitlines()))
                self.assertNotRegex(tts, r"\d|#")
                scenes = json.loads((self.folder / f"{lang}.scenes.json").read_text())
                self.assertEqual(len(scenes), len(tts.splitlines()))
                self.assertEqual(scenes[0]["chapter"], 1)
                self.assertAlmostEqual(scenes[0]["estimated_seconds"], len(scenes[0]["paragraph"].split()) * .4)
        with patch("karma.llm.complete", side_effect=AssertionError("Cache miss")):
            self.assertEqual(main(["loop", "001", "--lang", "all"]), 0)

    def test_long_skeleton_chunks_and_resume(self):
        (self.folder / "skeleton.md").unlink()
        atomic_write(self.folder / "source.txt", "word " * 6001)
        with patch("karma.llm.complete", side_effect=["part1", "part2", RuntimeError("stopped")]):
            with self.assertRaises(RuntimeError):
                build("001")
        with patch("karma.llm.complete", side_effect=["part3", "merged"]) as model:
            build("001")
            self.assertEqual(model.call_count, 2)
        self.assertEqual((self.folder / "skeleton.md").read_text(), "merged\n")
        with patch("karma.llm.complete", side_effect=AssertionError("Cache miss")):
            build("001")

    def test_continuation_checkpoint(self):
        self.configure(max_continuations=1)
        with patch("karma.llm.complete", side_effect=[Completion("## Chapter 1\nAn unfinished", True), RuntimeError("stopped")]):
            with self.assertRaises(RuntimeError):
                write_round("001", "en", 1)
        self.assertFalse((self.folder / "en.round1.txt").exists())
        self.assertTrue((self.folder / "en.round1.draft.txt").exists())
        with patch("karma.llm.complete", return_value="sentence.\n## Chapter 2\nThe end. [[END_SCRIPT]]") as model:
            write_round("001", "en", 1)
            self.assertIn("An unfinished", model.call_args.args[1])
        self.assertIn("Chapter 2", (self.folder / "en.round1.txt").read_text())

    def test_prep_rejects_edited_final(self):
        atomic_write(self.folder / "en.final.txt", "Edited.")
        atomic_write(self.folder / "en.round1.txt", "Approved.")
        save_json(self.folder / "en.round1.score.json", grade())
        with self.assertRaisesRegex(ValueError, "tương ứng"):
            prep("001", "en")

    def test_number_languages(self):
        for lang, expected in (("en", "one hundred twenty-three"), ("de", "einhundertdreiundzwanzig"), ("es", "ciento veintitrés")):
            self.assertEqual(integer_words(123, lang), expected)
        self.assertEqual(expand_numbers("1,234.5%", "en"), "one thousand two hundred thirty-four point five percent")
        self.assertEqual(expand_numbers("1.234,5%", "es"), "mil doscientos treinta y cuatro coma cinco por ciento")
        self.assertEqual(integer_words(21000, "es"), "veintiún mil")


class CleanTests(unittest.TestCase):
    def test_existing_srt_behavior(self):
        source = ("1\r\n00:00:00,000 --> 00:00:01,000\r\n<b>Xin chào.</b>\r\n\r\n"
                  "2\r\n00:00:01,000 --> 00:00:02,000\r\nXin chào.\r\n[Nhạc]\r\nMột ngày.\r\n\r\n"
                  "3\r\n00:00:06.000 --> 00:00:07.000\r\nKết thúc.\r\n")
        self.assertEqual(clean(source), "Xin chào. Một ngày.\n\nKết thúc.")
        self.assertEqual(clean(source, gap=10), "Xin chào. Một ngày. Kết thúc.")
        self.assertEqual(clean("No subtitles."), "")


if __name__ == "__main__":
    unittest.main()
