import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import db

class ArchiveConfirmView(discord.ui.View):
    def __init__(self, cog, source_channel, target_forum, thread_title, filter_type_name, style_val, messages_to_archive):
        super().__init__(timeout=300) # 5 minute timeout to confirm
        self.cog = cog
        self.source_channel = source_channel
        self.target_forum = target_forum
        self.thread_title = thread_title
        self.filter_type_name = filter_type_name
        self.style_val = style_val
        self.messages_to_archive = messages_to_archive

    @discord.ui.button(label="Proceed & Archive", style=discord.ButtonStyle.green, custom_id="proceed")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable buttons so they can't be clicked twice
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        
        # Hand off to the cog to actually do the archiving
        await self.cog.execute_archive(
            interaction=interaction,
            source_channel=self.source_channel,
            target_forum=self.target_forum,
            thread_title=self.thread_title,
            filter_type_name=self.filter_type_name,
            style_val=self.style_val,
            messages_to_archive=self.messages_to_archive
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ Archiving operation cancelled.", embed=None, view=self)


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
            thread, _ = await forum_channel.create_thread(name=title[:100], embed=embed)
            await interaction.followup.send(f"Successfully archived to {thread.mention}!")
        except Exception as e:
            await interaction.followup.send(f"Failed to create forum post: {e}")

    @app_commands.command(name="archive_channel", description="Bulk archive messages from a channel into a single forum thread.")
    @app_commands.describe(
        source_channel="The channel to read messages from",
        target_forum="The forum channel to dump these into",
        thread_title="Title of the new forum thread",
        filter_type="What type of messages to archive",
        style="How to format the archived messages",
        limit="Max number of messages to scan (leave empty for unlimited)"
    )
    @app_commands.choices(filter_type=[
        app_commands.Choice(name="All Messages", value="ALL"),
        app_commands.Choice(name="Videos Only", value="VIDEOS"),
        app_commands.Choice(name="Images Only", value="IMAGES"),
        app_commands.Choice(name="Voice Messages Only", value="VOICE")
    ])
    @app_commands.choices(style=[
        app_commands.Choice(name="Rich Embed", value="EMBED"),
        app_commands.Choice(name="Webhook (Impersonation)", value="WEBHOOK")
    ])
    async def archive_channel(
        self, 
        interaction: discord.Interaction, 
        source_channel: discord.TextChannel,
        target_forum: discord.ForumChannel,
        thread_title: str,
        filter_type: app_commands.Choice[str],
        style: app_commands.Choice[str],
        limit: int = None
    ):
        # We need this to not be ephemeral so the progress bar can be seen in the execution channel
        await interaction.response.defer(ephemeral=False)

        limit_text = "Unlimited" if limit is None else str(limit)
        status_msg = await interaction.followup.send(f"🔍 **Scanning {source_channel.mention}** (Limit: {limit_text})... This may take a minute.", wait=True)

        messages_to_archive = []
        try:
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
            await status_msg.edit(content="❌ I do not have permission to read message history in that channel.")
            return

        if not messages_to_archive:
            await status_msg.edit(content="⚠️ No messages found matching that filter.")
            return

        # Phase 2: Confirmation
        embed = discord.Embed(
            title="Scan Complete",
            description=f"Found **{len(messages_to_archive)}** messages matching `{filter_type.name}` in {source_channel.mention}.\n\nAre you sure you want to proceed and archive these to {target_forum.mention}?\n*(Depending on the amount, this could take several minutes. Do not restart the bot.)*",
            color=discord.Color.yellow()
        )
        
        view = ArchiveConfirmView(
            self, 
            source_channel, 
            target_forum, 
            thread_title, 
            filter_type.name, 
            style.value, 
            messages_to_archive
        )
        
        await status_msg.edit(content=None, embed=embed, view=view)

    def generate_progress_bar(self, current, total, start_time, length=20):
        percent = current / total if total > 0 else 1
        filled = int(length * percent)
        bar = '█' * filled + '░' * (length - filled)
        
        if current > 0:
            elapsed = asyncio.get_event_loop().time() - start_time
            rate = current / elapsed
            remaining_seconds = (total - current) / rate
            
            m, s = divmod(int(remaining_seconds), 60)
            h, m = divmod(m, 60)
            if h > 0:
                eta_str = f"~{h}h {m}m {s}s left"
            elif m > 0:
                eta_str = f"~{m}m {s}s left"
            else:
                eta_str = f"~{s}s left"
        else:
            eta_str = "Calculating ETA..."
            
        return f"`[{bar}]` **{current}/{total}** ({int(percent * 100)}%)\n*ETA: {eta_str}*"

    async def execute_archive(self, interaction, source_channel, target_forum, thread_title, filter_type_name, style_val, messages_to_archive):
        total = len(messages_to_archive)
        start_time = asyncio.get_event_loop().time()
        
        # You can set a custom animated emoji in your .env file like: LOADING_EMOJI=<a:spinner:123456789>
        loading_emoji = os.getenv('LOADING_EMOJI', '🔄')
        
        embed = discord.Embed(
            title=f"{loading_emoji} Archiving in Progress...",
            description=f"Target: {target_forum.mention}\n{self.generate_progress_bar(0, total, start_time)}",
            color=discord.Color.blue()
        )
        
        # Update the original confirmation message with the progress bar
        await interaction.message.edit(embed=embed)
        
        starter_embed = discord.Embed(
            title=f"Bulk Archive: {source_channel.name}",
            description=f"Archiving {total} messages.\nFilter: {filter_type_name}\nStyle: {style_val}",
            color=discord.Color.brand_green()
        )
        
        try:
            thread, _ = await target_forum.create_thread(
                name=thread_title[:100],
                embed=starter_embed
            )
        except Exception as e:
            embed.title = "❌ Archive Failed"
            embed.description = f"Failed to create the forum thread: {e}"
            embed.color = discord.Color.red()
            await interaction.message.edit(embed=embed)
            return

        webhook = None
        if style_val == "WEBHOOK":
            webhooks = await target_forum.webhooks()
            webhook = discord.utils.get(webhooks, name="ArchiveWebhook")
            if not webhook:
                webhook = await target_forum.create_webhook(name="ArchiveWebhook")

        archived_count = 0
        last_update_time = asyncio.get_event_loop().time()
        
        for msg in messages_to_archive:
            if style_val == "EMBED":
                emb = discord.Embed(description=msg.content, color=discord.Color.dark_theme())
                emb.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)
                emb.timestamp = msg.created_at
                
                if msg.attachments:
                    content_urls = "\n".join([a.url for a in msg.attachments])
                    emb.description = (emb.description or "") + f"\n\n**Attachments:**\n{content_urls}"
                    for a in msg.attachments:
                        if a.content_type and a.content_type.startswith('image/'):
                            emb.set_image(url=a.url)
                            break
                try:
                    await thread.send(embed=emb)
                    await asyncio.sleep(1) 
                except discord.HTTPException:
                    pass 
            else:
                files = []
                try:
                    for a in msg.attachments:
                        files.append(await a.to_file())
                except:
                    pass
                    
                try:
                    await webhook.send(
                        content=msg.content or "*(No text content)*",
                        username=msg.author.display_name,
                        avatar_url=msg.author.display_avatar.url,
                        files=files,
                        thread=thread
                    )
                    await asyncio.sleep(1)
                except discord.HTTPException:
                    pass

            archived_count += 1
            
            # Update the progress bar embed every 3 seconds to avoid Discord API rate limits on message editing
            current_time = asyncio.get_event_loop().time()
            if current_time - last_update_time > 3.0 or archived_count == total:
                embed.description = f"Target: {thread.mention}\n{self.generate_progress_bar(archived_count, total, start_time)}"
                try:
                    await interaction.message.edit(embed=embed)
                except discord.HTTPException:
                    pass
                last_update_time = current_time

        # Final Success State
        embed.title = "✅ Archive Complete"
        embed.color = discord.Color.green()
        await interaction.message.edit(embed=embed)
        await thread.send("✅ Bulk archive has finished processing.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Archive(bot))
