"""Social Media Alerts cog - monitor RSS feeds for new content.

Features
--------
- RSS feed monitoring for new posts
- Configurable alert channels
- Custom message templates
- Alert history to prevent duplicates
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from bot.db import Database

logger = logging.getLogger(__name__)


class SocialAlertsCog(commands.Cog, name="Social Alerts"):
    """Monitor RSS feeds and send alerts for new content."""

    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self.feed_check_task.start()

    def cog_unload(self) -> None:
        """Clean up tasks when cog is unloaded."""
        self.feed_check_task.cancel()

    # ------------------------------------------------------------------
    # Background task: poll RSS feeds every 15 minutes
    # ------------------------------------------------------------------

    @tasks.loop(minutes=15)
    async def feed_check_task(self) -> None:
        """Poll all enabled RSS feeds and send alerts for new items."""
        alerts = await self.db.get_all_enabled_social_alerts()
        if not alerts:
            return

        async with aiohttp.ClientSession() as session:
            for alert in alerts:
                try:
                    await self._process_alert(session, alert)
                except Exception as e:
                    logger.error("Error processing alert %s: %s", alert["id"], e)

        await self.db.cleanup_alert_history()

    @feed_check_task.before_loop
    async def before_feed_check(self) -> None:
        await self.bot.wait_until_ready()

    async def _process_alert(self, session: aiohttp.ClientSession, alert: dict) -> None:
        """Fetch an RSS feed and post new items to the configured channel."""
        guild = self.bot.get_guild(alert["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(alert["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        async with session.get(alert["account_id"], timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return
            content = await resp.text()

        root = ET.fromstring(content)
        items = root.findall(".//item")

        for item in reversed(items[:10]):
            guid_el = item.find("guid")
            link_el = item.find("link")
            content_id = (guid_el.text if guid_el is not None else None) or (link_el.text if link_el is not None else None)
            if not content_id:
                continue
            if await self.db.check_alert_history(alert["id"], content_id):
                continue

            title_el = item.find("title")
            pub_el = item.find("pubDate")
            title = title_el.text if title_el is not None else "No title"
            link = link_el.text if link_el is not None else ""
            date = pub_el.text if pub_el is not None else ""

            message = alert["message_template"].format(title=title, link=link, date=date)
            try:
                await channel.send(message)
                await self.db.record_alert_history(alert["guild_id"], alert["id"], content_id)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning("Could not send alert to channel %s: %s", alert["channel_id"], e)

    # ------------------------------------------------------------------
    # Social alerts command group
    # ------------------------------------------------------------------

    social_group = app_commands.Group(name="social", description="Social media feed monitoring")

    @social_group.command(name="add", description="Add an RSS feed alert")
    @app_commands.describe(
        channel="Channel to send alerts to",
        rss_url="RSS feed URL",
        message="Custom message template (use {title}, {link}, {date})"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_alert_add(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        rss_url: str,
        message: str = "📰 **{title}**\n{link}",
    ) -> None:
        """Add an RSS feed alert."""
        if not rss_url.startswith("http"):
            await interaction.response.send_message(
                "❌ Invalid RSS URL. Must start with http:// or https://",
                ephemeral=True,
            )
            return

        if await self.db.add_social_alert(
            interaction.guild_id,  # type: ignore[arg-type]
            channel.id,
            "rss",
            rss_url,
            "new",
            message,
        ):
            await interaction.response.send_message(
                f"✅ RSS alert added for {rss_url}\nAlerts will be sent to {channel.mention}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ An alert for this RSS URL already exists.",
                ephemeral=True,
            )

    @social_group.command(name="list", description="List all social media alerts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_alert_list(self, interaction: discord.Interaction) -> None:
        """List all social media alerts."""
        guild = interaction.guild
        assert guild is not None

        alerts = await self.db.get_social_alerts(guild.id)
        
        if not alerts:
            await interaction.response.send_message(
                "❌ No social media alerts configured.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="📢 Social Media Alerts",
            description=f"Found {len(alerts)} alert(s)",
            color=discord.Color.blue(),
        )

        for alert in alerts[:10]:
            channel = guild.get_channel(alert["channel_id"])
            channel_name = channel.name if channel else "unknown"
            
            status = "✅ Enabled" if alert["enabled"] else "❌ Disabled"
            
            # Truncate account_id for display
            account_display = alert["account_id"][:50] + "..." if len(alert["account_id"]) > 50 else alert["account_id"]
            
            embed.add_field(
                name=f"#{alert['id']} {alert['platform'].title()} Alert",
                value=f"**Status:** {status}\n**Channel:** #{channel_name}\n**Account:** `{account_display}`\n**Type:** {alert['alert_type']}",
                inline=False,
            )

        if len(alerts) > 10:
            embed.set_footer(text=f"Showing 10 of {len(alerts)} alerts")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @social_group.command(name="remove", description="Remove a social media alert")
    @app_commands.describe(alert_id="Alert ID to remove (use /social list to find IDs)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_alert_remove(
        self,
        interaction: discord.Interaction,
        alert_id: int,
    ) -> None:
        """Remove a social media alert."""
        if await self.db.remove_social_alert(interaction.guild_id, alert_id):  # type: ignore[arg-type]
            await interaction.response.send_message(
                f"✅ Alert #{alert_id} has been removed.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ Alert #{alert_id} not found.",
                ephemeral=True,
            )

    @social_group.command(name="toggle", description="Toggle a social media alert on/off")
    @app_commands.describe(alert_id="Alert ID to toggle")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_alert_toggle(
        self,
        interaction: discord.Interaction,
        alert_id: int,
    ) -> None:
        """Toggle a social media alert."""
        result = await self.db.toggle_social_alert(interaction.guild_id, alert_id)  # type: ignore[arg-type]
        
        if result is None:
            await interaction.response.send_message(
                f"❌ Alert #{alert_id} not found.",
                ephemeral=True,
            )
        elif result:
            await interaction.response.send_message(
                f"✅ Alert #{alert_id} has been enabled.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"✅ Alert #{alert_id} has been disabled.",
                ephemeral=True,
            )

    @social_group.command(name="test", description="Test an RSS feed alert")
    @app_commands.describe(rss_url="RSS feed URL to test")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def social_alert_test(
        self,
        interaction: discord.Interaction,
        rss_url: str,
    ) -> None:
        """Test an RSS feed by fetching recent items."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url, timeout=10) as response:
                    if response.status != 200:
                        await interaction.followup.send(
                            f"❌ Failed to fetch RSS feed. Status: {response.status}",
                            ephemeral=True,
                        )
                        return
                    
                    content = await response.text()
                    root = ET.fromstring(content)
                    
                    items = root.findall(".//item")
                    
                    if not items:
                        await interaction.followup.send(
                            "❌ No items found in RSS feed.",
                            ephemeral=True,
                        )
                        return
                    
                    embed = discord.Embed(
                        title="📰 RSS Feed Test Results",
                        description=f"Found {len(items)} items in feed",
                        color=discord.Color.green(),
                    )
                    
                    for item in items[:3]:
                        title = item.find("title")
                        link = item.find("link")
                        
                        if title is not None and link is not None:
                            title_text = title.text or "No title"
                            link_text = link.text or ""
                            embed.add_field(
                                name=title_text,
                                value=link_text[:100],
                                inline=False,
                            )
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
        except Exception as e:
            logger.error(f"Error testing RSS feed: {e}")
            await interaction.followup.send(
                f"❌ Error testing RSS feed: {str(e)}",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Load the SocialAlerts cog."""
    await bot.add_cog(SocialAlertsCog(bot, bot.db))
