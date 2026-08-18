# Discord Music Bot — Complete Planning Document

---

## 1. Project Overview

### What We're Building
A Discord bot written in Python that joins voice channels and plays music from YouTube. Users interact with it through Discord's slash commands (e.g., `/play`, `/skip`, `/queue`).

### Feature Scope
- Play audio from a YouTube URL
- Search YouTube by keywords and play the top result
- Pause, resume, skip, and stop playback
- Song queue: view, remove, shuffle
- Now-playing display with song info
- Works in multiple servers simultaneously

### What's NOT in Scope (For Now)
- Spotify/SoundCloud support
- Playlists
- Volume control
- 24/7 hosting
- Database or persistent data
- Web dashboard

---

## 2. Full Tech Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Language | Python | 3.10+ | Core language. 3.10+ required for discord.py 2.x and modern syntax. |
| Discord Library | discord.py[voice] | >= 2.3.0 | Wraps the Discord API. The `[voice]` extra installs PyNaCl for voice encryption. |
| YouTube Extraction | yt-dlp | >= 2024.0.0 | Extracts audio stream URLs from YouTube. Actively maintained fork of youtube-dl. |
| Audio Processing | FFmpeg | Latest stable | Decodes and streams audio to Discord. Required by discord.py for voice. |
| Environment Config | python-dotenv | >= 1.0.0 | Loads the bot token from a `.env` file so secrets stay out of code. |

### Why These Choices?

**discord.py** — The most mature Python Discord library. Has built-in voice support, slash command handling, and a cog system for organizing code. Large community and extensive documentation.

**yt-dlp** — The standard tool for extracting media from YouTube. It doesn't download files to disk — we use it to get a direct audio stream URL, which FFmpeg then streams in real time.

**FFmpeg** — Industry-standard audio/video tool. discord.py uses it under the hood to convert audio into the Opus format that Discord requires.

**python-dotenv** — Keeps your bot token in a `.env` file instead of hardcoded in your script. Simple and widely used.

---

## 3. Prerequisites & Setup

### 3A. Create a Discord Bot Application

1. Go to **https://discord.com/developers/applications**
2. Click **"New Application"**, give it a name (e.g., "Music Bot"), click Create
3. Go to the **Bot** tab on the left sidebar
4. Click **"Reset Token"**, then **copy the token** — you'll need it later
   - **IMPORTANT:** Never share this token. Anyone with it can control your bot.
5. Under **Privileged Gateway Intents**, you do NOT need to enable anything for basic music functionality
6. Go to **OAuth2 > URL Generator**
7. Under **Scopes**, check:
   - `bot`
   - `applications.commands`
8. Under **Bot Permissions**, check:
   - `Connect` (join voice channels)
   - `Speak` (play audio)
   - `Send Messages`
   - `Embed Links` (for rich now-playing/queue displays)
9. Copy the generated URL at the bottom, paste it into your browser
10. Select your server and authorize the bot

### 3B. Install FFmpeg on Windows

1. Go to **https://www.gyan.dev/ffmpeg/builds/**
2. Download **"ffmpeg-release-essentials.zip"**
3. Extract the zip to a permanent location (e.g., `C:\ffmpeg`)
4. Add `C:\ffmpeg\bin` to your system PATH:
   - Search "Environment Variables" in Windows Start
   - Click "Edit the system environment variables"
   - Click "Environment Variables..."
   - Under "System variables", find `Path`, click Edit
   - Click "New", paste `C:\ffmpeg\bin`
   - Click OK on all dialogs
5. **Verify:** Open a NEW terminal and run:
   ```
   ffmpeg -version
   ```
   You should see version info, not "command not found".

### 3C. Set Up Python Environment

