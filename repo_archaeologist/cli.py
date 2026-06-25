"""Command-line interface for repo-archaeologist."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from repo_archaeologist import __version__
from repo_archaeologist.analyzer import AnalysisResult, analyze

GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/[\w.-]+/[\w.-]+?(?:\.git)?(?:/|$)",
    re.IGNORECASE,
)


def _is_github_url(s: str) -> bool:
    return bool(GITHUB_URL_RE.match(s))


def _clone(url: str, dest: Path) -> Path:
    """Clone a GitHub URL into dest. Returns the clone path."""
    # Normalize: ensure .git suffix is stripped from dest dir name
    cmd = ["git", "clone", "--depth", "1", url, str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("git not found. Install git to analyze GitHub URLs.")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"git clone failed for {url}:\n{e.stderr.strip()}")
    return dest


def _resolve_target(target_arg: Optional[str]) -> tuple:
    """Resolve the target argument into (path, cloned, tempdir_to_clean).

    Returns:
        (target_path, cloned_bool, tempdir_path_or_None)
    """
    if target_arg is None:
        return Path.cwd(), False, None

    if _is_github_url(target_arg):
        tmp = tempfile.mkdtemp(prefix="repo-arch-")
        # Derive a sensible dir name from the URL (last path segment, minus .git)
        tail = target_arg.rstrip("/").split("/")[-1]
        if tail.endswith(".git"):
            tail = tail[:-4]
        if not tail:
            tail = "repo"
        clone_dir = Path(tmp) / tail
        _clone(target_arg, clone_dir)
        return clone_dir, True, tmp

    path = Path(target_arg).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Target does not exist: {path}")
    if not path.is_dir():
        raise SystemExit(f"Target is not a directory: {path}")
    return path, False, None


def _print_summary(result: AnalysisResult, out_dir: Path) -> None:
    """Print a short confirmation to stdout."""
    facts = result.facts
    s = facts.structure
    d = facts.dependencies
    print(f"\nAnalyzed: {result.target}")
    print(f"Reports written to: {out_dir}\n")
    for p in result.reported_files if hasattr(result, "reported_files") else result.reports:
        print(f"  - {p.name}")
    print()
    print("Quick read:")
    print(f"  Source files : {s.source_file_count}")
    print(f"  Total LOC    : {s.total_loc:,}")
    if s.primary_language:
        print(f"  Primary lang : {s.primary_language}")
    print(f"  Dependencies : {d.count}")
    print(f"  Entry points : {len(s.entry_points)}")
    print(f"  Tests        : {'yes' if s.has_tests else 'no'}")
    print()
    print(f"Start here: {out_dir / 'EXECUTIVE_SUMMARY.md'}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-archaeologist",
        description="Point it at an abandoned repo. Get an opinionated briefing in seconds.",
    )
    parser.add_argument("--version", action="version", version=f"repo-archaeologist {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze_p = sub.add_parser("analyze", help="Analyze a local path or GitHub URL.")
    analyze_p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Local directory path or GitHub URL. Defaults to the current directory.",
    )
    analyze_p.add_argument(
        "--out-dir",
        default=None,
        help="Where to write reports. Defaults to the target directory (or cwd for remote URLs).",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        target, cloned, tmp_to_clean = _resolve_target(args.target)

        # Default out dir: target dir for local, cwd for cloned repos
        if args.out_dir:
            out_dir = Path(args.out_dir).expanduser().resolve()
        elif cloned:
            out_dir = Path.cwd()
        else:
            out_dir = target

        try:
            result = analyze(target, out_dir=out_dir)
            result.cloned = cloned
            _print_summary(result, out_dir)
        finally:
            if tmp_to_clean:
                shutil.rmtree(tmp_to_clean, ignore_errors=True)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
