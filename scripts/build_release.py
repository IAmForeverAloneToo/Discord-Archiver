"""Create release archives from an explicit public-file manifest."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from discord_archiver import __version__


PUBLIC_FILES = (
    ".gitattributes", ".gitignore", ".github/workflows/release-build.yml",
    "README.md", "LICENSE", "DISCLAIMER.md", "SECURITY.md", "CONTRIBUTING.md",
    "requirements.txt", "requirements-build.txt", "token.txt.example",
    "archive_dms.py", "desktop.py", "run.bat", "launch-gui.vbs", "run.sh", "launch.command",
    "discord_archiver/__init__.py", "discord_archiver/__main__.py",
    "discord_archiver/client.py", "discord_archiver/export.py", "discord_archiver/gateway.py",
    "discord_archiver/gui.py", "discord_archiver/media.py", "discord_archiver/render.py",
    "discord_archiver/selftest.py", "discord_archiver/util.py", "discord_archiver/viewer.py",
    "audit/BUG_SECURITY_REVIEW.md", "audit/reproduce_findings.py",
    "docs/USER_GUIDE.md", "docs/COMMANDS.md", "docs/RELEASE_NOTES.md",
    "scripts/build_release.py", "scripts/check_public_files.py", "scripts/smoke_native.py",
)


def source_archive() -> Path:
    destination = ROOT / "dist" / f"Discord-Archiver-v{__version__}-source.zip"
    destination.parent.mkdir(exist_ok=True)
    prefix = f"Discord-Archiver-v{__version__}"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in PUBLIC_FILES:
            path = ROOT / name
            info = zipfile.ZipInfo(f"{prefix}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if path.suffix in {".sh", ".command"} else 0o644
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, path.read_bytes())
    return destination


def native_archive(label: str) -> Path:
    system = platform.system()
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    expected = f"{'macOS' if system == 'Darwin' else system}-{arch}"
    if label != expected:
        raise SystemExit(f"Build {label} on {label}; this machine builds {expected}.")
    name = "Discord-Archiver"
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--console", "--name", name, "--distpath", "dist/native", "--workpath", "build/native",
        "--specpath", "build", "--noupx",
    ]
    if system == "Windows":
        command += ["--hide-console", "hide-early"]
    command.append("desktop.py")
    subprocess.run(command, cwd=ROOT, check=True)
    executable = ROOT / "dist" / "native" / (name + (".exe" if system == "Windows" else ""))
    subprocess.run([str(executable), "--version"], check=True, timeout=60)
    subprocess.run([str(executable), "selftest"], check=True, timeout=120)
    prefix = f"Discord-Archiver-v{__version__}-{label}"
    with tempfile.TemporaryDirectory() as temporary:
        package = Path(temporary) / prefix
        package.mkdir()
        shutil.copy2(executable, package / executable.name)
        for name in ("README.md", "LICENSE", "DISCLAIMER.md", "SECURITY.md", "token.txt.example"):
            shutil.copy2(ROOT / name, package / name)
        shutil.copytree(ROOT / "docs", package / "docs")
        licenses = package / "licenses"
        licenses.mkdir()
        python_license = next((path for path in (
            Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
            Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt",
        ) if path.is_file()), None)
        if python_license is None:
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            url = f"https://raw.githubusercontent.com/python/cpython/{version}/LICENSE"
            with urllib.request.urlopen(url, timeout=30) as response:
                (licenses / "PYTHON-LICENSE.txt").write_bytes(response.read())
        else:
            shutil.copy2(python_license, licenses / "PYTHON-LICENSE.txt")
        (licenses / "README.txt").write_text(
            "This download bundles Python and Tcl/Tk using PyInstaller.\n"
            "Python license: PYTHON-LICENSE.txt\n"
            "Tcl/Tk licenses are also included with the bundled runtime data.\n"
            "PyInstaller's distribution exception permits distributing bundled applications.\n"
            "https://pyinstaller.org/en/stable/license.html\n", encoding="utf-8"
        )
        if system == "Linux":
            destination = ROOT / "dist" / f"{prefix}.tar.gz"
            with tarfile.open(destination, "w:gz") as archive:
                archive.add(package, arcname=prefix)
        else:
            destination = ROOT / "dist" / f"{prefix}.zip"
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(package.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(package.parent).as_posix())
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=("Windows-x64", "macOS-x64", "macOS-arm64", "Linux-x64", "Linux-arm64"))
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args()
    if not args.source_only and not args.label:
        parser.error("choose --label or --source-only")
    destination = source_archive() if args.source_only else native_archive(args.label)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_name(destination.name + ".sha256").write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    print(f"Created {destination.name}")


if __name__ == "__main__":
    main()
