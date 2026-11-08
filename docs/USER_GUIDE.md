# User guide

[Back to the overview](../README.md)

> [!WARNING]
> This program automates a normal Discord account, which Discord prohibits. Your account can be disabled or terminated. Use at your own risk; the author and contributors accept no responsibility for these consequences, to the maximum extent permitted by law. Read the [full disclaimer](../DISCLAIMER.md) first.

## Choose a download

Get the archive for your operating system from [Releases](https://github.com/IAmForeverAloneToo/Discord-Archiver/releases). Extract it before starting the program. Do not run it from inside the compressed download or a folder where you cannot save files.

The native downloads include the runtime. Windows builds target 64-bit Intel/AMD systems. macOS has separate Apple silicon and Intel downloads. Linux has separate x64 and ARM64 downloads, built on Ubuntu 22.04; other distributions need compatible system libraries. The graphical window requires a desktop session.

On macOS, if the system blocks the unfamiliar executable, review the downloaded file and use the system's normal **Privacy & Security** approval flow if you choose to trust it. On Linux, if execute permission was lost while extracting, run `chmod +x Discord-Archiver` in its folder. Do not disable system security protections globally.

## Run from source

Use this option on Windows, macOS, or Linux if you prefer the Python source or a native download is unsuitable.

1. Install Python 3.10 or newer. Windows and macOS users can use [python.org](https://www.python.org/downloads/).
2. Download the source ZIP from the release and extract it.
3. Open the window using the option for your system:

| System | Start the window |
| --- | --- |
| Windows | Double-click `launch-gui.vbs`, or run `python -m discord_archiver gui` from the extracted folder |
| macOS | Run `sh launch.command` from the extracted folder |
| Linux | Run `sh run.sh` from the extracted folder |

No third-party Python packages need to be installed. The window uses Tkinter. If it is missing on Linux, install your distribution's Tkinter package for your Python version; on Ubuntu/Debian this is usually `python3-tk`. You can use the command-line interface without Tkinter.

## Provide your token

A token is a credential for your own signed-in Discord session. Anyone with it may be able to use your account. Never send it to someone else or post it in an issue.

1. Open [Discord in your browser](https://discord.com/app) and sign in to your own account.
2. Open the browser's developer tools and select **Network**. In most desktop browsers, press **F12** or use the browser menu.
3. Reload Discord. Select a request to `discord.com/api/`.
4. Under its request headers, find **Authorization** and copy only its value.
5. Paste it into the program's **Token** field. Do not add `Authorization`, `Bot`, or `Bearer`.

If you select **Save token to token.txt**, the program writes the token beside the program for later runs. Leave that option off if you do not want a saved token. For terminal use, copy `token.txt.example` to `token.txt` and put the token on its own line instead of a command-line argument.

If the token is rejected, sign in again and obtain the current value. If you believe it has been exposed, secure your Discord account and change your password to invalidate the old session credential.

## Choose conversations

For a few conversations, enable **Only selected chats**, choose **Load chats**, and check the rows you want. The **Selected** line shows what will be copied. The filter helps you find usernames and group names.

For all available direct chats, leave **Only selected chats** off. **Include closed chats with friends** also checks existing conversations with friends that are missing from the sidebar. Those chats may appear temporarily and are hidden again after a successful copy, unless **Leave reopened chats in the sidebar** is enabled.

Discord does not provide a complete list of closed chats with people who are not friends. To include one, enable **Developer Mode** in Discord's Advanced settings, copy that person's user ID, and paste it into **Extra user IDs**. A group you have left may remain inaccessible even if you know its channel ID.

## Stop, resume, and browse

Choose **Stop** to stop after the current page. The program may need to finish a request or file download first. Closing the window also requests a stop. Use the same save folder to resume.

Select **Browse archive** for the local browser viewer, or open `archive/index.html` directly for the offline copy. Each chat also has a `transcript.md` file. The complete saved message data is in `messages.jsonl`; most users will not need to open it.

Messages are refreshed when they are fetched again. Normal exports check recent history. The optional `export --force` command walks older history to refresh older edits too.

## Missing or mislabeled files

**Retry missing files** requests fresh attachment links and tries again. Some files have been removed from Discord and cannot be recovered. A previously deleted message or call recording cannot be reconstructed by this program.

**Fix saved files** checks extensions and removes only duplicate files with matching contents. Different files are preserved even when their names collide. This works offline. Keep a separate backup of archives you cannot replace.

SVG, HTML, and other active file types are downloaded as attachments by the local viewer. Supported pictures, audio, and video display inline.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Windows launcher cannot find Python | Install Python 3.10+ or use the native Windows download. The `python -m discord_archiver gui` command is an alternative if the `py` launcher is unavailable. |
| No window appears on Linux | Use a graphical desktop and check that Tkinter is available, or use terminal commands. |
| Token rejected | Copy the current Authorization value from your own Discord session. Bot tokens cannot access personal DMs. |
| Files or messages are missing | Retry the export, check the selection and save folder, and use Retry missing files. Deleted or inaccessible content may be unavailable. |
| Rate-limit message | Allow the program to wait. Run only one copy. Delays do not remove the account-policy risk. |
| Save fails | Extract the download and move the folder somewhere writable. Check free disk space. |

See the [command reference](COMMANDS.md) for optional terminal features. When requesting help, remove all credentials and private information from error messages and screenshots.
