import base64
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


DEFAULT_TARGET = Path(__file__).resolve().parents[1] / "scripts" / "generate_image.py"
TARGET = Path(os.environ.get("RIGHT_CODE_CLIENT_UNDER_TEST", DEFAULT_TARGET))
SPEC = importlib.util.spec_from_file_location("right_code_generate_image", TARGET)
CLIENT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLIENT)


class RecoveringTransport:
    def __init__(self):
        self.calls = []

    def request_json(self, method, url, api_key, payload=None, stage="request"):
        self.calls.append((method, stage))
        if len(self.calls) == 1:
            raise CLIENT.RightCodeError("temporary TLS EOF")
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")
        return {"status": "completed", "data": [{"b64_json": encoded}]}


class FailingPollTransport:
    def __init__(self):
        self.calls = 0

    def request_json(self, method, url, api_key, payload=None, stage="request"):
        self.calls += 1
        raise CLIENT.RightCodeError("temporary TLS EOF")


class FailingSubmitTransport:
    def __init__(self):
        self.calls = []

    def request_json(self, method, url, api_key, payload=None, stage="request"):
        self.calls.append((method, stage))
        raise CLIENT.RightCodeError("submit failed")


class CompletedSubmitTransport:
    def request_json(self, method, url, api_key, payload=None, stage="request"):
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")
        return {
            "task_id": "task-new",
            "status": "completed",
            "data": [{"b64_json": encoded}],
        }


class RightCodeEndpointTests(unittest.TestCase):
    def test_uses_rightapi_submit_and_poll_endpoints(self):
        self.assertEqual(
            CLIENT.SUBMIT_URL,
            "https://www.rightapi.ai/draw/v1/images/generations",
        )
        self.assertEqual(
            CLIENT.TASK_URL,
            "https://www.rightapi.ai/v1/tasks/{task_id}",
        )
        self.assertIn("rightapi.ai", CLIENT.AUTHENTICATED_DOWNLOAD_HOSTS)


