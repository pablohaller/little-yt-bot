import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque
import os
from dotenv import load_dotenv
import static_ffmpeg

static_ffmpeg.add_paths()
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

SPOTDL_AVAILABLE = False
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        from spotdl import Spotdl as SpotdlClient
        SPOTDL_AVAILABLE = True
    except ImportError:
        pass

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": False,
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Per-guild state
guild_queues: dict[int, deque] = {}
guild_np_messages: dict[int, discord.Message] = {}
guild_np_views: dict[int, "PlayerView"] = {}
guild_channels: dict[int, discord.abc.Messageable] = {}


def get_queue(guild_id: int) -> deque:
    if guild_id not in guild_queues:
        guild_queues[guild_id] = deque()
    return guild_queues[guild_id]


def is_spotify_url(url: str) -> bool:
    return "open.spotify.com" in url


async def resolve_spotify(url: str) -> list[tuple[str, str]]:
    if not SPOTDL_AVAILABLE:
        raise RuntimeError(
            "Spotify support requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env "
            "and spotdl installed."
        )
    loop = asyncio.get_event_loop()
    client = SpotdlClient(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
    songs = await loop.run_in_executor(None, lambda: client.search([url]))
    return [
        (f"ytsearch1:{song.name} {song.artist}", f"{song.name} — {song.artist}")
        for song in songs
    ]


async def fetch_stream_info(query: str) -> tuple[str, str | None, str | None]:
    """Fetch a fresh stream URL, thumbnail, and webpage URL for a webpage URL or ytsearch query."""
    loop = asyncio.get_event_loop()
    opts = {**YDL_OPTIONS, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
    if "entries" in info:
        info = info["entries"][0]
    return info["url"], info.get("thumbnail"), info.get("webpage_url")


async def ensure_voice(interaction: discord.Interaction) -> discord.VoiceClient | None:
    """Connect/move to the user's voice channel. Returns None if user is not in one."""
    if not interaction.user.voice:
        await interaction.followup.send("❌ Join a voice channel first!")
        return None
    vc = interaction.guild.voice_client
    if not vc:
        vc = await interaction.user.voice.channel.connect()
    elif vc.channel != interaction.user.voice.channel:
        await vc.move_to(interaction.user.voice.channel)
    guild_channels[interaction.guild.id] = interaction.channel
    return vc


# ── UI Views ──────────────────────────────────────────────────────────────────

class PlayerView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        self.guild = guild

    @discord.ui.button(emoji="⏸", label="Pause", style=discord.ButtonStyle.secondary)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.guild.voice_client
        if not vc:
            return await interaction.response.defer()
        if vc.is_playing():
            vc.pause()
            button.emoji = "▶"
            button.label = "Resume"
            button.style = discord.ButtonStyle.success
        elif vc.is_paused():
            vc.resume()
            button.emoji = "⏸"
            button.label = "Pause"
            button.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏭", label="Skip", style=discord.ButtonStyle.primary)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹", label="Stop", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.guild.voice_client
        if vc:
            get_queue(self.guild.id).clear()
            vc.stop()
            await vc.disconnect()
        self._disable_all()
        await interaction.response.edit_message(content="⏹ Stopped.", view=None)

    def _disable_all(self):
        for child in self.children:
            child.disabled = True


class SearchView(discord.ui.View):
    def __init__(self, guild: discord.Guild, entries: list):
        super().__init__(timeout=30)
        self.guild = guild
        self.entries = entries

        for i in range(len(entries)):
            btn = discord.ui.Button(label=str(i + 1), style=discord.ButtonStyle.secondary)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            entry = self.entries[idx]
            webpage_url = entry.get("webpage_url") or entry.get("url")
            title = entry.get("title", "Unknown")

            get_queue(self.guild.id).append((webpage_url, title))
            self.stop()
            await interaction.response.edit_message(
                content=f"✅ Added to queue: **{title}**", embeds=[], view=None
            )

            vc = self.guild.voice_client
            if vc and not vc.is_playing() and not vc.is_paused():
                await play_next(self.guild)

        return callback

    async def _cancel(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(content="Search cancelled.", embeds=[], view=None)


# ── Playback ──────────────────────────────────────────────────────────────────

async def _expire_now_playing(guild_id: int):
    view = guild_np_views.pop(guild_id, None)
    msg = guild_np_messages.pop(guild_id, None)
    if view and msg:
        view._disable_all()
        try:
            await msg.edit(view=view)
        except Exception:
            pass


async def play_next(guild: discord.Guild) -> None:
    await _expire_now_playing(guild.id)

    queue = get_queue(guild.id)
    if not queue:
        return

    query, title = queue.popleft()
    channel = guild_channels.get(guild.id)

    try:
        stream_url, thumbnail, webpage_url = await fetch_stream_info(query)
    except Exception as e:
        if channel:
            await channel.send(f"❌ Could not fetch **{title}**: {e}")
        await play_next(guild)
        return

    vc = guild.voice_client
    if not vc:
        return

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS), volume=0.5
    )

    def after_play(error: Exception | None) -> None:
        if error:
            print(f"Playback error: {error}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

    vc.play(source, after=after_play)

    if channel:
        view = PlayerView(guild)
        content = f"▶ Now playing: {webpage_url}" if webpage_url else f"▶ Now playing: **{title}**"
        msg = await channel.send(content=content, view=view)
        guild_np_views[guild.id] = view
        guild_np_messages[guild.id] = msg


# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Slash commands synced to guild {GUILD_ID}.")
    else:
        await bot.tree.sync()
        print("Slash commands synced globally (may take up to 1 hour).")
    print(f"Logged in as {bot.user} (id: {bot.user.id})")


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member.bot:
        return
    vc = member.guild.voice_client
    if not vc:
        return
    if not any(not m.bot for m in vc.channel.members):
        await asyncio.sleep(30)
        vc = member.guild.voice_client
        if vc and not any(not m.bot for m in vc.channel.members):
            get_queue(member.guild.id).clear()
            await _expire_now_playing(member.guild.id)
            await vc.disconnect()


# ── Slash Commands ────────────────────────────────────────────────────────────

@bot.tree.command(name="play", description="Play a YouTube or Spotify URL")
@app_commands.describe(url="YouTube or Spotify URL (video, playlist, or track)")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    vc = await ensure_voice(interaction)
    if not vc:
        return

    queue = get_queue(interaction.guild.id)

    try:
        if is_spotify_url(url):
            tracks = await resolve_spotify(url)
            for item in tracks:
                queue.append(item)
            await interaction.followup.send(f"📋 Added **{len(tracks)}** Spotify track(s) to the queue.")
        else:
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                info = await loop.run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                for entry in entries:
                    webpage_url = entry.get("webpage_url") or entry.get("url")
                    title = entry.get("title", "Unknown")
                    queue.append((webpage_url, title))
                await interaction.followup.send(f"📋 Added **{len(entries)}** tracks to the queue.")
            else:
                webpage_url = info.get("webpage_url") or url
                title = info.get("title", "Unknown")
                queue.append((webpage_url, title))
                await interaction.followup.send(f"✅ Added to queue: **{title}**")
    except Exception as e:
        return await interaction.followup.send(f"❌ Error: {e}")

    if not vc.is_playing() and not vc.is_paused():
        await play_next(interaction.guild)


@bot.tree.command(name="search", description="Search YouTube and pick a track to play")
@app_commands.describe(query="Song name or search terms")
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    vc = await ensure_voice(interaction)
    if not vc:
        return

    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL({**YDL_OPTIONS, "noplaylist": True}) as ydl:
        results = await loop.run_in_executor(
            None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False)
        )

    entries = [e for e in results.get("entries", []) if e][:5]
    if not entries:
        return await interaction.followup.send("❌ No results found.")

    embeds = []
    for i, entry in enumerate(entries, 1):
        duration = int(entry.get("duration") or 0)
        mins, secs = divmod(duration, 60)
        embed = discord.Embed(
            title=f"{i}. {entry.get('title', 'Unknown')}",
            description=f"**{entry.get('uploader', 'Unknown')}** • {mins}:{secs:02d}",
            color=discord.Color.red(),
        )
        if thumbnail := entry.get("thumbnail"):
            embed.set_thumbnail(url=thumbnail)
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds, view=SearchView(interaction.guild, entries))