```bash
# Navigate to the project folder
cd "C:\Users\<your-username>\Desktop\Repos\Discord Bot"

# Create a virtual environment
python -m venv venv

# Activate it (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3D. Create the .env File

Create a file called `.env` in the project root with this single line:
```
DISCORD_TOKEN=paste_your_token_here
```

Replace `paste_your_token_here` with the token you copied in step 3A.

---

## 4. Architecture & Project Structure

### File Tree

```
Discord Bot/
├── bot.py                 # Entry point — bot setup, cog loading, startup
├── cogs/
│   └── music.py           # Music cog — all commands, queue logic, audio streaming
├── .env                   # Bot token (DO NOT share or commit)
├── .gitignore             # Excludes .env, __pycache__, venv from git
├── requirements.txt       # Python dependencies
└── PLAN.md                # This document
```

### How discord.py Cogs Work

A **cog** is a class that groups related commands and event listeners. Think of it as a plugin or module.

- `bot.py` creates the bot and loads cogs
- `cogs/music.py` defines a `Music` class with all music-related commands
- The cog registers its slash commands with Discord automatically when loaded
- This separation keeps `bot.py` clean and makes it easy to add/remove features

### Data Flow

```
User types /play "song name"
        |
        v
Discord API sends interaction to bot
        |
        v
music.py receives the command
        |
        v
yt-dlp searches YouTube, extracts the direct audio stream URL
        |
        v
discord.py tells FFmpeg to stream that URL
        |
        v
FFmpeg decodes the audio and sends Opus packets to Discord
        |
        v
Audio plays in the voice channel
```

### In-Memory Data (No Database)

The bot stores everything in Python dictionaries, keyed by server (guild) ID:

- **`self.queues`** — `dict[int, list[dict]]` — Each server gets its own song queue
- **`self.now_playing`** — `dict[int, dict | None]` — Tracks what's currently playing per server

When the bot restarts, all queues are lost. This is fine for a personal bot.

---

## 5. Implementation Plan (Step-by-Step)

Each step builds on the previous one and has a testable checkpoint.

### Step 1: Project Scaffolding
**Create:** `requirements.txt`, `.env`, `.gitignore`, `cogs/` directory, empty `bot.py`

**Checkpoint:** Files exist, `pip install -r requirements.txt` succeeds without errors.

**Debug if it fails:**
- `pip` not found → Make sure venv is activated (`venv\Scripts\activate`)
- Package not found → Check spelling in requirements.txt
- PyNaCl build fails → Install Microsoft Visual C++ Build Tools, or try `pip install PyNaCl` separately

---

### Step 2: Minimal Bot That Connects
**Create:** `bot.py` with:
- Load token from `.env`
- Create bot instance
- `on_ready` event that prints to console
- Sync slash commands

**Checkpoint:** Run `python bot.py`. Console should print `Logged in as YourBotName`. The bot should appear online in Discord.

**Debug if it fails:**
- `LoginFailure` / "Improper token" → Token is wrong. Re-copy it from the Developer Portal. Make sure there are no extra spaces in `.env`.
- `ModuleNotFoundError: No module named 'discord'` → Venv not activated, or dependencies not installed.
- Bot is online but no slash commands appear → Commands haven't synced yet. Slash command sync can take up to 1 hour globally. For instant testing, sync to a specific guild (covered in debugging section).

---

### Step 3: Bot Joins a Voice Channel
**Create:** A basic `/join` command in `cogs/music.py` that:
- Checks if the user is in a voice channel
- Connects the bot to that channel

Also add a `/leave` command.

**Checkpoint:** Use `/join` — bot appears in your voice channel. Use `/leave` — bot disconnects.

**Debug if it fails:**
- "You must be in a voice channel" → You need to be in a voice channel before using the command.
- `ClientException: Already connected` → Bot is already in a channel. Handle this by moving it instead.
- Bot joins but immediately disconnects → Check for exceptions in the console. Possibly a permissions issue.

---

### Step 4: Bot Plays Audio from a Direct URL
**Create:** A basic `/play` command that:
- Joins the voice channel (if not already in one)
- Uses yt-dlp to extract the audio URL from a YouTube link
- Uses FFmpegPCMAudio to stream it

No queue yet — just play one song.

**Checkpoint:** Use `/play https://www.youtube.com/watch?v=dQw4w9WgXcQ` — you hear audio in the voice channel.

