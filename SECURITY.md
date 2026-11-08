# Security and privacy

## Protect your account and archive

- Keep `token.txt`, signing keys, and saved credentials private.
- Never publish an archive, attachment, message, contact list, or account file.
- Remove names, IDs, local paths, and private content before sharing logs or screenshots.
- Only access your own account and data you are entitled to access.

The default archive folder, token file, session metadata, and build outputs are excluded from version control. If you choose another output folder inside a checkout, add it to `.gitignore` before committing anything.

The program sends authenticated requests to Discord. Media downloads do not include the account token. External embed downloads are optional. The browser viewer listens only on this computer and forces active attachment formats to download instead of executing as pages.

These precautions do not remove Discord's account-policy risk. Read the [disclaimer](DISCLAIMER.md).

## Report a vulnerability

Use GitHub's private vulnerability reporting feature when available. Otherwise, open an issue with a general description and request a private reporting route. Do not post credentials, private conversations, or sensitive exploit details publicly.

Include the program version, operating system, and reproduction steps using invented sample data. Only the latest published version is supported for security fixes.
