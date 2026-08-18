"""Validate release metadata without printing credentials or API response bodies."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    root = Path(__file__).parents[2]
    ledger = json.loads((root / ".github/version-ledger.json").read_text(encoding="utf-8"))
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    application_id = re.search(r'applicationId\s*=\s*"([^"]+)"', gradle)
    version_name = re.search(r'versionName\s*=\s*"([^"]+)"', gradle)
    version_code = re.search(r"versionCode\s*=\s*(\d+)", gradle)
    if not application_id or application_id.group(1) != ledger["applicationId"]:
        return fail("application_id_mismatch")
    if not version_name or not version_code:
        return fail("version_metadata_missing")
    current_code = int(version_code.group(1))
    if current_code <= int(ledger["lastReleasedVersionCode"]):
        return fail("version_code_not_strictly_increasing")
    tag = f"v{version_name.group(1)}"
    existing = subprocess.run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"], capture_output=True, text=True, check=False)
    if existing.stdout.strip():
        return fail("tag_not_unique")
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repository:
        return fail("github_context_missing")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/workflows/android-ci.yml/runs?branch=main&status=success&per_page=1",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read())
    except Exception:
        return fail("main_ci_lookup_failed")
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    if not runs or runs[0].get("head_branch") != "main":
        return fail("main_ci_not_successful")
    print(f"PASS application_id={application_id.group(1)} version_name={version_name.group(1)} version_code={current_code} tag={tag} main_ci=success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
