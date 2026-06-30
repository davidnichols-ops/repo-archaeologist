"""Tests for the new report sections and CLI flags added in v0.2.0."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_archaeologist.analyzer import AnalysisOptions, analyze
from repo_archaeologist.cli import main as cli_main


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------- Architecture report: Mermaid + dead code ----------


def test_architecture_has_mermaid_diagram(tmp_path):
    out_dir = tmp_path / "out"
    analyze(REPO_ROOT, out_dir=out_dir)
    text = (out_dir / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "## Dependency Diagram" in text
    assert "```mermaid" in text
    assert "graph LR" in text


def test_architecture_has_dead_code_section(tmp_path):
    out_dir = tmp_path / "out"
    analyze(REPO_ROOT, out_dir=out_dir)
    text = (out_dir / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "## Dead Code Estimate" in text


def test_architecture_dead_code_disabled(tmp_path):
    out_dir = tmp_path / "out"
    analyze(REPO_ROOT, out_dir=out_dir, options=AnalysisOptions(dead_code=False, security=True))
    text = (out_dir / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "disabled via --no-dead-code" in text


# ---------- SECURITY.md report ----------


def test_security_report_written(tmp_path):
    out_dir = tmp_path / "out"
    analyze(REPO_ROOT, out_dir=out_dir)
    assert (out_dir / "SECURITY.md").exists()
    text = (out_dir / "SECURITY.md").read_text(encoding="utf-8")
    assert "# Security Scan" in text
    assert "## Summary" in text


def test_security_report_no_security_flag(tmp_path):
    out_dir = tmp_path / "out"
    analyze(REPO_ROOT, out_dir=out_dir, options=AnalysisOptions(dead_code=True, security=False))
    assert not (out_dir / "SECURITY.md").exists()


def test_security_report_lists_findings_for_secrets_repo(tmp_path):
    repo = tmp_path / "risky"
    repo.mkdir()
    (repo / "app.py").write_text(
        'KEY = "AKIAIOSFODNN7EXAMPLE"\nimport os\nos.system("x")\n',
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    analyze(repo, out_dir=out_dir)
    text = (out_dir / "SECURITY.md").read_text(encoding="utf-8")
    assert "CRITICAL" in text
    assert "AWS access key" in text
    assert "os.system" in text


def test_executive_summary_mentions_security_md(tmp_path):
    out_dir = tmp_path / "out"
    analyze(REPO_ROOT, out_dir=out_dir)
    text = (out_dir / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
    assert "SECURITY.md" in text


# ---------- CLI flags ----------


def test_cli_no_security_skips_security(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = cli_main(["analyze", str(repo), "--out-dir", str(out_dir), "--no-security"])
    assert rc == 0
    assert (out_dir / "ARCHITECTURE.md").exists()
    assert not (out_dir / "SECURITY.md").exists()


def test_cli_no_dead_code_skips_dead_code(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = cli_main(["analyze", str(repo), "--out-dir", str(out_dir), "--no-dead-code"])
    assert rc == 0
    text = (out_dir / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "disabled via --no-dead-code" in text


def test_cli_default_writes_security(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = cli_main(["analyze", str(repo), "--out-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "SECURITY.md").exists()


def test_cli_version_reports_0_2_0(capsys):
    with pytest.raises(SystemExit):
        cli_main(["--version"])
    captured = capsys.readouterr()
    assert "0.2.0" in captured.out
