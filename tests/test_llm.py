import io
import json
import subprocess
import os
from pathlib import Path
from unittest.mock import patch

from karma import llm
from .test_pipeline import Workspace


class LLMTests(Workspace):
    def test_codex_router_private_key_and_output(self):
        credentials = self.root / "credentials.json"
        credentials.write_text(json.dumps({"base_url": "http://localhost:9999/v1",
                                           "api_key": "PRIVATE_KEY", "model": "fake"}))
        self.configure(llm={"writer": {"type": "codex_router",
            "credentials_file": str(credentials), "attempts": 1}})
        def run(command, **kwargs):
            self.assertNotIn("PRIVATE_KEY", " ".join(command))
            self.assertEqual(kwargs["env"]["KARMA_CODEX_ROUTER_KEY"], "PRIVATE_KEY")
            self.assertEqual(kwargs["input"], "PRIVATE_PROMPT")
            self.assertIn('model_providers.karma_router.wire_api="responses"', command)
            Path(command[command.index("-o") + 1]).write_text("Kịch bản sạch")
            return subprocess.CompletedProcess(command, 0, "CLI banner", "progress")
        with patch("karma.llm.subprocess.run", side_effect=run):
            self.assertEqual(llm.complete("writer", "PRIVATE_PROMPT"), "Kịch bản sạch")
        self.assertNotIn("PRIVATE_KEY", (self.root / "work/llm.log").read_text())
        self.assertNotIn("KARMA_CODEX_ROUTER_KEY", os.environ)

    def test_local_configuration_overrides_output_directory(self):
        (self.root / "config.local.json").write_text(json.dumps({"stories_dir": "/tmp/nas-test"}))
        from karma.common import config
        self.assertEqual(config()["stories_dir"], "/tmp/nas-test")

    def test_cli_stdin_and_private_log(self):
        response = subprocess.CompletedProcess(["fake"], 0, "Output", "")
        with patch("karma.llm.subprocess.run", return_value=response) as command:
            self.assertEqual(llm.complete("writer", "PRIVATE SOURCE"), "Output")
            self.assertEqual(command.call_args.kwargs["input"], "PRIVATE SOURCE")
            self.assertEqual(command.call_args.kwargs["timeout"], 300)
        log = (self.root / "work/llm.log").read_text()
        self.assertNotIn("PRIVATE SOURCE", log)
        self.assertTrue(json.loads(log)["success"])

    def test_retry_and_redaction(self):
        bad = subprocess.CompletedProcess(["fake"], 1, "", "SECRET API KEY")
        with patch("karma.llm.subprocess.run", return_value=bad) as command, patch("karma.llm.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "sau 3 lần") as error:
                llm.complete("scorer", "PRIVATE SOURCE")
            self.assertEqual(command.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertNotIn("SECRET", str(error.exception))
        self.assertNotIn("SECRET", (self.root / "work/llm.log").read_text())

    def test_openai_environment_and_truncation(self):
        self.configure(llm={"writer": {"type": "openai", "base_url_env": "TEST_URL", "key_env": "TEST_KEY", "model_env": "TEST_MODEL"}})
        payload = {"choices": [{"message": {"content": "Partial"}, "finish_reason": "length"}]}
        with patch.dict("os.environ", {"TEST_URL": "http://localhost:9999/v1", "TEST_KEY": "secret", "TEST_MODEL": "fake"}), patch("karma.llm.urllib.request.urlopen") as request:
            request.return_value.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
            result = llm.complete("writer", "Hello")
            self.assertTrue(result.truncated)
            sent = request.call_args.args[0]
            self.assertEqual(sent.full_url, "http://localhost:9999/v1/chat/completions")
            self.assertEqual(json.loads(sent.data)["model"], "fake")
