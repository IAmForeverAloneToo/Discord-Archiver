# Discord Archiver

Save your own Discord direct messages, group chats, and shared files to a folder on your computer. Browse your saved conversations offline, with readable messages, replies, pictures, and attachments.

[Download v1.0.0](https://github.com/IAmForeverAloneToo/Discord-Archiver/releases/tag/v1.0.0) · [User guide](docs/USER_GUIDE.md) · [MIT license](LICENSE)

> [!WARNING]
> **Using this program can result in your Discord account being suspended, disabled, or terminated.** Discord prohibits automating normal user accounts outside its supported bot/OAuth2 APIs. This program uses a normal user account and is not approved by or affiliated with Discord. See [Discord's policy](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots).
>
> **Use entirely at your own risk.** To the maximum extent permitted by applicable law, the author and contributors accept no responsibility or liability for account restrictions, account loss, lost data, or any other consequences of using this software. No setting, request delay, or feature makes it exempt from Discord's rules. See the [full disclaimer](DISCLAIMER.md).

## What it does

- Saves one-to-one DMs and group DMs, including shared images, video, audio, stickers, and custom emoji.
- Lets you choose specific chats or copy all available direct chats.
- Creates an offline conversation viewer and readable transcripts.
- Keeps completed pages so an interrupted export can resume.
- Can retry missing attachments and refresh edited messages.

It does not export server channels, recover deleted messages, or record calls. It does not send chat messages. Checking a closed DM can temporarily reopen it in your Discord sidebar.

## Download and start

Open the [v1.0.0 release](https://github.com/IAmForeverAloneToo/Discord-Archiver/releases/tag/v1.0.0), expand **Assets**, and choose your platform. No Git clone is needed.

| Your system | Download | After extracting |
| --- | --- | --- |
| Windows, 64-bit Intel/AMD | `Discord-Archiver-v1.0.0-Windows-x64.zip` | Open `Discord-Archiver.exe` |
| macOS, Apple silicon | `Discord-Archiver-v1.0.0-macOS-arm64.zip` | Open `Discord-Archiver` |
| macOS, Intel | `Discord-Archiver-v1.0.0-macOS-x64.zip` | Open `Discord-Archiver` |
| Linux, 64-bit Intel/AMD | `Discord-Archiver-v1.0.0-Linux-x64.tar.gz` | Run `./Discord-Archiver` in the extracted folder |
| Linux, ARM64 | `Discord-Archiver-v1.0.0-Linux-arm64.tar.gz` | Run `./Discord-Archiver` in the extracted folder |

The native downloads include Python. Keep the extracted folder somewhere you can write files, such as your Documents folder. On macOS or Linux, a terminal window may remain open while the program runs. Linux needs a graphical desktop for the window; terminal commands also work without one.

The executables are not signed with an Apple or Windows application certificate. Your operating system may ask you to review an unfamiliar application. The Git commit and release tag are separately signed; that does not remove operating-system warnings.

**Prefer the source version?** Download `Discord-Archiver-v1.0.0-source.zip`. It works on Windows, macOS, and Linux with Python 3.10 or newer; no third-party Python packages are required. Follow the [source setup steps](docs/USER_GUIDE.md#run-from-source).

## Your first export

1. Read the warning above before continuing.
2. Open the program and enter the token from your own Discord session. The [user guide](docs/USER_GUIDE.md#provide-your-token) explains where to find it. A bot token will not work.
3. Choose a save folder. The default is `archive` beside the program.
4. To copy specific chats, check **Only selected chats**, select **Load chats**, and check the conversations you want.
5. Select **Start**. Use **Stop** to pause after the current page.
6. When finished, select **Browse archive**, or open `archive/index.html` in your browser.

Large histories can take hours. Run one copy of the program at a time. If an export stops, use the same save folder on the next run.

## Keep your data private

Your token grants access to your Discord account. Never share it or include it in an issue, screenshot, commit, or release. If you save it, the program keeps it in `token.txt` beside the program.

The archive contains private messages, account identifiers, and downloaded files. Keep it private and back it up securely. The program connects to Discord and, if you enable external downloads, to the relevant media hosts; it does not upload your archive to a separate service.

## Help and further reading

- [User guide](docs/USER_GUIDE.md): setup, token instructions, missing files, and troubleshooting.
- [Command reference](docs/COMMANDS.md): optional terminal commands.
- [Disclaimer](DISCLAIMER.md): account risk and responsibility.
- [Security](SECURITY.md): private data and vulnerability reports.
- [Contributing](CONTRIBUTING.md): tests and release builds.

For a problem with the program, [open an issue](https://github.com/IAmForeverAloneToo/Discord-Archiver/issues) with the version, operating system, and a short description. Remove all tokens, personal paths, names, IDs, and private message content first.
