"""Orchestrate collection and report generation."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from repo_archaeologist.collectors import dependencies as dep_collector
from repo_archaeologist.collectors import structure as struct_collector
from repo_archaeologist.facts import Facts
from repo_archaeologist.reports import architecture, executive_summary, first_15_minutes


@dataclass
class AnalysisResult:
    facts: Facts
    reports: List[Path]
    target: Path  # the directory that was analyzed (may be a temp clone)
    cloned: bool  # True if we cloned a remote URL


def analyze(target: Path, out_dir: Optional[Path] = None) -> AnalysisResult:
    """Analyze a target directory and write reports.

    Args:
        target: directory to analyze (already resolved; cloning handled by the CLI).
        out_dir: where to write reports. Defaults to the target directory.
    """
    target = target.resolve()
    if not target.is_dir():
        raise NotADirectoryError(f"Target is not a directory: {target}")

    out_dir = (out_dir or target).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    structure = struct_collector.collect(target)
    deps = dep_collector.collect(target)
    facts = Facts(root=target, structure=structure, dependencies=deps)

    written = [
        architecture.write(facts, out_dir),
        executive_summary.write(facts, out_dir),
        first_15_minutes.write(facts, out_dir),
    ]

    return AnalysisResult(facts=facts, reports=written, target=target, cloned=False)
