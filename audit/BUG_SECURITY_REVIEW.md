# Security and reliability review

The following issues were addressed before the v1.0.0 release. The regression suite verifies the corrected behavior using temporary archives and invented sample data.

| Area | Current behavior |
| --- | --- |
| Media credentials | Hostnames are checked at domain boundaries. Downloads never send the account token. |
| Redirects | HTTPS is required on every redirect. Credentials are removed when the destination origin changes. |
| Active attachments | SVG, HTML, and other untrusted documents download with restrictive response headers. |
| Viewer links | Numeric channel routes resolve to the correct chat folder, including folders named after contacts. |
| Duplicate files | Different URL queries and ports remain distinct. Files are removed only when content hashes match. |
| Extension repair | Filename collisions preserve different contents under separate names, including concurrent repairs. |
| Edited messages | Changed records are saved, and previews, search, and the live viewer use the latest version. |
| Pagination | Unexpected pagination stops leave history incomplete and resumable. |
| Memory use | Format detection reads only the first 16 bytes of each file. |

## Run the checks

```sh
python -m discord_archiver selftest
python -W error::ResourceWarning audit/reproduce_findings.py
```

Use `python3` where required by your system. No account credentials or private archive are needed. A passing regression check confirms the repaired behavior.

Tests cover download requests, redirect handling, file preservation, local HTTP responses, updated viewer data, and resumable history. They do not establish that Discord permits the program, guarantee an account will remain available, or exercise live authenticated exports. See the [security guidance](../SECURITY.md) and [account disclaimer](../DISCLAIMER.md).