@bot.tree.command(name="pause", description="Pause playback")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸ Paused.")
    else:
        await interaction.response.send_message("Nothing is playing.")


@bot.tree.command(name="resume", description="Resume paused playback")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶ Resumed.")
    else:
        await interaction.response.send_message("Nothing is paused.")


@bot.tree.command(name="skip", description="Skip the current track")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message("⏭ Skipped.")
    else:
        await interaction.response.send_message("Nothing is playing.")


@bot.tree.command(name="stop", description="Stop playback, clear the queue, and disconnect")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        get_queue(interaction.guild.id).clear()
        vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("⏹ Stopped and disconnected.")
    else:
        await interaction.response.send_message("Not connected to a voice channel.")


@bot.tree.command(name="queue", description="Show the current queue")
async def queue_cmd(interaction: discord.Interaction):
    q = get_queue(interaction.guild.id)
    if not q:
        return await interaction.response.send_message("Queue is empty.")
    lines = [f"`{i + 1}.` {title}" for i, (_, title) in enumerate(q)]
    if len(lines) > 20:
        lines = lines[:20] + [f"…and {len(q) - 20} more"]
    await interaction.response.send_message("**Queue:**\n" + "\n".join(lines))


@bot.tree.command(name="volume", description="Set the playback volume (0–100)")
@app_commands.describe(level="Volume level from 0 to 100")
async def volume(interaction: discord.Interaction, level: int):
    if not 0 <= level <= 100:
        return await interaction.response.send_message("Volume must be between 0 and 100.")
    vc = interaction.guild.voice_client
    if vc and vc.source:
        vc.source.volume = level / 100
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**.")
    else:
        await interaction.response.send_message("Nothing is playing.")


@bot.tree.command(name="join", description="Join your voice channel")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ You are not in a voice channel.")
    vc = interaction.guild.voice_client
    if vc:
        await vc.move_to(interaction.user.voice.channel)
    else:
        await interaction.user.voice.channel.connect()
    guild_channels[interaction.guild.id] = interaction.channel
    await interaction.response.send_message(f"Joined **{interaction.user.voice.channel.name}**.")


@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        get_queue(interaction.guild.id).clear()
        await vc.disconnect()
        await interaction.response.send_message("👋 Disconnected.")
    else:
        await interaction.response.send_message("Not connected to a voice channel.")


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN is not set in .env")
    bot.run(TOKEN)
