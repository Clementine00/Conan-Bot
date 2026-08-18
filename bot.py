import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())


@bot.event
async def on_ready():
    guild_id = os.getenv("GUILD_ID")
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Slash commands synced to guild {guild_id} (instant).")
    else:
        await bot.tree.sync()
        print("Slash commands synced globally (may take up to 1 hour).")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s)")


async def main():
    async with bot:
        await bot.load_extension("cogs.music")
        await bot.start(os.getenv("DISCORD_TOKEN"))


asyncio.run(main())
