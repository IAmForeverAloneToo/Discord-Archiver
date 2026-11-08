# Contributing

Keep changes focused and use invented sample data in tests. Never commit account credentials, downloaded conversations, personal paths, signing keys, or local session history.

## Check a change

The source requires Python 3.10 or newer. No third-party Python packages are needed to run the program or its tests.

```sh
python -m discord_archiver selftest
python -W error::ResourceWarning audit/reproduce_findings.py
python -m compileall -q discord_archiver audit
```

Use `python3` instead of `python` where required by your system. These checks use temporary fixtures and dummy credentials. They do not need a real account or archive.

Run the window once to check interface changes. A graphical desktop and Tkinter are needed for that check. Avoid making live account calls merely to validate a local change.

## Documentation

Keep the main README focused on downloading and starting the program. Put detailed setup instructions in the user guide and optional flags in the command reference. Preserve the account-policy warning and responsibility disclaimer.

## Release builds

The release workflow builds native packages on Windows, macOS, and Linux runners, then tests each package before uploading it as a build artifact. It does not need account credentials or a private archive. Python is bundled in native packages; source users do not need the build tool.

To reproduce a native package on the same operating system and architecture:

```sh
python -m pip install -r requirements-build.txt
python scripts/build_release.py --label Windows-x64
```

Use the appropriate platform label: `Windows-x64`, `macOS-arm64`, `macOS-x64`, `Linux-x64`, or `Linux-arm64`. Builds are created under `dist/`, which is excluded from Git. The workflow runs on demand so a maintainer can review and publish tested artifacts with release notes and checksums.
