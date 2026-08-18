FROM python:3.12-slim

# ffmpeg decodes the audio stream; nodejs runs yt-dlp's YouTube JS challenge
# solver (see YDL_OPTIONS in cogs/music.py) — without it some formats drop out.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs ca-certificates \
    && rm -rf /var/lib/apt/lists/*

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
