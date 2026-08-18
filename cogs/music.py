import asyncio
import os
import random
import subprocess
import sys
from dataclasses import dataclass

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

# YouTube requires a GVS proof-of-origin token for playable formats. Without one
# the android_vr client returns URLs that answer 403 and every other client
# returns no formats at all. Tokens come from a bgutil provider; in deployment
# that is a sidecar container, so the URL is overridable per environment.
POT_PROVIDER_URL = os.getenv("POT_PROVIDER_URL", "http://127.0.0.1:4416")

# Which YouTube player client to extract with. The default, android_vr, never
# requests a PO token, so YouTube answers its stream URLs with 403. web_safari
# and tv are SABR-only and yt-dlp has no SABR downloader. mweb requests a GVS
# token from the provider above and still serves plain HTTPS formats.
# Overridable because YouTube changes which clients work fairly often.
YOUTUBE_PLAYER_CLIENT = os.getenv("YOUTUBE_PLAYER_CLIENT", "mweb")
_PLAYER_CLIENTS = [c.strip() for c in YOUTUBE_PLAYER_CLIENT.split(",") if c.strip()]

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "extract_flat": False,
    # YouTube now requires running its JS to solve the signature and n-param
    # (throttling) challenges. yt-dlp only enables Deno by default; enable the
    # already-installed Node runtime instead, plus the EJS challenge-solver
    # script (fetched from GitHub and cached). Without both, some formats are
    # dropped and those tracks fail to play.
    "js_runtimes": {"node": {}},
    "remote_components": ["ejs:github"],
    "extractor_args": {
        "youtube": {"player_client": _PLAYER_CLIENTS},
        "youtubepot-bgutilhttp": {"base_url": [POT_PROVIDER_URL]},
    },
}


# Opus in WebM is streamable from a pipe. A muxed MP4 fallback is not: its moov
# atom sits at the end of the file, so FFmpeg cannot identify the stream until
# the whole download lands and fails with "Invalid data found when processing
# input". Prefer audio-only formats and only fall back to a muxed one last.
STREAM_FORMAT = "bestaudio[acodec=opus]/bestaudio/best"


def ytdlp_stream_argv(webpage_url: str) -> list[str]:
    """Command line that streams the chosen audio track to stdout.

    Playback pipes through yt-dlp rather than handing FFmpeg the stream URL.
    YouTube ties a URL to the session that extracted it, so a second fetch of
    that same URL is answered with 403 no matter which headers accompany it -
    only the extracting process can read it.
    """
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        # --quiet drops the progress meter, which would otherwise flood the
        # container logs, but leaves warnings and errors on stderr.
        "--quiet",
        "--no-playlist",
        "--format",
        STREAM_FORMAT,
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--extractor-args",
        f"youtube:player_client={','.join(_PLAYER_CLIENTS)}",
        "--extractor-args",
        f"youtubepot-bgutilhttp:base_url={POT_PROVIDER_URL}",
        "--output",
        "-",
        webpage_url,
    ]


