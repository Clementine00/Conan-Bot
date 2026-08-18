FROM python:3.12-slim

# ffmpeg decodes the audio stream. libstdc++6 is the only shared library the
# Node binary copied in below needs beyond the base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp runs YouTube's JS challenge solver (see YDL_OPTIONS in cogs/music.py).
# As of yt-dlp 2026.07.04 NodeJsRuntime.MIN_SUPPORTED_VERSION is (22, 0, 0),
# but Debian trixie only packages Node 20.19. yt-dlp then treats the runtime as
# unsupported, falls back to JS-less clients, and playback dies with HTTP 403 on
# the returned stream URLs. Pin a new enough Node instead of the distro package.
COPY --from=node:24-trixie-slim /usr/local/bin/node /usr/local/bin/node

# Fail the build rather than playback if yt-dlp raises the floor again.
RUN node --version && node -e "if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('yt-dlp requires Node >= 22')"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py ./
COPY cogs/ ./cogs/

# yt-dlp caches the EJS challenge solver it fetches from GitHub under here.
ENV XDG_CACHE_HOME=/app/.cache \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/.cache \
    && chown -R bot:bot /app
USER bot

CMD ["python", "bot.py"]
