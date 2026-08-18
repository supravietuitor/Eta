"""Run a redacted, deterministic visual probe against an OpenAI/Anthropic API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROBE_TEXT = "Inspect the attached image. Reply with exactly VISION_PROBE_OK."
PROBE_MARKER = "VISION_PROBE_OK"
PROTOCOLS = ("chat_completions", "responses", "anthropic")


class ProbeFailure(Exception):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def request_json(url: str, api_key: str, payload: dict[str, Any] | None) -> Any:
    try:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        raise ProbeFailure("protocol_error")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
            try:
                return json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise ProbeFailure("protocol_error") from exc
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ProbeFailure("authentication") from exc
        if exc.code in (402, 429):
            raise ProbeFailure("quota") from exc
        if exc.code == 404:
            raise ProbeFailure("routing") from exc
        raise ProbeFailure("protocol_error") from exc
    except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as exc:
        if isinstance(exc, urllib.error.URLError) and not isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise ProbeFailure("routing") from exc
        raise ProbeFailure("timeout") from exc


def url_join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def model_ids(models_payload: Any) -> set[str]:
    if not isinstance(models_payload, dict) or not isinstance(models_payload.get("data"), list):
        raise ProbeFailure("protocol_error")
    if not models_payload["data"] or not all(isinstance(item, dict) for item in models_payload["data"]):
        raise ProbeFailure("protocol_error")
    ids = {item.get("id") for item in models_payload["data"]}
    if not ids or not all(isinstance(item, str) and bool(item) for item in ids):
        raise ProbeFailure("protocol_error")
    return ids


def text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        if not value:
            raise ProbeFailure("protocol_error")
        result: list[str] = []
        for item in value:
            result.extend(text_fragments(item))
        return result
    if isinstance(value, dict):
        result = []
        found = False
        for key in ("text", "content", "output_text"):
            if key in value:
                found = True
                result.extend(text_fragments(value[key]))
        if not found:
            raise ProbeFailure("protocol_error")
        return result
    raise ProbeFailure("protocol_error")


def assert_probe_response(protocol: str, response: Any) -> None:
    if not isinstance(response, dict):
        raise ProbeFailure("protocol_error")
    if protocol == "chat_completions":
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not all(isinstance(item, dict) for item in choices):
            raise ProbeFailure("protocol_error")
        message = choices[0].get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise ProbeFailure("protocol_error")
        fragments = text_fragments(message["content"])
    elif protocol == "responses":
        if "output" not in response:
            raise ProbeFailure("protocol_error")
        fragments = text_fragments(response["output"])
    else:
        if "content" not in response:
            raise ProbeFailure("protocol_error")
        fragments = text_fragments(response["content"])
    if PROBE_MARKER not in "".join(fragments):
        raise ProbeFailure("content_assertion")


def probe_payload(protocol: str, model: str, image_data: str) -> tuple[str, dict[str, Any]]:
    data_url = f"data:image/png;base64,{image_data}"
    if protocol == "chat_completions":
        return "v1/chat/completions", {"model": model, "stream": False, "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROBE_TEXT}, {"type": "image_url", "image_url": {"url": data_url}}
        ]}]}
    if protocol == "responses":
        return "v1/responses", {"model": model, "stream": False, "input": [{"role": "user", "content": [
            {"type": "input_text", "text": PROBE_TEXT}, {"type": "input_image", "image_url": data_url}
        ]}]}
    return "v1/messages", {"model": model, "max_tokens": 64, "stream": False, "messages": [{"role": "user", "content": [
        {"type": "text", "text": PROBE_TEXT}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}}
    ]}]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--protocols", default=",".join(PROTOCOLS))
    parser.add_argument("--fixture", required=True)
    args = parser.parse_args()
    api_key = os.environ.get("ETA_VISION_API_KEY", "")
    requested = [item.strip() for item in args.models.split(",") if item.strip()]
    protocols = [item.strip() for item in args.protocols.split(",") if item.strip()]
    if not requested or not protocols or any(item not in PROTOCOLS for item in protocols):
        print("FAIL category=protocol_error")
        return 1
    try:
        image_bytes = base64.b64decode(Path(args.fixture).read_text(encoding="ascii"), validate=True)
        image_data = base64.b64encode(image_bytes).decode("ascii")
        available = model_ids(request_json(url_join(args.base_url, "v1/models"), api_key, None))
    except ProbeFailure as failure:
        print(f"FAIL category={failure.category}")
        return 1
    except (OSError, ValueError):
        print("FAIL category=protocol_error")
        return 1
    missing = [model for model in requested if model not in available]
    if missing:
        print(f"FAIL category=model_missing count={len(missing)}")
        return 1
    counts: dict[str, int] = {}
    for model in requested:
        for protocol in protocols:
            categories: list[str] = []
            for _ in range(2):
                try:
                    path, payload = probe_payload(protocol, model, image_data)
                    assert_probe_response(protocol, request_json(url_join(args.base_url, path), api_key, payload))
                    categories.append("PASS")
                except ProbeFailure as failure:
                    categories.append(failure.category)
            key = f"{model}/{protocol}"
            if categories != ["PASS", "PASS"]:
                print(f"FAIL target={key} attempts={','.join(categories)}")
                counts["failed"] = counts.get("failed", 0) + 1
            else:
                print(f"PASS target={key} attempts=PASS,PASS")
                counts["passed"] = counts.get("passed", 0) + 1
    if counts.get("failed"):
        return 1
    print(f"SUMMARY passed={counts.get('passed', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