@dataclass
class Song:
    title: str
    webpage_url: str
    query: str
    duration: int
    requester: discord.Member


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: dict[int, list[Song]] = {}
        self.now_playing: dict[int, Song | None] = {}
        # The yt-dlp process feeding each guild's player, so it can be reaped
        # when playback is skipped, stopped, or replaced.
        self.streams: dict[int, subprocess.Popen] = {}

    def get_queue(self, guild_id: int) -> list[Song]:
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]

    async def search_song(self, query: str, requester: discord.Member) -> Song:
        """Extract song info from a URL or search query using yt-dlp."""
        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(query, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                return info

        info = await loop.run_in_executor(None, _extract)
        return Song(
            title=info.get("title", "Unknown"),
            webpage_url=info.get("webpage_url", query),
            query=query,
            duration=info.get("duration", 0),
            requester=requester,
        )

    def stop_stream(self, guild_id: int) -> None:
        """Reap the yt-dlp process still feeding this guild, if any."""
        proc = self.streams.pop(guild_id, None)
        if proc and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    async def open_stream(self, song: Song) -> subprocess.Popen:
        """Start yt-dlp writing this song's audio to a pipe."""
        loop = asyncio.get_event_loop()

        def _spawn():
            return subprocess.Popen(
                ytdlp_stream_argv(song.webpage_url),
                stdout=subprocess.PIPE,
                # Inherit stderr so extraction failures land in the container
                # logs. Discarding it makes a silent pipe indistinguishable
                # from a download that simply produced nothing.
                stderr=None,
            )

        return await loop.run_in_executor(None, _spawn)

    def play_next(self, guild: discord.Guild, channel: discord.abc.Messageable):
        """Callback to play the next song in the queue."""
        queue = self.get_queue(guild.id)
        voice_client = guild.voice_client

        if not queue or not voice_client:
            self.now_playing[guild.id] = None
            self.stop_stream(guild.id)
            return

        next_song = queue.pop(0)

        # Schedule the async work on the bot's event loop
        future = asyncio.run_coroutine_threadsafe(
            self._play_song(guild, channel, next_song, voice_client), self.bot.loop
        )
        # Catch any exceptions from the coroutine
        future.add_done_callback(
            lambda f: f.result() if not f.cancelled() and f.exception() is None else None
        )

    async def _play_song(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        song: Song,
        voice_client: discord.VoiceClient,
    ):
        """Resolve the stream URL and start playback."""
        self.stop_stream(guild.id)
        try:
            proc = await self.open_stream(song)
        except Exception as e:
            await channel.send(f"Could not play **{song.title}**: {e}")
            self.play_next(guild, channel)
            return

        self.streams[guild.id] = proc
        source = discord.FFmpegPCMAudio(proc.stdout, pipe=True, options="-vn")
        self.now_playing[guild.id] = song

        voice_client.play(
            source,
            after=lambda e: self.play_next(guild, channel),
        )
        await channel.send(f"Now playing: **{song.title}**")

    @app_commands.command(name="play", description="Play a song from YouTube (URL or search)")
    @app_commands.describe(query="YouTube URL or search keywords")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            await interaction.response.send_message(
                "You need to be in a voice channel to use this command."
            )
            return

        # Defer first: connecting + yt-dlp extraction can exceed the 3s window.
        await interaction.response.defer()

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        # Join, move, or repair the connection. A gateway RESUME can leave a
        # stale voice_client that is non-None but no longer actually connected
        # (bot appears in the channel but play() raises "Not connected to voice").
        try:
            if voice_client is None:
                voice_client = await voice_channel.connect()
            elif not voice_client.is_connected():
                await voice_client.disconnect(force=True)
                voice_client = await voice_channel.connect()
            elif voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        except Exception as e:
            await interaction.followup.send(f"Couldn't connect to voice: {e}")
            return

        try:
            song = await self.search_song(query, interaction.user)
        except Exception as e:
            await interaction.followup.send(f"Could not find or play that song: {e}")
            return

        queue = self.get_queue(interaction.guild.id)

        if voice_client.is_playing() or voice_client.is_paused():
            queue.append(song)
            await interaction.followup.send(
                f"Added to queue at position #{len(queue)}: **{song.title}**"
            )
        else:
            # Nothing is playing — start immediately
            self.stop_stream(interaction.guild.id)
            try:
                proc = await self.open_stream(song)
            except Exception as e:
                await interaction.followup.send(f"Could not play **{song.title}**: {e}")
                return

            self.streams[interaction.guild.id] = proc
            source = discord.FFmpegPCMAudio(proc.stdout, pipe=True, options="-vn")
            self.now_playing[interaction.guild.id] = song

            voice_client.play(
                source,
                after=lambda e: self.play_next(interaction.guild, interaction.channel),
            )
            await interaction.followup.send(f"Now playing: **{song.title}**")

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.response.send_message("Paused.")
        else:
            await interaction.response.send_message("Nothing is playing right now.")

    @app_commands.command(name="resume", description="Resume the paused song")
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message("Resumed.")
        else:
            await interaction.response.send_message("Nothing is paused right now.")

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            title = self.now_playing.get(interaction.guild.id)
            voice_client.stop()  # triggers play_next via the after callback
            await interaction.response.send_message(
                f"Skipped **{title.title}**." if title else "Skipped."
            )
        else:
            await interaction.response.send_message("Nothing is playing right now.")

    @app_commands.command(name="stop", description="Stop playback, clear queue, and disconnect")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            await interaction.response.send_message("I'm not in a voice channel.")
            return

        self.queues[interaction.guild.id] = []
        self.now_playing[interaction.guild.id] = None
        voice_client.stop()
        self.stop_stream(interaction.guild.id)
        await voice_client.disconnect()
        await interaction.response.send_message("Stopped and disconnected.")

    @app_commands.command(name="queue", description="Show the current song queue")
    async def queue(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild.id)
        now = self.now_playing.get(interaction.guild.id)

        if not now and not queue:
            await interaction.response.send_message("The queue is empty.")
            return

        embed = discord.Embed(title="Music Queue", color=discord.Color.blurple())

        if now:
            duration = f"{now.duration // 60}:{now.duration % 60:02d}" if now.duration else "??:??"
            embed.add_field(
                name="Now Playing",
                value=f"**{now.title}** [{duration}] — requested by {now.requester.mention}",
                inline=False,
            )

        if queue:
            lines = []
            for i, song in enumerate(queue, start=1):
                duration = (
                    f"{song.duration // 60}:{song.duration % 60:02d}" if song.duration else "??:??"
                )
                lines.append(f"`{i}.` **{song.title}** [{duration}] — {song.requester.mention}")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up Next", value="Nothing queued.", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove", description="Remove a song from the queue by position")
    @app_commands.describe(position="Position in the queue (1, 2, 3...)")
    async def remove(self, interaction: discord.Interaction, position: int):
        queue = self.get_queue(interaction.guild.id)
        if position < 1 or position > len(queue):
            await interaction.response.send_message(
                f"Invalid position. The queue has {len(queue)} song(s)."
            )
            return

        removed = queue.pop(position - 1)
        await interaction.response.send_message(f"Removed **{removed.title}** from the queue.")

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild.id)
        if not queue:
            await interaction.response.send_message("The queue is empty, nothing to shuffle.")
            return

        random.shuffle(queue)
        await interaction.response.send_message(f"Shuffled the queue ({len(queue)} songs).")

    @app_commands.command(name="nowplaying", description="Show the currently playing song")
    async def nowplaying(self, interaction: discord.Interaction):
        now = self.now_playing.get(interaction.guild.id)
        if not now:
            await interaction.response.send_message("Nothing is playing right now.")
            return

        duration = f"{now.duration // 60}:{now.duration % 60:02d}" if now.duration else "??:??"
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{now.title}**",
            url=now.webpage_url,
            color=discord.Color.green(),
        )
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Requested by", value=now.requester.mention, inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