**Debug if it fails:**
- `FFmpegNotFound` / "ffmpeg was not found" → FFmpeg is not on PATH. Re-do step 3B. You MUST open a new terminal after editing PATH.
- No audio but no errors → Check that `options: "-vn"` is set in FFMPEG_OPTIONS. Check that the URL from yt-dlp is valid (test it in a browser).
- `yt_dlp.utils.DownloadError` → The video might be age-restricted, region-locked, or a live stream. Try a different video.
- Audio is robotic/choppy → Your internet connection or CPU is struggling. Normal for very slow connections.

---

### Step 5: Add Queue System
**Create:** Queue logic:
- `/play` adds to queue if something is already playing
- `play_next()` callback auto-advances to the next song
- `/skip` stops current song (triggering `play_next`)
- `/stop` clears queue and disconnects
- `/pause` and `/resume`

**Checkpoint:** Queue 3 songs. First plays immediately. `/skip` advances. After last song, bot goes idle. `/stop` clears everything.

**Debug if it fails:**
- Bot stops after first song, doesn't play next → The `after` callback in `voice_client.play()` runs in a different thread. You must use `asyncio.run_coroutine_threadsafe()` to schedule the next song on the event loop.
- `/skip` does nothing → Make sure you're calling `voice_client.stop()`, not `voice_client.pause()`. `stop()` triggers the `after` callback.
- Songs play over each other → You're calling `play()` while something is already playing. Check `voice_client.is_playing()` before starting playback.

---

### Step 6: Add YouTube Search
**Create:** Update `/play` to accept keywords (not just URLs):
- If input doesn't start with `http`, treat it as a search query
- yt-dlp's `default_search: "ytsearch"` option handles this automatically

**Checkpoint:** Use `/play never gonna give you up` (no URL) — bot searches YouTube and plays the top result.

**Debug if it fails:**
- Returns wrong song → yt-dlp picks the first YouTube search result. This is usually correct but not always.
- Takes very long → YouTube search via yt-dlp can take 3-8 seconds. Make sure you're using `interaction.response.defer()` before the search.
- `InteractionResponded` error → You're trying to respond to the interaction twice. After `defer()`, use `interaction.followup.send()` instead of `interaction.response.send_message()`.

---

### Step 7: Add Queue Display and Management
**Create:**
- `/queue` — Shows numbered list of queued songs in an embed
- `/remove <position>` — Removes a song by its position number
- `/shuffle` — Randomizes queue order
- `/nowplaying` — Shows current song details

**Checkpoint:** Queue several songs. `/queue` shows them numbered. `/remove 2` removes the second song. `/shuffle` reorders them. `/nowplaying` shows what's playing.

**Debug if it fails:**
- Embed is empty → Check that you're actually adding fields to the embed. Use `embed.add_field()`.
- `/remove` removes the wrong song → Make sure you're converting from 1-indexed (user-facing) to 0-indexed (Python list).
- `/nowplaying` says nothing is playing while audio is going → Check that `self.now_playing[guild_id]` is being set when a song starts.

---

### Step 8: Polish and Edge Cases
**Handle:**
- Bot disconnects if left alone in a voice channel (no one listening)
- Expired stream URLs for songs that sat in queue too long (re-extract at play time)
- Proper error messages for all edge cases
- User tries commands when bot isn't in a channel

**Checkpoint:** Test every edge case listed in the testing checklist (Section 8).

---

## 6. Detailed Command Specifications

### `/play <query>`
| Property | Detail |
|----------|--------|
| Parameter | `query` (string, required) — YouTube URL or search keywords |
| Behavior | 1. Checks user is in a voice channel. 2. Joins if bot isn't already connected. 3. Defers the response. 4. Extracts audio info via yt-dlp. 5. If nothing is playing, starts playback. If something is playing, adds to queue. |
| Response (playing) | "Now playing: **{title}**" |
| Response (queued) | "Added to queue at position #{n}: **{title}**" |
| Error: not in VC | "You need to be in a voice channel to use this command." |
| Error: extraction fails | "Could not find or play that song. Try a different search." |

### `/pause`
| Property | Detail |
|----------|--------|
| Behavior | Pauses current playback |
| Response | "Paused." |
| Error: nothing playing | "Nothing is playing right now." |

