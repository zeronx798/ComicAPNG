"""Semantic validation for GitHub Actions build and release automation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.classify_release_tag import InvalidReleaseTag, classify_release_context

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / ".github/workflows/build.yml"

EXPECTED_MATRIX = {
    "Windows x64": (
        "windows-latest",
        "ComicAPNG-Windows-x64",
        "ComicAPNG-Windows-x64.zip",
    ),
    "Linux x64": (
        "ubuntu-22.04",
        "ComicAPNG-Linux-x64",
        "ComicAPNG-Linux-x64.tar.gz",
    ),
    "macOS Intel": (
        "macos-15-intel",
        "ComicAPNG-macOS-x64",
        "ComicAPNG-macOS-x64.zip",
    ),
    "macOS Apple Silicon": (
        "macos-latest",
        "ComicAPNG-macOS-arm64",
        "ComicAPNG-macOS-arm64.zip",
    ),
}


def _workflow() -> dict:
    value = yaml.load(WORKFLOW_PATH.read_text(encoding="ascii"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _can_publish(event_name: str, ref: str) -> bool:
    try:
        release_kind = classify_release_context(event_name, ref)
    except InvalidReleaseTag:
        return False
    return (
        event_name == "push"
        and ref.startswith("refs/tags/")
        and release_kind in {"stable", "rc"}
    )


def test_build_only_events_cannot_publish() -> None:
    assert classify_release_context("workflow_dispatch", "refs/heads/main") == "none"
    assert classify_release_context("workflow_dispatch", "refs/tags/v1.0.0") == "none"
    assert classify_release_context("push", "refs/heads/main") == "none"
    assert classify_release_context("pull_request", "refs/pull/12/merge") == "none"
    assert not _can_publish("workflow_dispatch", "refs/tags/v1.0.0")
    assert not _can_publish("push", "refs/heads/main")
    assert not _can_publish("pull_request", "refs/pull/12/merge")


def test_supported_tags_can_publish_with_explicit_release_kinds() -> None:
    assert classify_release_context("push", "refs/tags/v1.0.0") == "stable"
    assert classify_release_context("push", "refs/tags/v2.4.7") == "stable"
    assert classify_release_context("push", "refs/tags/v1.0.0-rc.1") == "rc"
    assert classify_release_context("push", "refs/tags/v2.3.1-rc.4") == "rc"
    assert _can_publish("push", "refs/tags/v1.0.0")
    assert _can_publish("push", "refs/tags/v1.0.0-rc.1")


@pytest.mark.parametrize(
    "tag",
    [
        "v1.0",
        "v1",
        "release-1.0.0",
        "v1.0.0-test",
        "v1.0.0-alpha",
        "v1.0.0-beta.1",
        "vfoo",
        "v1.0.0-foo",
    ],
)
def test_malformed_release_tags_fail_classification(tag: str) -> None:
    ref = f"refs/tags/{tag}"
    with pytest.raises(InvalidReleaseTag, match="Expected vX.Y.Z or vX.Y.Z-rc.N"):
        classify_release_context("push", ref)
    assert not _can_publish("push", ref)


def test_workflow_triggers_gating_and_permissions_are_safe() -> None:
    workflow = _workflow()
    triggers = workflow["on"]
    assert set(triggers) == {"workflow_dispatch", "push", "pull_request"}
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["push"]["tags"] == ["v*"]
    assert triggers["pull_request"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    assert "!startsWith(github.ref, 'refs/tags/')" in workflow["concurrency"][
        "cancel-in-progress"
    ]

    policy = workflow["jobs"]["release_policy"]
    build = workflow["jobs"]["build"]
    release = workflow["jobs"]["release"]
    write_jobs = {
        name
        for name, job in workflow["jobs"].items()
        if job.get("permissions", {}).get("contents") == "write"
    }
    assert write_jobs == {"release"}
    assert policy["permissions"] == {"contents": "read"}
    assert build["permissions"] == {"contents": "read"}
    assert release["permissions"] == {"contents": "write"}
    assert build["needs"] == ["release_policy"]
    assert set(release["needs"]) == {"release_policy", "build"}

    release_condition = " ".join(release["if"].split())
    assert "github.event_name == 'push'" in release_condition
    assert "startsWith(github.ref, 'refs/tags/')" in release_condition
    assert "release_kind == 'stable'" in release_condition
    assert "release_kind == 'rc'" in release_condition


def test_release_policy_classifies_early_and_checks_main_ancestry() -> None:
    policy = _workflow()["jobs"]["release_policy"]
    assert policy["outputs"]["release_kind"] == "${{ steps.classify.outputs.release_kind }}"
    scripts = "\n".join(step.get("run", "") for step in policy["steps"])
    assert "python scripts/classify_release_tag.py" in scripts
    assert "git merge-base --is-ancestor HEAD refs/remotes/origin/main" in scripts
    assert "The tag was not changed" in scripts


def test_workflow_builds_exactly_four_named_archives() -> None:
    workflow = _workflow()
    build = workflow["jobs"]["build"]
    entries = build["strategy"]["matrix"]["include"]
    actual = {
        entry["display_name"]: (
            entry["runner"],
            entry["artifact_name"],
            entry["archive_name"],
        )
        for entry in entries
    }
    assert actual == EXPECTED_MATRIX
    assert build["strategy"]["fail-fast"] == "false"

    uses = [step.get("uses") for step in build["steps"] if "uses" in step]
    assert "actions/checkout@v7" in uses
    assert "actions/setup-python@v7" in uses
    assert uses.count("actions/upload-artifact@v7") == 1
    scripts = "\n".join(step.get("run", "") for step in build["steps"])
    assert "python -m pytest" in scripts
    assert "python scripts/check_source_ascii.py" in scripts
    assert "python scripts/validate_packaging.py" in scripts
    assert "python scripts/validate_frozen_archive.py" in scripts
    upload = next(step for step in build["steps"] if step.get("uses") == "actions/upload-artifact@v7")
    assert upload["with"]["retention-days"] == "14"
    assert upload["with"]["if-no-files-found"] == "error"


def test_linux_qt_tests_install_runtime_dependencies_and_run_offscreen() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    dependency_step = next(step for step in steps if "apt-get install" in step.get("run", ""))
    assert dependency_step["if"] == "matrix.platform == 'linux'"
    for package in (
        "libdbus-1-3",
        "libegl1",
        "libgl1",
        "libxcb-cursor0",
        "libxkbcommon-x11-0",
    ):
        assert package in dependency_step["run"]

    test_steps = [step for step in steps if "python -m pytest" in step.get("run", "")]
    assert len(test_steps) == 2
    linux_test = next(step for step in test_steps if step["if"] == "matrix.platform == 'linux'")
    other_test = next(step for step in test_steps if step["if"] == "matrix.platform != 'linux'")
    assert linux_test["env"] == {"QT_QPA_PLATFORM": "offscreen"}
    assert linux_test["run"] == "python -m pytest"
    assert other_test["run"] == "python -m pytest"
    assert steps.index(dependency_step) < steps.index(linux_test)
    assert all("-k" not in step["run"] and "--ignore" not in step["run"] for step in test_steps)


def test_macos_bundle_diagnostics_precede_frozen_validation() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    diagnostic = next(
        step
        for step in steps
        if "find dist/ComicAPNG.app/Contents" in step.get("run", "")
    )
    validation = next(
        step
        for step in steps
        if "python scripts/validate_frozen_archive.py" in step.get("run", "")
    )
    assert diagnostic["if"] == "matrix.platform == 'macos'"
    assert "plugins/platforms" in diagnostic["run"]
    assert steps.index(diagnostic) < steps.index(validation)


def test_release_reuses_every_build_archive_without_rebuilding() -> None:
    release = _workflow()["jobs"]["release"]
    uses = [step.get("uses") for step in release["steps"] if "uses" in step]
    assert uses == ["actions/download-artifact@v8"]
    scripts = "\n".join(step.get("run", "") for step in release["steps"])
    for _runner, _artifact_name, archive_name in EXPECTED_MATRIX.values():
        assert archive_name in scripts
    assert "SHA256SUMS.txt" in scripts
    assert "sha256sum" in scripts
    assert "PyInstaller" not in scripts
    assert "pip install" not in scripts


def test_rc_and_stable_publish_steps_have_distinct_release_behavior() -> None:
    release = _workflow()["jobs"]["release"]
    rc_step = next(step for step in release["steps"] if step.get("id") == "publish_rc")
    stable_step = next(step for step in release["steps"] if step.get("id") == "publish_stable")

    assert rc_step["if"] == "needs.release_policy.outputs.release_kind == 'rc'"
    assert stable_step["if"] == "needs.release_policy.outputs.release_kind == 'stable'"
    assert "--prerelease" in rc_step["run"]
    assert "--prerelease" not in stable_step["run"]
    for step in (rc_step, stable_step):
        assert "gh release create \"$GITHUB_REF_NAME\"" in step["run"]
        assert "--generate-notes" in step["run"]
        assert "--verify-tag" in step["run"]
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert step["env"]["GH_REPO"] == "${{ github.repository }}"
