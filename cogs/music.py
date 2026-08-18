import asyncio
import random
import shlex
from dataclasses import dataclass, field

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

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
}

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"


def ffmpeg_options(headers: dict[str, str]) -> dict[str, str]:
    """Build FFmpeg arguments, forwarding the headers yt-dlp extracted with.

    FFmpeg fetches the stream URL itself rather than reusing yt-dlp's session,
    so by default it sends its own Lavf/ User-Agent. Google can refuse a URL
    fetched with headers that don't match the client it was issued to, which
    surfaces as HTTP 403 at playback time.
    """
    before = FFMPEG_BEFORE_OPTIONS
    if headers:
        blob = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        before = f"{before} -headers {shlex.quote(blob)}"
    return {"before_options": before, "options": "-vn"}


@dataclass
class Song:
    title: str
    webpage_url: str
    query: str
    duration: int
    requester: discord.Member
    url: str = ""  # stream URL, resolved at play time
    http_headers: dict[str, str] = field(default_factory=dict)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: dict[int, list[Song]] = {}
        self.now_playing: dict[int, Song | None] = {}

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

    async def resolve_stream_url(self, song: Song) -> tuple[str, dict[str, str]]:
        """Resolve the direct stream URL and its headers just before playback.

        Stream URLs are short-lived, so this runs immediately before handing
        the URL to FFmpeg rather than at queue time.
        """
        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(song.webpage_url, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                return info["url"], info.get("http_headers") or {}

        return await loop.run_in_executor(None, _extract)

    def play_next(self, guild: discord.Guild, channel: discord.abc.Messageable):
        """Callback to play the next song in the queue."""
        queue = self.get_queue(guild.id)
        voice_client = guild.voice_client

        if not queue or not voice_client:
            self.now_playing[guild.id] = None
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
        try:
            song.url, song.http_headers = await self.resolve_stream_url(song)
        except Exception as e:
            await channel.send(f"Could not play **{song.title}**: {e}")
            self.play_next(guild, channel)
            return

        source = discord.FFmpegPCMAudio(song.url, **ffmpeg_options(song.http_headers))
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
            try:
                song.url, song.http_headers = await self.resolve_stream_url(song)
            except Exception as e:
                await interaction.followup.send(f"Could not play **{song.title}**: {e}")
                return

            source = discord.FFmpegPCMAudio(song.url, **ffmpeg_options(song.http_headers))
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
