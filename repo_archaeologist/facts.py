"""Shared facts container passed from the analyzer to report writers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from repo_archaeologist.collectors.dead_code import DeadCodeReport
from repo_archaeologist.collectors.dependencies import DependencyReport
from repo_archaeologist.collectors.imports import ImportGraph
from repo_archaeologist.collectors.security import SecurityReport
from repo_archaeologist.collectors.structure import Structure


@dataclass
class Facts:
    """All collected facts about a repository, ready for report generation."""

    root: Path
    structure: Structure
    dependencies: DependencyReport
    dead_code: Optional[DeadCodeReport] = None
    security: Optional[SecurityReport] = None
    imports: Optional[ImportGraph] = None

    @property
    def repo_name(self) -> str:
        return self.root.name
