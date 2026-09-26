import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import db

class ArchiveConfirmView(discord.ui.View):
    def __init__(self, cog, output_channel, user_id, source_channel, target_forum, thread_title, filter_type_name, style_val, messages_to_archive):
        super().__init__(timeout=300) # 5 minute timeout
        self.cog = cog
        self.output_channel = output_channel
        self.user_id = user_id
        self.source_channel = source_channel
        self.target_forum = target_forum
        self.thread_title = thread_title
        self.filter_type_name = filter_type_name
        self.style_val = style_val
        self.messages_to_archive = messages_to_archive
        self.message = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(content="\u274c Archiving timed out (no response). Moving to next in queue if any.", view=self, embed=None)
        except:
            pass
        self.cog.process_next_in_queue(self.source_channel.guild.id)

    @discord.ui.button(label="Proceed & Archive", style=discord.ButtonStyle.green, custom_id="proceed")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the person who initiated this scan can confirm it.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        
        await self.cog.execute_archive(
            message=interaction.message,
            source_channel=self.source_channel,
            target_forum=self.target_forum,
            thread_title=self.thread_title,
            filter_type_name=self.filter_type_name,
            style_val=self.style_val,
            messages_to_archive=self.messages_to_archive
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the person who initiated this scan can cancel it.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="\u274c Archiving operation cancelled.", embed=None, view=self)
        self.cog.process_next_in_queue(self.source_channel.guild.id)


