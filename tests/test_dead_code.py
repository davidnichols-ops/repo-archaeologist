"""Tests for the dead code collector."""

from __future__ import annotations

from pathlib import Path

from repo_archaeologist.collectors import dead_code as dead_code_collector


def test_dead_code_detects_unreferenced_py_module(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("from helpers import thing\n\nprint(thing)\n", encoding="utf-8")
    (repo / "helpers.py").write_text("thing = 1\n", encoding="utf-8")
    # orphan.py is never imported
    (repo / "orphan.py").write_text("x = 42\n", encoding="utf-8")

    report = dead_code_collector.collect(repo)
    relpaths = [m.relpath for m in report.modules]
    assert "orphan.py" in relpaths
    assert "main.py" not in relpaths
    assert "helpers.py" not in relpaths


def test_dead_code_excludes_entry_points_and_tests(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text("def test_main(): pass\n", encoding="utf-8")
    (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")

    report = dead_code_collector.collect(repo)
    relpaths = [m.relpath for m in report.modules]
    assert "main.py" not in relpaths
    assert "tests/test_main.py" not in relpaths
    assert "tests/__init__.py" not in relpaths


def test_dead_code_detects_unreferenced_js_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.js").write_text('const util = require("./util");\nconsole.log(util);\n', encoding="utf-8")
    (repo / "util.js").write_text("module.exports = {};\n", encoding="utf-8")
    (repo / "orphan.js").write_text("module.exports = {};\n", encoding="utf-8")

    report = dead_code_collector.collect(repo)
    relpaths = [m.relpath for m in report.modules]
    assert "orphan.js" in relpaths
    assert "index.js" not in relpaths
    assert "util.js" not in relpaths


def test_dead_code_handles_package_import(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "mod.py").write_text("val = 1\n", encoding="utf-8")
    (repo / "pkg" / "other.py").write_text("val = 2\n", encoding="utf-8")
    (repo / "main.py").write_text("from pkg import mod\nprint(mod.val)\n", encoding="utf-8")

    report = dead_code_collector.collect(repo)
    relpaths = [m.relpath for m in report.modules]
    # pkg.other is never imported -> dead
    assert "pkg/other.py" in relpaths
    # pkg.mod is imported -> alive
    assert "pkg/mod.py" not in relpaths
    assert "main.py" not in relpaths


def test_dead_code_empty_repo(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    report = dead_code_collector.collect(repo)
    assert report.count == 0
    assert report.modules == []
