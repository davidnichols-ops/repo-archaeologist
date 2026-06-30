"""Tests for the import graph collector and Mermaid rendering."""

from __future__ import annotations

from pathlib import Path

from repo_archaeologist.collectors import imports as imports_collector
from repo_archaeologist.collectors.imports import mermaid


def test_import_graph_builds_local_edges(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("from helpers import thing\n", encoding="utf-8")
    (repo / "helpers.py").write_text("thing = 1\n", encoding="utf-8")

    graph = imports_collector.collect(repo)
    assert graph.has_graph
    assert "main" in graph.nodes
    assert "helpers" in graph.nodes
    assert ("main", "helpers") in graph.edges


def test_import_graph_excludes_external_from_edges(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("import os\nimport sys\n", encoding="utf-8")

    graph = imports_collector.collect(repo)
    # os/sys are external; no edges between local nodes
    assert graph.edges == []
    assert "main" in graph.nodes


def test_mermaid_renders_graph_block(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("from helpers import thing\n", encoding="utf-8")
    (repo / "helpers.py").write_text("thing = 1\n", encoding="utf-8")

    graph = imports_collector.collect(repo)
    out = mermaid(graph)
    assert out.startswith("graph LR")
    assert "main" in out
    assert "helpers" in out
    assert "-->" in out


def test_mermaid_empty_graph_returns_empty(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    graph = imports_collector.collect(repo)
    assert not graph.has_graph
    assert mermaid(graph) == ""


def test_import_graph_js_edges(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.js").write_text('const u = require("./util");\n', encoding="utf-8")
    (repo / "util.js").write_text("module.exports = {};\n", encoding="utf-8")

    graph = imports_collector.collect(repo)
    assert graph.has_graph
    # JS modules should appear as nodes
    assert any("index" in n for n in graph.nodes)
    assert any("util" in n for n in graph.nodes)
