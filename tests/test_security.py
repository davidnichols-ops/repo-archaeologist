"""Tests for the security collector."""

from __future__ import annotations

from pathlib import Path

from repo_archaeologist.collectors import security as security_collector


def test_detects_aws_access_key(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        'KEY = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8"
    )
    report = security_collector.collect(repo)
    assert report.critical_count >= 1
    assert any(f.category == "secret" and "AWS access key" in f.message for f in report.findings)


def test_detects_github_token(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.py").write_text(
        'token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"\n', encoding="utf-8"
    )
    report = security_collector.collect(repo)
    assert report.critical_count >= 1
    assert any("GitHub" in f.message for f in report.findings)


def test_detects_private_key_block(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "id_rsa").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    report = security_collector.collect(repo)
    assert report.critical_count >= 1
    assert any("Private key" in f.message for f in report.findings)


def test_detects_eval_and_shell_true(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "danger.py").write_text(
        "import subprocess\n\ndef f(user_input):\n    eval(user_input)\n    subprocess.run(user_input, shell=True)\n",
        encoding="utf-8",
    )
    report = security_collector.collect(repo)
    cats = [f.category for f in report.findings]
    assert cats.count("dangerous-call") >= 2
    assert any("eval" in f.message.lower() for f in report.findings)
    assert any("shell=True" in f.message for f in report.findings)


def test_detects_os_system(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "run.py").write_text("import os\nos.system('rm -rf /')\n", encoding="utf-8")
    report = security_collector.collect(repo)
    assert any("os.system" in f.message for f in report.findings)


def test_detects_deprecated_package_in_requirements(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("request\nnose\nflask\n", encoding="utf-8")
    report = security_collector.collect(repo)
    msgs = " ".join(f.message for f in report.findings)
    assert "request" in msgs
    assert "nose" in msgs


def test_detects_deprecated_package_in_package_json(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"dependencies": {"request": "^2.88.0", "express": "^4.0.0"}}\n',
        encoding="utf-8",
    )
    report = security_collector.collect(repo)
    msgs = " ".join(f.message for f in report.findings)
    assert "request" in msgs


def test_detects_js_eval(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.js").write_text("function f(x){ return eval(x); }\n", encoding="utf-8")
    report = security_collector.collect(repo)
    assert any("eval" in f.message.lower() for f in report.findings)


def test_no_false_positives_on_clean_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        '"""Clean module."""\n\ndef add(a, b):\n    return a + b\n', encoding="utf-8"
    )
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    report = security_collector.collect(repo)
    # No secrets, no dangerous calls, no deprecated deps
    assert report.critical_count == 0
    assert report.high_count == 0
    assert all(f.category != "dangerous-call" for f in report.findings)


def test_empty_repo(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    report = security_collector.collect(repo)
    assert report.count == 0


def test_findings_sorted_by_severity(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(
        'KEY = "AKIAIOSFODNN7EXAMPLE"\nimport os\nos.system("x")\n', encoding="utf-8"
    )
    report = security_collector.collect(repo)
    severities = [f.severity for f in report.findings]
    # CRITICAL should come before MEDIUM
    if "CRITICAL" in severities and "MEDIUM" in severities:
        assert severities.index("CRITICAL") < severities.index("MEDIUM")
