"""Voice utilities and music playback.

Playback is handled via wavelink 3 + Lavalink v4. Lavalink must be running
before the bot starts — see docker-compose.yml at the repo root.

Spotify URLs are resolved via the LavaSrc Lavalink plugin (metadata only;
audio is streamed from YouTube mirrors). YouTube URLs and search queries
work out of the box via the youtube-plugin for Lavalink.

Bot needs Connect + Speak in the destination channel (invite URL in main.py).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db import Database

logger = logging.getLogger(__name__)


def _fmt_duration(ms: int | None) -> str:
    if ms is None:
        return "?"
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _get_player(interaction: discord.Interaction) -> wavelink.Player | None:
    if not interaction.guild:
        return None
    return cast(wavelink.Player | None, interaction.guild.voice_client)


class VoiceMusicCog(commands.Cog, name="Voice & Music"):
    """Music queue + basic voice-channel moderation (wavelink 3 / Lavalink v4)."""

    def __init__(self, bot: commands.Bot, db: "Database", config: "Config") -> None:
        self.bot = bot
        self.db = db
        self.config = config

    async def cog_load(self) -> None:
        node = wavelink.Node(
            uri=self.config.lavalink_uri,
            password=self.config.lavalink_password,
        )
        await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
        logger.info("wavelink: connecting to Lavalink at %s", self.config.lavalink_uri)

    async def cog_unload(self) -> None:
        for guild in self.bot.guilds:
            player = cast(wavelink.Player | None, guild.voice_client)
            if player:
                await player.disconnect()
        await wavelink.Pool.close()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _read_bounded_int(self, guild_id: int, key: str, default: int, lo: int, hi: int) -> int:
        raw = await self.db.get_guild_config(guild_id, key)
        if raw is None:
            return default
        try:
            return max(lo, min(hi, int(raw)))
        except ValueError:
            return default

    async def _music_module_enabled(self, guild_id: int) -> bool:
        v = await self.db.get_guild_config(guild_id, "music_enabled")
        return v != "0"

    async def _max_queue(self, guild_id: int) -> int:
        return await self._read_bounded_int(guild_id, "music_max_queue", 50, 5, 100)

    async def _inactivity_timeout(self, guild_id: int) -> int:
        return await self._read_bounded_int(guild_id, "music_inactivity_minutes", 3, 1, 60) * 60

    async def _ensure_music_allowed(self, interaction: discord.Interaction) -> bool:
        gid = interaction.guild_id
        if gid is None:
            return True
        if await self._music_module_enabled(gid):
            return True
        msg = "Music is disabled for this server. Ask a server admin to enable it in the dashboard under **Voice & Music**."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return False

    # ------------------------------------------------------------------
    # wavelink events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        logger.info(
            "wavelink: node ready  session=%s  resumed=%s",
            payload.session_id,
            payload.resumed,
        )

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        player = payload.player
        if not player or not hasattr(player, "home"):
            return
        track = payload.track
        dur = _fmt_duration(track.length)
        em = discord.Embed(
            title="Now playing",
            description=f"**[{track.title}]({track.uri})** by {track.author}",
            color=discord.Color.blurple(),
        )
        em.add_field(name="Duration", value=dur)
        if track.artwork:
            em.set_thumbnail(url=track.artwork)
        requester_id = track.extras.requester_id if track.extras else None
        if requester_id:
            em.set_footer(text=f"Requested by <@{requester_id}>")
        await player.home.send(embed=em)  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        player = payload.player
        if not player:
            return
        if player.autoplay == wavelink.AutoPlayMode.disabled and not player.queue:
            timeout = await self._inactivity_timeout(player.guild.id)
            player.inactive_timeout = timeout

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        await player.disconnect()
        if hasattr(player, "home"):
            await player.home.send("Left the voice channel due to inactivity.")  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_or_connect(
        self, interaction: discord.Interaction
    ) -> wavelink.Player | None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return None

        member = interaction.user
        vs = member.voice
        if not vs or not vs.channel or not isinstance(vs.channel, discord.VoiceChannel):
            return None

        ch = vs.channel
        perms = ch.permissions_for(interaction.guild.me)
        if not perms.connect or not perms.speak:
            return None

        player: wavelink.Player | None = cast(wavelink.Player | None, interaction.guild.voice_client)

        if player:
            if player.channel != ch:
                await player.move_to(ch)
        else:
            player = await ch.connect(cls=wavelink.Player, self_deaf=True)

        player.home = interaction.channel  # type: ignore[attr-defined]
        timeout = await self._inactivity_timeout(interaction.guild.id)
        player.inactive_timeout = timeout
        return player

    # ------------------------------------------------------------------
    # /music …
    # ------------------------------------------------------------------

    music = app_commands.Group(
        name="music",
        description="Play music in a voice channel (powered by Lavalink)",
        guild_only=True,
    )

    @music.command(name="join", description="Join your current voice channel")
    async def music_join(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        u = interaction.user
        uv = u.voice if isinstance(u, discord.Member) else None  # type: ignore[union-attr]
        if uv and uv.channel and not isinstance(uv.channel, discord.VoiceChannel):
            await interaction.followup.send(
                "Music playback uses normal **voice channels** only (not stage channels).",
                ephemeral=True,
            )
            return
        player = await self._get_or_connect(interaction)
        if player is None:
            await interaction.followup.send(
                "Join a **voice channel** I can **Connect** and **Speak** in first.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(f"Joined {player.channel.mention}.", ephemeral=True)

    @music.command(name="play", description="Add a track or playlist to the queue (URL or search query)")
    @app_commands.describe(query="YouTube/Spotify URL, or search words")
    async def music_play(self, interaction: discord.Interaction, query: str) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        await interaction.response.defer()

        u = interaction.user
        uv = u.voice if isinstance(u, discord.Member) else None  # type: ignore[union-attr]
        if uv and uv.channel and not isinstance(uv.channel, discord.VoiceChannel):
            await interaction.followup.send(
                "Use a normal **voice channel** for music (stage channels are not supported).",
                ephemeral=True,
            )
            return

        player = await self._get_or_connect(interaction)
        if player is None:
            await interaction.followup.send(
                "Join a voice channel I can **Connect** and **Speak** in, then try again.",
                ephemeral=True,
            )
            return

        try:
            tracks: wavelink.Search = await wavelink.Playable.search(query)
        except wavelink.LavalinkLoadException as exc:
            logger.warning("Lavalink load error: %s", exc)
            await interaction.followup.send(f"Could not load that track: `{exc}`", ephemeral=True)
            return

        if not tracks:
            await interaction.followup.send("No playable audio found for that query.", ephemeral=True)
            return

        max_q = await self._max_queue(interaction.guild.id)  # type: ignore[union-attr]

        if isinstance(tracks, wavelink.Playlist):
            slots = max(0, max_q - len(player.queue))
            to_add = list(tracks)[:slots]
            for t in to_add:
                t.extras = wavelink.ExtrasNamespace({"requester_id": interaction.user.id})
            added = await player.queue.put_wait(to_add)
            await interaction.followup.send(
                f"Added **{added}** track(s) from playlist **{tracks.name}** to the queue."
            )
        else:
            if len(player.queue) >= max_q:
                await interaction.followup.send(f"Queue is full (max {max_q}).", ephemeral=True)
                return
            track: wavelink.Playable = tracks[0]
            track.extras = wavelink.ExtrasNamespace({"requester_id": interaction.user.id})
            await player.queue.put_wait(track)
            dur = _fmt_duration(track.length)
            pos = len(player.queue)
            await interaction.followup.send(
                f"Added **{track.title}** (`{dur}`) — position **{pos}** in queue."
            )

        player.autoplay = wavelink.AutoPlayMode.partial
        if not player.playing:
            await player.play(player.queue.get())

    @music.command(name="pause", description="Pause playback")
    async def music_pause(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        player = _get_player(interaction)
        if not player or not player.playing:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        await player.pause(True)
        await interaction.response.send_message("Paused.", ephemeral=True)

    @music.command(name="resume", description="Resume playback")
    async def music_resume(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        player = _get_player(interaction)
        if not player or not player.paused:
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)
            return
        await player.pause(False)
        await interaction.response.send_message("Resumed.", ephemeral=True)

    @music.command(name="skip", description="Skip the current track")
    async def music_skip(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        player = _get_player(interaction)
        if not player or not player.playing:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        await player.skip(force=True)
        await interaction.response.send_message("Skipped.", ephemeral=True)

    @music.command(name="stop", description="Stop playback and clear the queue")
    async def music_stop(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        player = _get_player(interaction)
        if not player:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            return
        player.queue.clear()
        await player.stop()
        await interaction.response.send_message("Stopped and cleared the queue.", ephemeral=True)

    @music.command(name="leave", description="Disconnect from voice")
    async def music_leave(self, interaction: discord.Interaction) -> None:
        player = _get_player(interaction)
        if player:
            player.queue.clear()
            await player.disconnect()
        await interaction.response.send_message("Disconnected.", ephemeral=True)

    @music.command(name="queue", description="Show the current queue")
    async def music_queue(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        player = _get_player(interaction)
        lines: list[str] = []
        if player and player.current:
            dur = _fmt_duration(player.current.length)
            lines.append(f"**Now:** {player.current.title} (`{dur}`)")
        if player:
            for i, t in enumerate(list(player.queue)[:15], start=1):
                lines.append(f"`{i}.` {t.title}")
            extra = len(player.queue) - 15
            if extra > 0:
                lines.append(f"*…and {extra} more*")
        if not lines:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        em = discord.Embed(title="Music queue", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=em, ephemeral=True)

    @music.command(name="nowplaying", description="Show the track that is currently playing")
    async def music_np(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        player = _get_player(interaction)
        if not player or not player.current:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        t = player.current
        dur = _fmt_duration(t.length)
        requester_id = t.extras.requester_id if t.extras else None
        em = discord.Embed(
            title="Now playing",
            description=f"**[{t.title}]({t.uri})** by {t.author}",
            color=discord.Color.blurple(),
        )
        em.add_field(name="Duration", value=dur)
        if t.artwork:
            em.set_thumbnail(url=t.artwork)
        if requester_id:
            em.set_footer(text=f"Requested by <@{requester_id}>")
        await interaction.response.send_message(embed=em, ephemeral=True)

    @music.command(name="volume", description="Set playback volume (0–100%)")
    @app_commands.describe(percent="Volume percentage (default 100)")
    async def music_volume(self, interaction: discord.Interaction, percent: int = 100) -> None:
        if not await self._ensure_music_allowed(interaction):
            return
        player = _get_player(interaction)
        if not player:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            return
        vol = max(0, min(100, percent))
        await player.set_volume(vol)
        await interaction.response.send_message(f"Volume set to **{vol}%**.", ephemeral=True)

    # ------------------------------------------------------------------
    # /voice …
    # ------------------------------------------------------------------

    voice = app_commands.Group(name="voice", description="Voice channel utilities", guild_only=True)

    @voice.command(name="move", description="Move a member to another voice channel")
    @app_commands.describe(member="Member to move", channel="Destination voice channel")
    @app_commands.default_permissions(move_members=True)
    @app_commands.checks.bot_has_permissions(move_members=True)
    async def voice_move(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        if not interaction.guild:
            return
        if not member.voice or not member.voice.channel:
            await interaction.response.send_message("That member is not in a voice channel.", ephemeral=True)
            return
        await member.move_to(channel, reason=f"Moved by {interaction.user}")
        await interaction.response.send_message(
            f"Moved {member.mention} → {channel.mention}.",
            ephemeral=True,
        )

    @voice.command(name="disconnect", description="Disconnect a member from voice")
    @app_commands.describe(member="Member to disconnect from voice")
    @app_commands.default_permissions(move_members=True)
    @app_commands.checks.bot_has_permissions(move_members=True)
    async def voice_disconnect(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not member.voice or not member.voice.channel:
            await interaction.response.send_message("That member is not in voice channel.", ephemeral=True)
            return
        await member.move_to(None, reason=f"Disconnected by {interaction.user}")
        await interaction.response.send_message(f"Disconnected {member.mention} from voice.", ephemeral=True)

    @voice.command(name="members", description="List members in a voice channel")
    @app_commands.describe(channel="Voice channel to inspect")
    async def voice_members(self, interaction: discord.Interaction, channel: discord.VoiceChannel) -> None:
        names = [m.mention for m in channel.members] if channel.members else ["*(empty)*"]
        em = discord.Embed(
            title=f"Members in #{channel.name}",
            description="\n".join(names[:50]),
            color=discord.Color.green(),
        )
        if len(names) > 50:
            em.set_footer(text=f"Showing 50 of {len(names)}")
        await interaction.response.send_message(embed=em, ephemeral=True)
