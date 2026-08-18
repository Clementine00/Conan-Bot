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

## CI/CD

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) is a single gated pipeline.

On every push and pull request to `main`:

- **Lint** — `ruff check` and `ruff format --check`
- **Build** — installs dependencies on Python 3.11 and 3.12, byte-compiles the
  sources, and imports the music cog as a smoke test
- **Secret scan** — `scripts/check_secrets.sh` plus [gitleaks](https://github.com/gitleaks/gitleaks)
  over both the working tree and the full commit history

On pushes to `main`, and only if all three of the above pass:

- **Publish** — builds the image and pushes it to
  `ghcr.io/clementine00/conan-bot`, tagged `latest` and with the short commit SHA
- **Deploy** — SSHes into the Ubuntu host and restarts the container on the new image

## Deployment

The bot ships as a Docker image. On the Ubuntu host:

```bash
mkdir -p ~/conan-bot && cd ~/conan-bot
# copy docker-compose.yml from this repo into that directory
nano .env          # DISCORD_TOKEN=... and optionally GUILD_ID=...
chmod 600 .env

# GHCR is private, so authenticate once with a PAT that has read:packages
echo "$GHCR_TOKEN" | docker login ghcr.io -u Clementine00 --password-stdin

docker compose pull
docker compose up -d
docker compose logs -f
```

### Automatic deploys

The `deploy` job stays skipped until you opt in. To enable it, under
**Settings → Secrets and variables → Actions**:

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `DEPLOY_ENABLED` | `true` |
| Secret | `DEPLOY_HOST` | Server hostname or IP |
| Secret | `DEPLOY_USER` | SSH user |
| Secret | `DEPLOY_SSH_KEY` | Private half of a deploy-only SSH keypair |
| Secret | `DEPLOY_PATH` | Directory holding `docker-compose.yml`, e.g. `/home/you/conan-bot` |
| Secret | `GHCR_PULL_TOKEN` | PAT with `read:packages`, used by the host to pull |

Generate a dedicated keypair rather than reusing a personal one, and put only its
public half in the server's `~/.ssh/authorized_keys`:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ./deploy_key -N ""
```

The `.env` on the server is the only place the bot token lives. It is never baked
into the image and never passed through Actions.

## If the token ever leaks

Reset it immediately in the Discord Developer Portal (**Bot → Reset Token**). Rotating
the token invalidates the old one; removing it from git history alone is not enough,
because the value may already have been copied.
