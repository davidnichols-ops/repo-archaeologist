"""Collect a best-effort module dependency graph for Mermaid diagrams.

We extract import edges between *local* modules only (stdlib and third-party
packages are collapsed into a single ``external`` node per language to keep the
graph readable). The graph is intentionally simple and may be imperfect — it is
a visual aid, not a ground-truth dependency tree.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from repo_archaeologist.collectors.structure import SKIP_DIRS


@dataclass
class ImportGraph:
    """A directed graph of local module dependencies.

    Nodes are short, human-readable module names (repo-relative dotted paths).
    Edges go from a source module to a module it imports.
    """

    nodes: List[str] = field(default_factory=list)
    edges: List[Tuple[str, str]] = field(default_factory=list)
    external: List[str] = field(default_factory=list)  # collapsed external nodes

    @property
    def has_graph(self) -> bool:
        return bool(self.nodes)


def _py_dotted(rel: str) -> str:
    parts = rel.split(os.sep)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


_PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE)
_PY_FROM_IMPORT_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import", re.MULTILINE)
_JS_REQUIRE_RE = re.compile(r'require\s*\(\s*["\']([^"\']+)["\']', re.MULTILINE)
_JS_IMPORT_RE = re.compile(
    r'\bimport\s+(?:[\w*{}\s,]+\s+from\s+)?["\']([^"\']+)["\']', re.MULTILINE
)


def _resolve_js_spec(spec: str, rel_file: str) -> str:
    if not (spec.startswith("./") or spec.startswith("../")):
        return ""
    base_dir = os.path.dirname(rel_file)
    target = os.path.normpath(os.path.join(base_dir, spec))
    # strip extension if present
    for ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
        if target.endswith(ext):
            target = target[: -len(ext)]
            break
    return target.replace(os.sep, ".")


def collect(root: Path, max_nodes: int = 40) -> ImportGraph:
    """Build a local module dependency graph, capped at ``max_nodes`` for readability."""
    root = root.resolve()
    graph = ImportGraph()
    if not root.is_dir():
        return graph

    py_files: List[str] = []
    js_files: List[str] = []
    py_modules: Set[str] = set()
    js_modules: Set[str] = set()

    # First pass: collect local module names.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git"))
        for fname in filenames:
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext not in ("py", "js", "jsx", "mjs", "cjs", "ts", "tsx"):
                continue
            fpath = Path(dirpath) / fname
            rel = str(fpath.relative_to(root))
            if fname == "__init__.py":
                continue  # package marker; represented by its package node
            if ext == "py":
                py_files.append(rel)
                py_modules.add(_py_dotted(rel))
            else:
                js_files.append(rel)
                js_modules.add(_resolve_js_spec(rel, rel) or rel.replace(os.sep, ".").rsplit(".", 1)[0])

    # Determine the top-level package name(s) so we can distinguish local from external.
    local_top: Set[str] = set()
    for m in py_modules:
        top = m.split(".", 1)[0]
        local_top.add(top)
    for m in js_modules:
        top = m.split(".", 1)[0]
        local_top.add(top)

    edges: Set[Tuple[str, str]] = set()
    external: Set[str] = set()

    def is_local(mod: str) -> bool:
        top = mod.split(".", 1)[0]
        return top in local_top

    # Second pass: extract edges.
    for rel in py_files:
        src = _py_dotted(rel)
        try:
            text = Path(root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _PY_IMPORT_RE.finditer(text):
            tgt = m.group(1)
            if is_local(tgt) and tgt in py_modules and tgt != src:
                edges.add((src, tgt))
            elif not is_local(tgt):
                external.add(tgt.split(".", 1)[0])
        for m in _PY_FROM_IMPORT_RE.finditer(text):
            tgt = m.group(1).lstrip(".")
            if not tgt:
                continue
            if is_local(tgt) and tgt in py_modules and tgt != src:
                edges.add((src, tgt))
            elif not is_local(tgt):
                external.add(tgt.split(".", 1)[0])

    for rel in js_files:
        src = _resolve_js_spec(rel, rel) or rel.replace(os.sep, ".").rsplit(".", 1)[0]
        try:
            text = Path(root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _JS_REQUIRE_RE.finditer(text):
            spec = m.group(1)
            if spec.startswith("./") or spec.startswith("../"):
                tgt = _resolve_js_spec(spec, rel)
                if tgt in js_modules and tgt != src:
                    edges.add((src, tgt))
            else:
                external.add(spec.split("/", 1)[0].split(".", 1)[0])
        for m in _JS_IMPORT_RE.finditer(text):
            spec = m.group(1)
            if spec.startswith("./") or spec.startswith("../"):
                tgt = _resolve_js_spec(spec, rel)
                if tgt in js_modules and tgt != src:
                    edges.add((src, tgt))
            else:
                external.add(spec.split("/", 1)[0].split(".", 1)[0])

    all_nodes = sorted(py_modules | js_modules)
    # Cap node count: keep the most-connected nodes.
    if len(all_nodes) > max_nodes:
        degree: Dict[str, int] = {}
        for a, b in edges:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        all_nodes = sorted(all_nodes, key=lambda n: -degree.get(n, 0))[:max_nodes]
        keep = set(all_nodes)
        edges = {(a, b) for a, b in edges if a in keep and b in keep}

    graph.nodes = all_nodes
    graph.edges = sorted(edges)
    graph.external = sorted(external)[:15]
    return graph


def mermaid(graph: ImportGraph) -> str:
    """Render the graph as a Mermaid ``graph LR`` block (without fences)."""
    if not graph.has_graph:
        return ""

    lines: List[str] = ["graph LR"]

    # Sanitize node ids: mermaid ids can't contain dots, so replace with __.
    def nid(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "_", name)

    # Emit nodes with labels.
    for n in graph.nodes:
        lines.append(f'  {nid(n)}["{n}"]')

    if graph.external:
        lines.append("  ext[\"external deps\"]")
        # connect any node that has an external edge to the external bucket
        # (we don't track per-edge external targets to keep the graph small)
        for n in graph.nodes[:5]:
            lines.append(f"  {nid(n)} -.-> ext")

    for a, b in graph.edges:
        lines.append(f"  {nid(a)} --> {nid(b)}")

    return "\n".join(lines)