### `/resume`
| Property | Detail |
|----------|--------|
| Behavior | Resumes paused playback |
| Response | "Resumed." |
| Error: not paused | "Nothing is paused right now." |

### `/skip`
| Property | Detail |
|----------|--------|
| Behavior | Skips current song. Triggers `play_next()` via the `after` callback. |
| Response | "Skipped **{title}**." |
| Error: nothing playing | "Nothing is playing right now." |

### `/stop`
| Property | Detail |
|----------|--------|
| Behavior | Clears the queue, stops playback, disconnects from voice. |
| Response | "Stopped and disconnected." |
| Error: not connected | "I'm not in a voice channel." |

### `/queue`
| Property | Detail |
|----------|--------|
| Behavior | Displays an embed with the current queue. Shows "Now playing" at top, then numbered upcoming songs with title and who requested each. |
| Response (has songs) | Embed with song list |
| Response (empty) | "The queue is empty." |

### `/remove <position>`
| Property | Detail |
|----------|--------|
| Parameter | `position` (integer, required) — 1-indexed position in queue |
| Behavior | Removes the song at the given position from the queue. |
| Response | "Removed **{title}** from the queue." |
| Error: invalid position | "Invalid position. The queue has {n} songs." |

### `/shuffle`
| Property | Detail |
|----------|--------|
| Behavior | Randomly reorders the queue. Does not affect the currently playing song. |
| Response | "Shuffled the queue ({n} songs)." |
| Error: queue empty | "The queue is empty, nothing to shuffle." |

### `/nowplaying`
| Property | Detail |
|----------|--------|
| Behavior | Shows an embed with the current song's title, YouTube URL, duration, and who requested it. |
| Response (playing) | Rich embed with song info |
| Response (nothing) | "Nothing is playing right now." |

---

## 7. Debugging Process

### 7A. Enable Logging

Add this at the top of `bot.py` to see detailed logs from discord.py:

```python
import logging
logging.basicConfig(level=logging.INFO)

# For even more detail (shows API calls, gateway events):
# logging.basicConfig(level=logging.DEBUG)
```

### 7B. Test yt-dlp Independently

If audio isn't working, test yt-dlp by itself in a Python shell:

```python
import yt_dlp

YDL_OPTIONS = {"format": "bestaudio/best", "noplaylist": True, "quiet": True}

with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
    info = ydl.extract_info("ytsearch:never gonna give you up", download=False)
    if "entries" in info:
        info = info["entries"][0]
    print(info["title"])
    print(info["url"])  # This is the direct audio stream URL
```

If this fails, the problem is yt-dlp or your network, not the bot.

### 7C. Test FFmpeg Independently

Run this in your terminal:

```bash
ffmpeg -version
```

If it says "not recognized", FFmpeg is not on your PATH. Redo section 3B.

To test streaming a URL:

```bash
ffmpeg -i "PASTE_AUDIO_URL_HERE" -f null -
```

If this plays without errors, FFmpeg is working. If it fails, the URL may be expired.

### 7D. Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `LoginFailure: Improper token was passed` | Wrong token in `.env` | Re-copy token from Developer Portal. No quotes around it in `.env`. |
| `ModuleNotFoundError: No module named 'discord'` | Dependencies not installed or venv not activated | Run `venv\Scripts\activate` then `pip install -r requirements.txt` |
| `ClientException: ffmpeg was not found` | FFmpeg not on PATH | Install FFmpeg (section 3B). Open a NEW terminal after editing PATH. |
| `opus is not loaded` | PyNaCl not installed | Run `pip install PyNaCl` |
| Slash commands don't appear | Commands not synced, or sync is still propagating | Wait up to 1 hour, OR sync to a specific guild for instant results (see below) |
| `InteractionResponded` | Tried to respond to an interaction twice | After `defer()`, use `interaction.followup.send()` not `interaction.response.send_message()` |
| `NotFound: 404 ... Unknown interaction` | Took more than 15 minutes to respond after deferring | yt-dlp is too slow or hung. Check your network. Add a timeout. |
| Audio is silent but bot is "playing" | FFmpeg options wrong, or stream URL is invalid | Verify FFMPEG_OPTIONS has `"-vn"`. Test the URL with yt-dlp independently. |
| `DownloadError` from yt-dlp | Video is unavailable, age-restricted, or live | Try a different video. Age-restricted videos require cookies (advanced). |
| Bot plays one song then stops | `after` callback isn't scheduling `play_next` properly | Must use `asyncio.run_coroutine_threadsafe(play_next(...), bot.loop)` |
| `Already playing audio` | Called `play()` while something is playing | Check `voice_client.is_playing()` before calling `play()` |
| Bot disconnects immediately after joining | Error during playback setup | Check console for tracebacks. Often a missing FFmpeg or bad URL. |

