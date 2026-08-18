# Discord Music Bot

A Discord music bot built with [discord.py](https://discordpy.readthedocs.io/) and
[yt-dlp](https://github.com/yt-dlp/yt-dlp). Streams audio from YouTube into a voice
channel with a per-guild queue.

## Commands

| Command | Description |
| --- | --- |
| `/play <query>` | Play a song from a YouTube URL or search keywords |
| `/pause` | Pause the current song |
| `/resume` | Resume the paused song |
| `/skip` | Skip the current song |
| `/stop` | Stop playback, clear the queue, and disconnect |
| `/queue` | Show the current queue |
| `/nowplaying` | Show the currently playing song |
| `/remove <position>` | Remove a song from the queue by position |
| `/shuffle` | Shuffle the queue |

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) on your `PATH`
- [Node.js](https://nodejs.org/) — yt-dlp runs YouTube's JS challenge solver through it

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill it in:

```
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_server_id_here
```

`DISCORD_TOKEN` comes from the [Discord Developer Portal](https://discord.com/developers/applications)
under **Bot → Reset Token**. `GUILD_ID` is optional — set it to sync slash commands to
one server instantly during development; leave it blank to sync globally, which can take
up to an hour to propagate.

**`.env` is gitignored and must stay that way.** Anyone holding the token can control the bot.

## Running

```bash
python bot.py
```

On Windows you can also double-click `start_bot.bat`.

## Development

Lint and format with [ruff](https://docs.astral.sh/ruff/):

```bash
pip install ruff
ruff check .
ruff format .
```

Check that no credentials have crept into tracked files:

```bash
bash scripts/check_secrets.sh
```

## CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push and pull request
to `main`:

- **Lint** — `ruff check` and `ruff format --check`
- **Build** — installs dependencies on Python 3.11 and 3.12, byte-compiles the sources,
  and imports the music cog as a smoke test
- **Secret scan** — `scripts/check_secrets.sh` plus [gitleaks](https://github.com/gitleaks/gitleaks)
  over both the working tree and the full commit history

## If the token ever leaks

Reset it immediately in the Discord Developer Portal (**Bot → Reset Token**). Rotating the
token invalidates the old one; removing it from git history alone is not enough, because
the value may already have been copied.