class RightCodeFilenameTests(unittest.TestCase):
    def test_layout_separates_image_prompt_and_task_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            (project / ".git").mkdir(parents=True)
            layout = CLIENT.resolve_layout(
                cwd=project,
                now=datetime(2026, 8, 23, 14, 25, 30),
                task_namespace="rightcode",
            )
            result = CLIENT.generate(
                api_key="test-key",
                payload={"model": "gpt-image-2", "prompt": "海报草案", "size": "16:9", "n": 1, "async": True},
                output_dir=layout.images_dir,
                task_dir=layout.task_dir,
                layout=layout,
                poll_interval=0,
                timeout=30,
                transport=CompletedSubmitTransport(),
                sleep=lambda _: None,
                monotonic=lambda: 0,
            )
            image = Path(result["files"][0])
            self.assertEqual(image.name, "20260823-142530-001-海报草案.png")
            self.assertTrue((layout.prompts_dir / "20260823-142530-001-海报草案.md").is_file())
            self.assertTrue((layout.task_dir / "right-code-task-task-new.json").is_file())

    def test_new_task_derives_filename_from_prompt(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                CLIENT.time, "strftime", return_value="20260805-091530"
            ):
                result = CLIENT.generate(
                    api_key="test-key",
                    payload={
                        "model": "gpt-image-2",
                        "prompt": "一只可爱的太空猫，电影质感",
                        "n": 1,
                        "async": True,
                    },
                    output_dir=Path(temporary),
                    poll_interval=0,
                    timeout=30,
                    transport=CompletedSubmitTransport(),
                    sleep=lambda _: None,
                    monotonic=lambda: 0,
                )

            self.assertEqual(
                Path(result["files"][0]).name,
                "一只可爱的太空猫-电影质感-20260805-091530-1.png",
            )
            checkpoint = json.loads(Path(result["checkpoint"]).read_text())
            self.assertEqual(checkpoint["filename_stem"], "一只可爱的太空猫-电影质感")

    def test_uses_readable_prompt_name_and_increments_duplicates(self):
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")
        values = [
            ("base64", encoded, "image/png"),
            ("base64", encoded, "image/png"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                CLIENT.time, "strftime", return_value="20260805-091530"
            ):
                files = CLIENT._save_results(
                    values=values,
                    task_id="task-daf57efd7c9c4dfaaa232a3a20e2f1e1",
                    output_dir=Path(temporary),
                    api_key="test-key",
                    transport=object(),
                    filename_stem="一只可爱的猫咪，穿着宇航服 / 测试.png",
                )

            self.assertEqual(
                [Path(path).name for path in files],
                [
                    "一只可爱的猫咪-穿着宇航服-测试-20260805-091530-1.png",
                    "一只可爱的猫咪-穿着宇航服-测试-20260805-091530-2.png",
                ],
            )

    def test_resume_reuses_filename_saved_in_checkpoint(self):
        transport = RecoveringTransport()
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            CLIENT._write_checkpoint(
                output_dir,
                "task-existing",
                "submitted",
                "gpt-image-2",
                filename_stem="太空猫",
            )
            with mock.patch.object(
                CLIENT.time, "strftime", return_value="20260805-091530"
            ):
                result = CLIENT.resume_task(
                    api_key="test-key",
                    task_id="task-existing",
                    output_dir=output_dir,
                    poll_interval=0,
                    timeout=30,
                    poll_retries=2,
                    transport=transport,
                    sleep=lambda _: None,
                    monotonic=lambda: 0,
                )

            self.assertEqual(
                Path(result["files"][0]).name,
                "太空猫-20260805-091530-1.png",
            )

    def test_cli_accepts_custom_filename(self):
        args = CLIENT.parse_args(["--prompt", "cat", "--filename", "太空猫.png"])
        self.assertEqual(args.filename, "太空猫.png")


class RightCodeRecoveryTests(unittest.TestCase):
    def test_resume_retries_poll_without_posting_and_downloads_result(self):
        transport = RecoveringTransport()
        sleeps = []
        with tempfile.TemporaryDirectory() as temporary:
            result = CLIENT.resume_task(
                api_key="test-key",
                task_id="task-existing",
                output_dir=Path(temporary),
                poll_interval=0,
                timeout=30,
                poll_retries=2,
                transport=transport,
                sleep=sleeps.append,
                monotonic=lambda: 0,
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(transport.calls, [("GET", "poll"), ("GET", "poll")])
            self.assertEqual(sleeps, [0, 1.0])
            self.assertEqual(len(result["files"]), 1)
            self.assertTrue(Path(result["files"][0]).is_file())
            checkpoint = json.loads(Path(result["checkpoint"]).read_text())
            self.assertEqual(checkpoint["status"], "completed")

    def test_poll_exhaustion_writes_traceable_checkpoint(self):
        transport = FailingPollTransport()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(CLIENT.RightCodeError, "checkpoint"):
                CLIENT.resume_task(
                    api_key="test-key",
                    task_id="task-existing",
                    output_dir=Path(temporary),
                    poll_interval=0,
                    timeout=30,
                    poll_retries=2,
                    transport=transport,
                    sleep=lambda _: None,
                    monotonic=lambda: 0,
                )

            self.assertEqual(transport.calls, 3)
            checkpoint_path = Path(temporary) / "right-code-task-task-existing.json"
            checkpoint = json.loads(checkpoint_path.read_text())
            self.assertEqual(checkpoint["status"], "poll_error")
            self.assertEqual(checkpoint["attempts"], 3)

    def test_submit_failure_is_never_retried(self):
        transport = FailingSubmitTransport()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(CLIENT.RightCodeError, "submit failed"):
                CLIENT.generate(
                    api_key="test-key",
                    payload={"model": "gpt-image-2", "n": 1, "async": True},
                    output_dir=Path(temporary),
                    poll_interval=0,
                    timeout=30,
                    poll_retries=5,
                    transport=transport,
                    sleep=lambda _: None,
                    monotonic=lambda: 0,
                )

            self.assertEqual(transport.calls, [("POST", "submit")])

    def test_resume_cli_does_not_require_prompt(self):
        args = CLIENT.parse_args(["--resume-task-id", "task-existing"])
        self.assertEqual(args.resume_task_id, "task-existing")
        self.assertIsNone(args.prompt)


if __name__ == "__main__":
    unittest.main()
