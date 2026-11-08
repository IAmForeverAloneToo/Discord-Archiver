"""Validate the exact files intended for a public checkout or source archive."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from build_release import PUBLIC_FILES, ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Require the Git index to match the manifest")
    args = parser.parse_args()
    if args.staged:
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
        if set(filter(None, names)) != set(PUBLIC_FILES):
            raise SystemExit("The Git index does not match the public-file manifest.")
    checks = {
        "private key": re.compile(rb"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----"),
        "credential": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|mfa\.[A-Za-z0-9_-]{20,})\b"),
        "session credential": re.compile(rb"\b[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,}\b"),
        "personal path": re.compile(rb"(?:[A-Za-z]:[/\\][Uu]sers[/\\]|/Users/|/home/)[^\s\"'<>]+"),
        "personal email": re.compile(rb"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    }
    failures = []
    for name in PUBLIC_FILES:
        data = (ROOT / name).read_bytes()
        if name == "scripts/check_public_files.py":
            continue
        for label, pattern in checks.items():
            for match in pattern.finditer(data):
                if label == "personal email" and match.group().endswith(b"@users.noreply.github.com"):
                    continue
                failures.append(f"{name}: {label}")
    if failures:
        raise SystemExit("\n".join(sorted(set(failures))))
    print(f"Checked {len(PUBLIC_FILES)} public files; no blocked content found.")


if __name__ == "__main__":
    main()