### 7E. Instant Slash Command Sync (Development Only)

Global sync takes up to 1 hour. For development, sync to your specific server for instant updates:

```python
# In bot.py on_ready:
guild = discord.Object(id=YOUR_SERVER_ID)  # Right-click server > Copy Server ID
bot.tree.copy_global_to(guild=guild)
await bot.tree.sync(guild=guild)
```

To find your server ID: Enable Developer Mode in Discord settings (App Settings > Advanced > Developer Mode), then right-click your server name and "Copy Server ID".

### 7F. Step-by-Step Debug Checklist

When something isn't working, go through this in order:

1. **Check the terminal** — Is there a traceback? Read the last line first (the actual error), then trace back up.
2. **Is the bot online?** — Check Discord. If offline, check the terminal for login errors.
3. **Is FFmpeg installed?** — Run `ffmpeg -version` in a NEW terminal.
4. **Is yt-dlp working?** — Test it independently (section 7B).
5. **Is the bot in the voice channel?** — Can you see it in the channel list?
6. **Check permissions** — Does the bot have Connect and Speak permissions in that channel?
7. **Add print statements** — Put `print()` calls before and after suspicious lines to narrow down where it breaks.
8. **Enable debug logging** — Change `logging.INFO` to `logging.DEBUG` for verbose output.

### 7G. Reading Python Tracebacks

A traceback looks like this:

```
Traceback (most recent call last):
  File "bot.py", line 15, in main
    await bot.start(token)
  File "cogs/music.py", line 42, in play
    info = ydl.extract_info(query, download=False)
yt_dlp.utils.DownloadError: Video unavailable
```

Read it **bottom to top**:
- **Last line** = the actual error (`DownloadError: Video unavailable`)
- **Lines above** = the call chain that led to it (started in `bot.py` line 15, went into `music.py` line 42)
- Fix the error described in the last line. The file and line number tell you exactly where.

---

## 8. Testing Checklist

Run through these tests after completing each implementation step.

### Basic Connection
- [ ] `python bot.py` starts without errors
- [ ] Bot appears online in Discord
- [ ] Slash commands appear when typing `/`

### Voice
- [ ] `/play <url>` — Bot joins your voice channel and plays audio
- [ ] `/play <keywords>` — Bot searches YouTube and plays the result
- [ ] `/pause` — Audio pauses
- [ ] `/resume` — Audio resumes
- [ ] `/skip` — Current song skips, next song plays (if queued)
- [ ] `/stop` — Audio stops, bot disconnects, queue clears

### Queue
- [ ] Play 3 songs — first plays, others queue up
- [ ] `/queue` — Shows all queued songs in order
- [ ] `/remove 1` — Removes the first queued song
- [ ] `/shuffle` — Queue order changes
- [ ] `/nowplaying` — Shows current song info

### Edge Cases
- [ ] Use a command without being in a voice channel — get a helpful error
- [ ] Use `/skip` when nothing is playing — get a helpful error
- [ ] Use `/remove 99` when queue has 2 songs — get a helpful error
- [ ] Use `/queue` when queue is empty — get "queue is empty"
- [ ] Queue 2+ songs, let them play through — all play in order, bot goes idle after last
- [ ] `/play` while a song is already playing — adds to queue, doesn't interrupt
- [ ] Use bot in two different servers simultaneously — queues are independent
