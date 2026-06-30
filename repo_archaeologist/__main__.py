"""Allow `python -m repo_archaeologist` to run the CLI."""

import sys

from repo_archaeologist.cli import main

if __name__ == "__main__":
    sys.exit(main())
