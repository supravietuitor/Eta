"""Local tests for the redacted vision probe and release ledger boundary."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import vision_probe  # noqa: E402


class VisionProbeTests(unittest.TestCase):
    def test_normal_response_shapes(self) -> None:
        vision_probe.assert_probe_response(
            "chat_completions",
            {"choices": [{"message": {"content": "VISION_PROBE_OK"}}]},
        )
        vision_probe.assert_probe_response(
            "responses",
            {"output": [{"content": [{"text": "VISION_PROBE_OK"}]}]},
        )
        vision_probe.assert_probe_response(
            "anthropic",
            {"content": [{"type": "text", "text": "VISION_PROBE_OK"}]},
        )

    def test_malformed_shapes_are_protocol_failures(self) -> None:
        cases = [
            ("models", {"data": [{"id": None}]}),
            ("chat_completions", {"choices": [None]}),
            ("chat_completions", {"choices": [{"message": None}]}),
            ("chat_completions", {"choices": [{"message": {"content": None}}]}),
            ("responses", {"output": [{"content": [{"unexpected": "x"}]}]}),
            ("anthropic", {"content": [{"text": None}]}),
        ]
        for protocol, response in cases:
            with self.subTest(protocol=protocol, response=response):
                with self.assertRaises(vision_probe.ProbeFailure) as raised:
                    if protocol == "models":
                        vision_probe.model_ids(response)
                    else:
                        vision_probe.assert_probe_response(protocol, response)
                self.assertEqual(raised.exception.category, "protocol_error")

    def test_malformed_models_are_reported_as_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.b64"
            fixture.write_text(base64.b64encode(b"png-bytes").decode("ascii"), encoding="ascii")
            with patch.object(vision_probe, "request_json", return_value={"data": [{"id": None}]}):
                output = io.StringIO()
                with patch.object(
                    sys,
                    "argv",
                    [
                        "vision_probe.py",
                        "--base-url",
                        "http://127.0.0.1",
                        "--models",
                        "vision-model",
                        "--protocols",
                        "chat_completions",
                        "--fixture",
                        str(fixture),
                    ],
                ), contextlib.redirect_stdout(output):
                    result = vision_probe.main()
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue().strip(), "FAIL category=protocol_error")

    def test_content_assertion_category(self) -> None:
        with self.assertRaises(vision_probe.ProbeFailure) as raised:
            vision_probe.assert_probe_response(
                "chat_completions",
                {"choices": [{"message": {"content": "different"}}]},
            )
        self.assertEqual(raised.exception.category, "content_assertion")

    def test_two_consistent_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.b64"
            fixture.write_text(base64.b64encode(b"png-bytes").decode("ascii"), encoding="ascii")
            responses = [
                {"data": [{"id": "vision-model"}]},
                {"choices": [{"message": {"content": "VISION_PROBE_OK"}}]},
                {"choices": [{"message": {"content": "VISION_PROBE_OK"}}]},
            ]
            with patch.object(vision_probe, "request_json", side_effect=responses):
                output = io.StringIO()
                with patch.object(
                    sys,
                    "argv",
                    [
                        "vision_probe.py",
                        "--base-url",
                        "http://127.0.0.1",
                        "--models",
                        "vision-model",
                        "--protocols",
                        "chat_completions",
                        "--fixture",
                        str(fixture),
                    ],
                ), contextlib.redirect_stdout(output):
                    result = vision_probe.main()
        self.assertEqual(result, 0)
        self.assertIn("PASS target=vision-model/chat_completions attempts=PASS,PASS", output.getvalue())

    def test_error_categories_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.b64"
            fixture.write_text(base64.b64encode(b"png-bytes").decode("ascii"), encoding="ascii")
            with patch.object(
                vision_probe,
                "request_json",
                side_effect=vision_probe.ProbeFailure("authentication"),
            ):
                output = io.StringIO()
                with patch.object(
                    sys,
                    "argv",
                    [
                        "vision_probe.py",
                        "--base-url",
                        "http://127.0.0.1",
                        "--models",
                        "vision-model",
                        "--protocols",
                        "chat_completions",
                        "--fixture",
                        str(fixture),
                    ],
                ), contextlib.redirect_stdout(output):
                    result = vision_probe.main()
        self.assertEqual(result, 1)
        self.assertIn("FAIL category=authentication", output.getvalue())
        self.assertNotIn("Authorization", output.getvalue())
        self.assertNotIn("Bearer", output.getvalue())

    def test_ledger_boundary_is_initial_and_strict(self) -> None:
        ledger = json.loads((Path(__file__).parents[1] / "version-ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["releaseStatus"], "no_formal_release")
        self.assertIsNone(ledger["lastReleasedVersionName"])
        self.assertIsNone(ledger["lastReleasedVersionCode"])
        baseline = ledger["initialVersionBaseline"]["versionCode"]
        self.assertLess(baseline, 261)
        self.assertFalse(260 > 261)


if __name__ == "__main__":
    unittest.main()
