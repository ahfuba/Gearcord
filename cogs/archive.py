import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import db

class Archive(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register the context menu command dynamically for the cog
        self.ctx_menu = app_commands.ContextMenu(
            name="Archive to Forum",
            callback=self.archive_menu_callback,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        # Clean up the command when the cog unloads
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @app_commands.command(name="setup_archive", description="Set the default forum channel for the Right-Click Archive menu.")
    @app_commands.describe(forum="The forum channel to send right-click archives to")
    async def setup_archive(self, interaction: discord.Interaction, forum: discord.ForumChannel):
        db.set_config('archive_forum_id', forum.id)
        await interaction.response.send_message(f"✅ The right-click 'Archive to Forum' menu will now send messages to {forum.mention}.", ephemeral=True)

    async def archive_menu_callback(self, interaction: discord.Interaction, message: discord.Message):
        forum_id = db.get_config('archive_forum_id')
        
        if not forum_id:
            await interaction.response.send_message("The archive forum isn't configured yet! Use `/setup_archive` first.", ephemeral=True)
            return

        forum_channel = self.bot.get_channel(int(forum_id))
        if not isinstance(forum_channel, discord.ForumChannel):
            await interaction.response.send_message("The configured channel is no longer a valid Forum Channel.", ephemeral=True)
            return

        embed = discord.Embed(description=message.content, color=discord.Color.dark_theme())
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"Archived from #{message.channel.name}")
        
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        title = f"Archive: {message.author.display_name}"
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            thread, _ = await forum_channel.create_thread(
                name=title[:100],
                embed=embed
            )
            await interaction.followup.send(f"Successfully archived to {thread.mention}!")
        except Exception as e:
            await interaction.followup.send(f"Failed to create forum post: {e}")

    @app_commands.command(name="archive_channel", description="Bulk archive messages from a channel into a single forum thread.")
    @app_commands.describe(
        source_channel="The channel to read messages from",
        target_forum="The forum channel to dump these into",
        thread_title="Title of the new forum thread",
        filter_type="What type of messages to archive",
        limit="Max number of messages to scan (default 100)"
    )
    @app_commands.choices(filter_type=[
        app_commands.Choice(name="All Messages", value="ALL"),
        app_commands.Choice(name="Videos Only", value="VIDEOS"),
        app_commands.Choice(name="Images Only", value="IMAGES"),
        app_commands.Choice(name="Voice Messages Only", value="VOICE")
    ])
    async def archive_channel(
        self, 
        interaction: discord.Interaction, 
        source_channel: discord.TextChannel,
        target_forum: discord.ForumChannel,
        thread_title: str,
        filter_type: app_commands.Choice[str],
        limit: int = 100
    ):
        # Tell Discord we are thinking, since this might take a while
        await interaction.response.defer(ephemeral=True)

        messages_to_archive = []
        try:
            # oldest_first=True so they are posted in chronological order
            async for msg in source_channel.history(limit=limit, oldest_first=True):
                if filter_type.value == "ALL":
                    messages_to_archive.append(msg)
                elif filter_type.value == "VIDEOS":
                    if msg.attachments and any(a.content_type and a.content_type.startswith('video/') for a in msg.attachments):
                        messages_to_archive.append(msg)
                elif filter_type.value == "IMAGES":
                    if msg.attachments and any(a.content_type and a.content_type.startswith('image/') for a in msg.attachments):
                        messages_to_archive.append(msg)
                elif filter_type.value == "VOICE":
                    if msg.flags.voice or (msg.attachments and any(a.content_type and a.content_type.startswith('audio/') for a in msg.attachments)):
                        messages_to_archive.append(msg)
        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to read message history in that channel.")
            return

        if not messages_to_archive:
            await interaction.followup.send("No messages found matching that filter.")
            return

        # We need a generic starter message to create the forum thread
        starter_embed = discord.Embed(
            title=f"Bulk Archive: {source_channel.name}",
            description=f"Archiving {len(messages_to_archive)} messages.\nFilter: {filter_type.name}",
            color=discord.Color.brand_green()
        )
        
        try:
            thread, _ = await target_forum.create_thread(
                name=thread_title[:100],
                embed=starter_embed
            )
        except Exception as e:
            await interaction.followup.send(f"Failed to create forum thread: {e}")
            return

        await interaction.followup.send(f"Found {len(messages_to_archive)} messages. Archiving them to {thread.mention}. This might take a moment...")

        for msg in messages_to_archive:
            embed = discord.Embed(description=msg.content, color=discord.Color.dark_theme())
            embed.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)
            embed.timestamp = msg.created_at
            
            if msg.attachments:
                # Add attachment URLs to description so Discord can preview videos/audio
                content_urls = "\n".join([a.url for a in msg.attachments])
                embed.description = (embed.description or "") + f"\n\n**Attachments:**\n{content_urls}"
                    
                # If there's an image, set it as the embed image
                for a in msg.attachments:
                    if a.content_type and a.content_type.startswith('image/'):
                        embed.set_image(url=a.url)
                        break

            try:
                await thread.send(embed=embed)
                await asyncio.sleep(1) 
            except discord.HTTPException:
                pass 

        await thread.send("✅ Archive complete.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Archive(bot))
