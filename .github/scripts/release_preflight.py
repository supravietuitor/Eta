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


def comparison_version_code(ledger: object) -> int | None:
    if not isinstance(ledger, dict):
        return None
    last_released = ledger.get("lastReleasedVersionCode")
    if last_released is not None:
        if isinstance(last_released, bool) or not isinstance(last_released, (int, str)):
            return None
        try:
            return int(last_released)
        except (TypeError, ValueError):
            return None
    baseline = ledger.get("initialVersionBaseline")
    if (
        not isinstance(baseline, dict)
        or isinstance(baseline.get("versionCode"), bool)
        or baseline.get("versionCode") != 0
    ):
        return None
    if ledger.get("releaseStatus") != "no_formal_release":
        return None
    return 0


def version_metadata(gradle: object) -> tuple[str, str, int] | None:
    if not isinstance(gradle, str):
        return None
    application_id = re.search(r'applicationId\s*=\s*"([^"]+)"', gradle)
    version_name = re.search(r'versionName\s*=\s*"([^"]+)"', gradle)
    version_code = re.search(r"versionCode\s*=\s*(\d+)", gradle)
    if not application_id or not version_name or not version_code:
        return None
    try:
        current_code = int(version_code.group(1))
    except (TypeError, ValueError):
        return None
    return application_id.group(1), version_name.group(1), current_code


def main() -> int:
    root = Path(__file__).parents[2]
    try:
        ledger = json.loads((root / ".github/version-ledger.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError):
        return fail("version_ledger_invalid")
    try:
        gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    except (OSError, UnicodeError, TypeError, ValueError):
        return fail("version_metadata_missing")
    metadata = version_metadata(gradle)
    if metadata is None:
        return fail("version_metadata_missing")
    application_id, version_name, current_code = metadata
    if not isinstance(ledger, dict) or not isinstance(ledger.get("applicationId"), str) or application_id != ledger.get("applicationId"):
        return fail("application_id_mismatch")
    comparison_code = comparison_version_code(ledger)
    if comparison_code is None:
        return fail("version_ledger_invalid")
    if current_code <= comparison_code:
        return fail("version_code_not_strictly_increasing")
    tag = f"v{version_name}"
    try:
        existing = subprocess.run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"], capture_output=True, text=True, check=False)
    except (OSError, TypeError, ValueError):
        return fail("tag_lookup_failed")
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
    except (OSError, TypeError, ValueError):
        return fail("main_ci_lookup_failed")
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    if not isinstance(runs, list) or not runs or not isinstance(runs[0], dict) or runs[0].get("head_branch") != "main":
        return fail("main_ci_not_successful")
    print(f"PASS application_id={application_id} version_name={version_name} version_code={current_code} tag={tag} main_ci=success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
