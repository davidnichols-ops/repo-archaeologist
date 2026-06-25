"""Tests for repo-archaeologist.

Two test groups:
1. Self-analysis — run the analyzer on this very repo and assert the 3 reports exist
   with the expected section headers.
2. Fixture analysis — build a tiny fake repo in a tmp_path and assert the heuristics
   detect the right entry point, dependency, and reports.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repo_archaeologist.analyzer import analyze
from repo_archaeologist.collectors import dependencies as dep_collector
from repo_archaeologist.collectors import structure as struct_collector
from repo_archaeologist.facts import Facts


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------- Self-analysis ----------


def test_self_analysis_writes_three_reports(tmp_path):
    out_dir = tmp_path / "reports"
    result = analyze(REPO_ROOT, out_dir=out_dir)

    names = {p.name for p in result.reports}
    assert names == {"ARCHITECTURE.md", "EXECUTIVE_SUMMARY.md", "FIRST_15_MINUTES.md"}


def test_self_analysis_executive_summary_has_sections(tmp_path):
    out_dir = tmp_path / "reports"
    analyze(REPO_ROOT, out_dir=out_dir)
    text = (out_dir / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
    assert "# Executive Summary" in text
    assert "Time to understand repository" in text
    assert "Risk level" in text
    assert "Likely purpose" in text
    assert "First file to read" in text
    assert "Most important dependency" in text
    assert "Suggested first contribution" in text


def test_self_analysis_architecture_has_sections(tmp_path):
    out_dir = tmp_path / "reports"
    analyze(REPO_ROOT, out_dir=out_dir)
    text = (out_dir / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "# Architecture" in text
    assert "## Tech Stack" in text
    assert "## Entry Points" in text
    assert "## Dependencies" in text
    assert "## Top-Level Layout" in text
    assert "## Project Hygiene" in text


def test_self_analysis_first_15_minutes_has_sections(tmp_path):
    out_dir = tmp_path / "reports"
    analyze(REPO_ROOT, out_dir=out_dir)
    text = (out_dir / "FIRST_15_MINUTES.md").read_text(encoding="utf-8")
    assert "# First 15 Minutes" in text
    assert "## Read these files" in text
    assert "## Ignore these" in text
    assert "## Run this" in text


def test_self_analysis_detects_itself_as_python(tmp_path):
    out_dir = tmp_path / "reports"
    result = analyze(REPO_ROOT, out_dir=out_dir)
    assert result.facts.structure.primary_language == "Python"
    assert result.facts.structure.source_file_count > 0


# ---------- Fixture-based tests ----------


@pytest.fixture
def fake_repo(tmp_path):
    """A tiny fake Python repo with a main.py and requirements.txt."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        '"""A tiny fake app."""\n\nimport fastapi\n\n\ndef main():\n    print("hello")\n\n\nif __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("fastapi>=0.100\nrequests\nnumpy\n", encoding="utf-8")
    (repo / "README.md").write_text("# fake-repo\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")
    return repo


def test_fixture_detects_entry_point(fake_repo):
    s = struct_collector.collect(fake_repo)
    assert "main.py" in s.entry_points


def test_fixture_detects_python_and_tests(fake_repo):
    s = struct_collector.collect(fake_repo)
    assert s.primary_language == "Python"
    assert s.has_tests is True
    assert s.has_readme is True


def test_fixture_detects_fastapi_as_most_important(fake_repo):
    d = dep_collector.collect(fake_repo)
    assert d.count == 3
    assert d.primary_ecosystem == "pypi"
    assert d.most_important is not None
    assert d.most_important.name == "fastapi"


def test_fixture_executive_summary_says_web_api(fake_repo, tmp_path):
    out_dir = tmp_path / "out"
    result = analyze(fake_repo, out_dir=out_dir)
    text = (out_dir / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
    assert "web API or web service" in text
    assert "fastapi" in text.lower()


def test_fixture_first_15_minutes_lists_main_py(fake_repo, tmp_path):
    out_dir = tmp_path / "out"
    analyze(fake_repo, out_dir=out_dir)
    text = (out_dir / "FIRST_15_MINUTES.md").read_text(encoding="utf-8")
    assert "main.py" in text
    assert "pip install" in text


def test_fixture_risk_is_low_or_medium(fake_repo, tmp_path):
    out_dir = tmp_path / "out"
    analyze(fake_repo, out_dir=out_dir)
    text = (out_dir / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
    # fake_repo has README + tests, so risk should not be HIGH
    assert "HIGH" not in text.split("Risk level")[1].split("\n")[0]


# ---------- Edge cases ----------


def test_empty_dir_does_not_crash(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = analyze(empty, out_dir=tmp_path / "out")
    assert len(result.reports) == 3
    text = (tmp_path / "out" / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
    assert "Executive Summary" in text


def test_nonexistent_target_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        analyze(tmp_path / "does-not-exist", out_dir=tmp_path / "out")