class Archive(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name="Archive to Forum",
            callback=self.archive_menu_callback,
        )
        self.bot.tree.add_command(self.ctx_menu)
        
        # State tracking to limit 1 archive process per server
        self.is_archiving = {} # guild_id -> bool
        self.archive_queue = {} # guild_id -> list of job dicts

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    def process_next_in_queue(self, guild_id):
        if guild_id in self.archive_queue and len(self.archive_queue[guild_id]) > 0:
            next_job = self.archive_queue[guild_id].pop(0)
            asyncio.create_task(self.start_scan(**next_job))
        else:
            self.is_archiving[guild_id] = False

    @app_commands.command(name="setup_archive", description="Set the default forum channel for the Right-Click Archive menu.")
    @app_commands.describe(forum="The forum channel to send right-click archives to")
    @app_commands.default_permissions(view_audit_log=True, manage_channels=True)
    async def setup_archive(self, interaction: discord.Interaction, forum: discord.ForumChannel):
        db.set_config('archive_forum_id', forum.id)
        await interaction.response.send_message(f"\u2705 The right-click 'Archive to Forum' menu will now send messages to {forum.mention}.", ephemeral=True)

    async def archive_menu_callback(self, interaction: discord.Interaction, message: discord.Message):
        # Check permissions manually for Context Menu
        if not interaction.user.guild_permissions.view_audit_log or not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("\u274c You need 'View Audit Log' and 'Manage Channels' permissions to archive messages.", ephemeral=True)
            return

        # Context menu is quick, so it bypasses the bulk queue
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
    @app_commands.default_permissions(view_audit_log=True, manage_channels=True)
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
        guild_id = interaction.guild_id
        
        job = {
            'output_channel': interaction.channel,
            'user_id': interaction.user.id,
            'source_channel': source_channel,
            'target_forum': target_forum,
            'thread_title': thread_title,
            'filter_type': filter_type,
            'style': style,
            'limit': limit
        }

        if self.is_archiving.get(guild_id, False):
            if guild_id not in self.archive_queue:
                self.archive_queue[guild_id] = []
            self.archive_queue[guild_id].append(job)
            await interaction.response.send_message(f"\u23f3 An archive process is already running in this server. You have been added to the queue (Position {len(self.archive_queue[guild_id])}). I will ping you when it's your turn.")
            return

        self.is_archiving[guild_id] = True
        await interaction.response.defer(ephemeral=False)
        job['interaction'] = interaction
        await self.start_scan(**job)

    async def start_scan(self, output_channel, user_id, source_channel, target_forum, thread_title, filter_type, style, limit, interaction=None):
        limit_text = "Unlimited" if limit is None else str(limit)
        msg_text = f"\U0001f50d <@{user_id}>, **Scanning {source_channel.mention}** (Limit: {limit_text})... This may take a minute."
        
        if interaction:
            status_msg = await interaction.followup.send(msg_text, wait=True)
        else:
            status_msg = await output_channel.send(msg_text)

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
            await status_msg.edit(content=f"\u274c <@{user_id}> I do not have permission to read message history in {source_channel.mention}.")
            self.process_next_in_queue(source_channel.guild.id)
            return
        except Exception as e:
            await status_msg.edit(content=f"\u274c <@{user_id}> Scan failed: {e}")
            self.process_next_in_queue(source_channel.guild.id)
            return

        if not messages_to_archive:
            await status_msg.edit(content=f"\u26a0\ufe0f <@{user_id}> No messages found matching `{filter_type.name}`.")
            self.process_next_in_queue(source_channel.guild.id)
            return

        embed = discord.Embed(
            title="Scan Complete",
            description=f"Found **{len(messages_to_archive)}** messages matching `{filter_type.name}` in {source_channel.mention}.\n\nAre you sure you want to proceed and archive these to {target_forum.mention}?",
            color=discord.Color.yellow()
        )
        
        view = ArchiveConfirmView(
            self, 
            output_channel,
            user_id,
            source_channel, 
            target_forum, 
            thread_title, 
            filter_type.name, 
            style.value, 
            messages_to_archive
        )
        view.message = status_msg
        
        await status_msg.edit(content=f"<@{user_id}>", embed=embed, view=view)

    def generate_progress_bar(self, current, success, errors, total, start_time, length=20):
        percent = current / total if total > 0 else 1
        filled = int(length * percent)
        bar = '\u2588' * filled + '\u2591' * (length - filled)
        
        if current > 0:
            elapsed = asyncio.get_event_loop().time() - start_time
            rate = current / elapsed
            remaining_seconds = (total - current) / rate
            m, s = divmod(int(remaining_seconds), 60)
            h, m = divmod(m, 60)
            eta_str = f"~{h}h {m}m {s}s left" if h > 0 else f"~{m}m {s}s left" if m > 0 else f"~{s}s left"
        else:
            eta_str = "Calculating ETA..."
            
        return f"`[{bar}]` **{current}/{total}** ({int(percent * 100)}%)\n\u2705 Success: {success} | \u274c Errors: {errors}\n*ETA: {eta_str}*"

    async def execute_archive(self, message, source_channel, target_forum, thread_title, filter_type_name, style_val, messages_to_archive):
        total = len(messages_to_archive)
        start_time = asyncio.get_event_loop().time()
        loading_emoji = os.getenv('LOADING_EMOJI', '\U0001f504')
        
        embed = discord.Embed(
            title=f"{loading_emoji} Archiving in Progress...",
            description=f"Target: {target_forum.mention}\n{self.generate_progress_bar(0, 0, 0, total, start_time)}",
            color=discord.Color.blue()
        )
        
        await message.edit(embed=embed)
        
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
            embed.title = "\u274c Archive Failed"
            embed.description = f"Failed to create the forum thread: {e}"
            embed.color = discord.Color.red()
            await message.edit(embed=embed)
            self.process_next_in_queue(source_channel.guild.id)
            return

        webhook = None
        if style_val == "WEBHOOK":
            webhooks = await target_forum.webhooks()
            webhook = discord.utils.get(webhooks, name="ArchiveWebhook")
            if not webhook:
                webhook = await target_forum.create_webhook(name="ArchiveWebhook")

        processed = 0
        success = 0
        errors = 0
        last_update_time = asyncio.get_event_loop().time()
        
        for msg in messages_to_archive:
            current_success = False
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
                    current_success = True
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
                    current_success = True
                except discord.HTTPException:
                    pass

            if current_success:
                success += 1
            else:
                errors += 1
                
            processed += 1
            
            # Avoid sending messages too fast
            await asyncio.sleep(1)
            
            current_time = asyncio.get_event_loop().time()
            if current_time - last_update_time > 3.0 or processed == total:
                embed.description = f"Target: {thread.mention}\n{self.generate_progress_bar(processed, success, errors, total, start_time)}"
                try:
                    await message.edit(embed=embed)
                except discord.HTTPException:
                    pass
                last_update_time = current_time

        embed.title = "\u2705 Archive Complete"
        embed.color = discord.Color.green() if errors == 0 else discord.Color.orange()
        await message.edit(embed=embed)
        await thread.send(f"\u2705 Bulk archive has finished processing. (Success: {success}, Errors: {errors})")
        
        # Trigger next in queue
        self.process_next_in_queue(source_channel.guild.id)

async def setup(bot: commands.Bot):
    await bot.add_cog(Archive(bot))
