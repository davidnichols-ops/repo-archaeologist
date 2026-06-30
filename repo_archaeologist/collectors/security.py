"""Best-effort security scan: secrets, deprecated packages, dangerous calls.

This is a *static, offline* heuristic scanner. It is not a substitute for a real
SAST tool (bandit, semgrep, gitleaks). It exists so an inherited repo gets a
first-pass "is there anything obviously scary here?" answer with zero setup.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from repo_archaeologist.collectors.structure import SKIP_DIRS, _is_source

# Severity ordering used for sorting and display.
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


@dataclass
class Finding:
    """A single security finding."""

    severity: str  # CRITICAL / HIGH / MEDIUM / LOW / INFO
    category: str  # e.g. "secret", "deprecated-package", "dangerous-call"
    message: str
    relpath: str  # repo-relative path of the offending file (or manifest)
    line: int = 0  # 1-based line number, 0 if not applicable

    def sort_key(self) -> Tuple[int, str, int, str]:
        return (SEVERITY_ORDER.get(self.severity, 99), self.relpath, self.line, self.message)


@dataclass
class SecurityReport:
    findings: List[Finding] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.findings)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "MEDIUM")

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "LOW")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "INFO")

    def by_severity(self) -> Dict[str, List[Finding]]:
        groups: Dict[str, List[Finding]] = {}
        for f in self.findings:
            groups.setdefault(f.severity, []).append(f)
        return groups


# ---------------------------------------------------------------------------
# Secret detection
# ---------------------------------------------------------------------------

# High-signal token patterns. We match on structure first, then entropy for
# generic strings to avoid flagging every long word.
_AWS_ACCESS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
_AWS_SECRET_RE = re.compile(r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])")
_GITHUB_PAT_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")
_GITHUB_LEGACY_RE = re.compile(r"\b[a-f0-9]{40}\b")  # 40-hex legacy token; weak signal
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")
_GOOGLE_API_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")

# Variable names that hint at a secret even when the value is generic.
_SECRET_VAR_RE = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*['\"]([A-Za-z0-9+/=_\-]{16,})['\"]"
)
_SECRET_NAME_HINTS = (
    "secret",
    "token",
    "apikey",
    "api_key",
    "accesskey",
    "access_key",
    "privatekey",
    "private_key",
    "passwd",
    "password",
    "pwd",
    "auth",
)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: Dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    length = len(s)
    entropy = 0.0
    for c in counts.values():
        p = c / length
        entropy -= p * math.log2(p)
    return entropy


def _scan_secrets(text: str, relpath: str) -> List[Finding]:
    findings: List[Finding] = []
    lines = text.splitlines()

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for m in _AWS_ACCESS_KEY_RE.finditer(text):
        findings.append(Finding("CRITICAL", "secret", "AWS access key id detected", relpath, line_of(m.start())))
    for m in _GITHUB_PAT_RE.finditer(text):
        findings.append(Finding("CRITICAL", "secret", "GitHub personal access token detected", relpath, line_of(m.start())))
    for m in _SLACK_TOKEN_RE.finditer(text):
        findings.append(Finding("HIGH", "secret", "Slack token detected", relpath, line_of(m.start())))
    for m in _GOOGLE_API_KEY_RE.finditer(text):
        findings.append(Finding("HIGH", "secret", "Google API key detected", relpath, line_of(m.start())))
    for m in _JWT_RE.finditer(text):
        findings.append(Finding("MEDIUM", "secret", "JWT token literal detected", relpath, line_of(m.start())))
    for m in _PRIVATE_KEY_RE.finditer(text):
        findings.append(Finding("CRITICAL", "secret", "Private key block detected", relpath, line_of(m.start())))

    # Variable-name + high-entropy value heuristic.
    for m in _SECRET_VAR_RE.finditer(text):
        name = m.group(1)
        value = m.group(2)
        low_name = name.lower()
        if any(h in low_name for h in _SECRET_NAME_HINTS):
            findings.append(
                Finding("HIGH", "secret", f"Possible secret assigned to `{name}`", relpath, line_of(m.start()))
            )
            continue
        # generic high-entropy string with no name hint
        if _shannon_entropy(value) >= 4.5 and len(value) >= 32:
            findings.append(
                Finding("MEDIUM", "secret", f"High-entropy string literal (entropy={_shannon_entropy(value):.1f})", relpath, line_of(m.start()))
            )

    # AWS secret key: 40-char base64-ish, but only flag if near a secret-ish name
    # to avoid false positives on git SHAs / hashes.
    for i, line in enumerate(lines, 1):
        if any(h in line.lower() for h in ("aws_secret", "secret_access", "secret_key")):
            for m in _AWS_SECRET_RE.finditer(line):
                findings.append(Finding("CRITICAL", "secret", "Likely AWS secret access key", relpath, i))

    return findings


# ---------------------------------------------------------------------------
# Deprecated / known-vulnerable package detection
# ---------------------------------------------------------------------------

# A tiny offline allowlist of known-deprecated package names. This is *not* a
# vulnerability database — it flags packages that are widely considered
# abandoned or dangerous so a maintainer can investigate.
DEPRECATED_PACKAGES: Dict[str, str] = {
    # Python
    "pip": "pip as a runtime dependency is unusual; pin and review",
    "distutils": "distutils is removed in Python 3.12; use setuptools/packaging",
    "nose": "nose is unmaintained; use pytest",
    "nose2": "nose2 is largely unmaintained; prefer pytest",
    "mock": "use stdlib unittest.mock instead of the standalone `mock` backport",
    "pbr": "pbr is largely unmaintained",
    "requirements-parser": "rare runtime dep; review",
    "setupmeta": "unmaintained setup helper",
    # Node
    "request": "request is deprecated; use node-fetch, axios, or undici",
    "request-promise": "deprecated (depends on request)",
    "node-uuid": "renamed to uuid; node-uuid is deprecated",
    "gulp-util": "removed in gulp 4; replace",
    "bower": "bower is deprecated; use npm/yarn",
    "phantomjs": "phantomjs is abandoned",
    "react-native-cli": "use the react-native community CLI",
    # Ruby
    "tilt": "review — tilt 1.x is old",
}


def _scan_deprecated_deps(root: Path) -> List[Finding]:
    findings: List[Finding] = []

    # requirements.txt
    req = root / "requirements.txt"
    if req.exists():
        try:
            for i, raw in enumerate(req.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                line = raw.split("#", 1)[0].strip()
                if not line or line.startswith("-"):
                    continue
                m = re.match(r"^([A-Za-z0-9_.-]+)", line)
                if m:
                    name = m.group(1).lower().replace("_", "-")
                    if name in DEPRECATED_PACKAGES:
                        findings.append(
                            Finding("MEDIUM", "deprecated-package", f"`{name}`: {DEPRECATED_PACKAGES[name]}", "requirements.txt", i)
                        )
        except OSError:
            pass

    # pyproject.toml (lightweight scan for quoted dep names)
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'["\']([A-Za-z0-9_.-]+)(?:[<>=!~;][^"\']*)?["\']', text):
                name = m.group(1).lower().replace("_", "-")
                if name in DEPRECATED_PACKAGES:
                    findings.append(
                        Finding("MEDIUM", "deprecated-package", f"`{name}`: {DEPRECATED_PACKAGES[name]}", "pyproject.toml", text.count("\n", 0, m.start()) + 1)
                    )
        except OSError:
            pass

    # package.json
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for name in (data.get(section, {}) or {}):
                    if name.lower() in DEPRECATED_PACKAGES:
                        findings.append(
                            Finding("MEDIUM", "deprecated-package", f"`{name}`: {DEPRECATED_PACKAGES[name.lower()]}", "package.json", 0)
                        )
        except (json.JSONDecodeError, OSError):
            pass

    return findings


# ---------------------------------------------------------------------------
# Dangerous calls
# ---------------------------------------------------------------------------

# Python
_PY_EVAL_RE = re.compile(r"\beval\s*\(")
_PY_EXEC_RE = re.compile(r"\bexec\s*\(")
_PY_OS_SYSTEM_RE = re.compile(r"\bos\.system\s*\(")
_PY_SUBPROCESS_SHELL_RE = re.compile(r"subprocess\.(?:run|call|Popen|check_output|check_call)\s*\([^)]*shell\s*=\s*True", re.DOTALL)
_PY_PICKLE_LOAD_RE = re.compile(r"\bpickle\.loads?\s*\(")
_PY_MKTEMP_RE = re.compile(r"\b(?:os\.|tempfile\.)?mktemp\b\s*\(")

# JavaScript
_JS_EVAL_RE = re.compile(r"\beval\s*\(")
_JS_CHILD_PROCESS_SHELL_RE = re.compile(r"child_process\.\w+\s*\([^)]*shell\s*:\s*true", re.DOTALL)
_JS_EXEC_RE = re.compile(r"\bnew\s+Function\s*\(")


def _scan_dangerous_calls(text: str, relpath: str, ext: str) -> List[Finding]:
    findings: List[Finding] = []
    lines = text.splitlines()

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    if ext == ".py":
        for m in _PY_EVAL_RE.finditer(text):
            findings.append(Finding("HIGH", "dangerous-call", "Use of `eval()`", relpath, line_of(m.start())))
        for m in _PY_EXEC_RE.finditer(text):
            findings.append(Finding("MEDIUM", "dangerous-call", "Use of `exec()`", relpath, line_of(m.start())))
        for m in _PY_OS_SYSTEM_RE.finditer(text):
            findings.append(Finding("MEDIUM", "dangerous-call", "Use of `os.system()`", relpath, line_of(m.start())))
        for m in _PY_SUBPROCESS_SHELL_RE.finditer(text):
            findings.append(Finding("HIGH", "dangerous-call", "subprocess with `shell=True`", relpath, line_of(m.start())))
        for m in _PY_PICKLE_LOAD_RE.finditer(text):
            findings.append(Finding("MEDIUM", "dangerous-call", "Use of `pickle.load(s)` — deserializing untrusted pickle is unsafe", relpath, line_of(m.start())))
        for m in _PY_MKTEMP_RE.finditer(text):
            findings.append(Finding("MEDIUM", "dangerous-call", "Use of `mktemp` — race condition; use mkstemp/TemporaryFile", relpath, line_of(m.start())))
    elif ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
        for m in _JS_EVAL_RE.finditer(text):
            findings.append(Finding("HIGH", "dangerous-call", "Use of `eval()`", relpath, line_of(m.start())))
        for m in _JS_CHILD_PROCESS_SHELL_RE.finditer(text):
            findings.append(Finding("HIGH", "dangerous-call", "child_process with `shell: true`", relpath, line_of(m.start())))
        for m in _JS_EXEC_RE.finditer(text):
            findings.append(Finding("MEDIUM", "dangerous-call", "Use of `new Function()` (dynamic code)", relpath, line_of(m.start())))

    return findings


# ---------------------------------------------------------------------------
# Top-level collect
# ---------------------------------------------------------------------------

# Files we never scan for secrets (noise / binary / vendored).
_SECRET_SKIP_EXT = {".lock", ".sum", ".map", ".min.js", ".min.css", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}


def collect(root: Path) -> SecurityReport:
    """Scan the repo for secrets, deprecated packages, and dangerous calls."""
    root = root.resolve()
    report = SecurityReport()
    if not root.is_dir():
        return report

    # 1. Deprecated deps from manifests.
    report.findings.extend(_scan_deprecated_deps(root))

    # 2. Walk source files for secrets + dangerous calls.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git"))
        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()
            if ext in _SECRET_SKIP_EXT:
                continue
            # Only scan text-y source/config files.
            if not (_is_source(fpath) or ext in (".toml", ".json", ".yml", ".yaml", ".env", ".ini", ".cfg", ".conf", ".txt") or ext == ""):
                continue
            # Skip the generated reports themselves if present in the tree.
            if fname in {"SECURITY.md", "ARCHITECTURE.md", "EXECUTIVE_SUMMARY.md", "FIRST_15_MINUTES.md"}:
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = str(fpath.relative_to(root))
            report.findings.extend(_scan_secrets(text, rel))
            if ext in (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
                report.findings.extend(_scan_dangerous_calls(text, rel, ext))

    # Dedup identical findings (same severity/category/relpath/line/message).
    seen = set()
    unique: List[Finding] = []
    for f in report.findings:
        key = (f.severity, f.category, f.relpath, f.line, f.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    report.findings = sorted(unique, key=lambda f: f.sort_key())
    return report
