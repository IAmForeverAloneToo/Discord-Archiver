# Command reference

[Back to the overview](../README.md) · [User guide](USER_GUIDE.md)

Read the [account-risk disclaimer](../DISCLAIMER.md) before any command that connects to Discord. The author and contributors accept no responsibility for account restrictions or other consequences, to the maximum extent permitted by law.

From the source folder, use `python -m discord_archiver` on Windows or `python3 -m discord_archiver` on macOS/Linux. With a native download, use `Discord-Archiver.exe` on Windows or `./Discord-Archiver` on macOS/Linux instead.

| Command | Purpose | Connects to Discord? |
| --- | --- | --- |
| `gui` | Open the window | When you load chats or start an online operation |
| `list` | Show open direct chats | Yes |
| `export` | Save messages and attachments | Yes |
| `retry-media` | Retry missing attachments | Yes |
| `render` | Rebuild readable copies from saved data | No |
| `fix-media` | Correct extensions and collapse byte-identical files | No |
| `search "words"` | Search saved messages | No |
| `serve` | Browse the saved archive on this computer | No |
| `selftest` | Run offline checks with temporary data | No |

For example, on macOS or Linux:

```sh
python3 -m discord_archiver export --only --name "Example"
python3 -m discord_archiver search "search words"
```

## Common export options

| Option | Effect |
| --- | --- |
| `--out PATH` | Choose a save folder. Relative paths are based on the program folder. |
| `--only --name "Example"` | Select a conversation by name. Repeat `--name` for more than one. |
| `--only --user USER_ID` | Select a conversation using a user ID. |
| `--only --channel CHANNEL_ID` | Select a known direct-message channel. |
| `--open-only` | Skip checking closed chats with friends. |
| `--leave-reopened` | Leave reopened chats in the Discord sidebar. |
| `--force` | Walk older history again and refresh messages that changed. |
| `--no-media` | Save message data without downloading attachments. |
| `--max-file-mb 100` | Skip files larger than 100 MB. The default has no limit. |
| `--include-external` | Allow downloads from external media hosts as well as Discord. |

Use `--help` after a command for its full option list. Keep credentials in the token file or an environment variable; avoid `--token`, which can leave a credential in shell history.
