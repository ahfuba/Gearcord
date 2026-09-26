import discord
from discord.ext import commands, tasks
from discord import app_commands
import db
import datetime
import image_gen
import sqlite3

class Shame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.monthly_shame_task.start()

    def cog_unload(self):
        self.monthly_shame_task.cancel()

    @app_commands.command(name="setup_shame", description="Configure the Wall of Shame feature.")
    @app_commands.describe(
        channel="The channel to post the Wall of Shame to",
        emoji="The exact emoji (e.g., \U0001f921) to track",
        threshold="Number of reactions needed to reach the Wall of Shame"
    )
    @app_commands.default_permissions(view_audit_log=True, manage_channels=True)
    async def setup_shame(self, interaction: discord.Interaction, channel: discord.TextChannel, emoji: str, threshold: int = 5):
        db.set_config('shame_channel_id', channel.id)
        db.set_config('shame_emoji', emoji)
        db.set_config('shame_threshold', threshold)
        
        # Set the setup date so the 30 day timer can start
        db.set_config('shame_setup_date', datetime.datetime.utcnow().isoformat())
        db.set_config('shame_iteration', 1)
        
        await interaction.response.send_message(f"\u2705 Wall of Shame configured! Messages receiving {threshold} {emoji} reactions will be copied to {channel.mention} via Webhook. The first leaderboard will be posted automatically in 30 days.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return # Ignore the bot's own reactions

        configured_emoji = db.get_config('shame_emoji')
        if not configured_emoji or str(payload.emoji) != configured_emoji:
            return 

        channel = self.bot.get_channel(payload.channel_id)
        if not channel: return
            
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        
        # STEP 1: Check if this message is already on the Wall of Shame (either OG or Webhook copy)
        cursor.execute("SELECT og_message_id FROM shame_messages WHERE og_message_id = ? OR webhook_message_id = ?", (message.id, message.id))
        row = cursor.fetchone()
        
        if row:
            # It IS already on the wall of shame. We just need to log this new vote (Deduplication handles itself)
            og_message_id = row[0]
            try:
                cursor.execute("INSERT INTO shame_votes (og_message_id, voter_id) VALUES (?, ?)", (og_message_id, payload.user_id))
                conn.commit()
            except sqlite3.IntegrityError:
                pass # The user already voted on this message in the other channel, so it's ignored!
            conn.close()
            return
        
        # STEP 2: If it's NOT on the wall of shame, we check if it just hit the threshold
        threshold = int(db.get_config('shame_threshold') or 5)
        reaction_count = next((r.count for r in message.reactions if str(r.emoji) == configured_emoji), 0)
                
        if reaction_count >= threshold:
            shame_channel_id = int(db.get_config('shame_channel_id'))
            shame_channel = self.bot.get_channel(shame_channel_id)
            
            if shame_channel:
                # Setup Webhook for impersonation
                webhooks = await shame_channel.webhooks()
                webhook = discord.utils.get(webhooks, name="ShameWebhook")
                if not webhook:
                    webhook = await shame_channel.create_webhook(name="ShameWebhook")
                
                content = message.content
                files = [await a.to_file() for a in message.attachments]
                content += f"\n\n[Jump to Original]({message.jump_url})"
                
                wh_message = await webhook.send(
                    content=content,
                    username=message.author.display_name,
                    avatar_url=message.author.display_avatar.url,
                    files=files,
                    wait=True 
                )
                
                # Save to database
                cursor.execute(
                    "INSERT INTO shame_messages (og_message_id, og_channel_id, webhook_message_id, shame_user_id) VALUES (?, ?, ?, ?)",
                    (message.id, message.channel.id, wh_message.id, message.author.id)
                )
                
                # Backfill the votes (everyone who reacted on the OG message gets logged)
                try:
                    for r in message.reactions:
                        if str(r.emoji) == configured_emoji:
                            async for user in r.users():
                                try:
                                    cursor.execute("INSERT INTO shame_votes (og_message_id, voter_id) VALUES (?, ?)", (message.id, user.id))
                                except sqlite3.IntegrityError:
                                    pass
                except Exception:
                    pass
                    
                conn.commit()
                
                # Bot slaps a reaction on the webhook message so people can easily click it to vote
                try:
                    await wh_message.add_reaction(configured_emoji)
                except discord.HTTPException:
                    pass
        conn.close()

    # The background task checking for the 30-day mark
    @tasks.loop(hours=12) # Check twice a day
    async def monthly_shame_task(self):
        setup_date_str = db.get_config('shame_setup_date')
        if not setup_date_str:
            return
            
        setup_date = datetime.datetime.fromisoformat(setup_date_str)
        iteration = int(db.get_config('shame_iteration') or 1)
        
        # Calculate when this specific iteration is due
        next_due_date = setup_date + datetime.timedelta(days=30 * iteration)
        
        if datetime.datetime.utcnow() >= next_due_date:
            await self.generate_and_post_leaderboard(iteration)
            db.set_config('shame_iteration', iteration + 1)
            
    @monthly_shame_task.before_loop
    async def before_monthly_task(self):
        await self.bot.wait_until_ready()
        
    @app_commands.command(name="force_leaderboard", description="Manually generate and post the leaderboard right now.")
    @app_commands.default_permissions(view_audit_log=True, manage_channels=True)
    async def force_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        iteration = int(db.get_config('shame_iteration') or 1)
        await self.generate_and_post_leaderboard(iteration, interaction)

    async def generate_and_post_leaderboard(self, iteration, interaction=None):
        shame_channel_id = db.get_config('shame_channel_id')
        if not shame_channel_id:
            if interaction: await interaction.followup.send("Wall of Shame is not configured yet!")
            return
            
        shame_channel = self.bot.get_channel(int(shame_channel_id))
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        
        # Calculate total shame points per user
        cursor.execute('''
            SELECT m.shame_user_id, COUNT(v.voter_id) as total_score
            FROM shame_messages m
            LEFT JOIN shame_votes v ON m.og_message_id = v.og_message_id
            GROUP BY m.shame_user_id
            ORDER BY total_score DESC
            LIMIT 6
        ''')
        top_rows = cursor.fetchall()
        conn.close()
        
        if not top_rows:
            msg = "Not enough shameful messages to generate a leaderboard right now!"
            if interaction:
                await interaction.followup.send(msg)
            return
            
        top_users = []
        for row in top_rows:
            user_id, score = row
            try:
                user = await self.bot.fetch_user(user_id)
                avatar_bytes = await user.display_avatar.read()
                name = user.display_name
            except discord.NotFound:
                name = f"User {user_id}"
                avatar_bytes = None
                
            top_users.append({
                'name': name,
                'score': score,
                'avatar_bytes': avatar_bytes
            })
            
        # Helper to write '1st', '2nd', '3rd', etc.
        def get_ordinal(n):
            if 11 <= (n % 100) <= 13: return str(n) + 'th'
            return str(n) + {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
            
        iteration_str = get_ordinal(iteration)
        guild_name = shame_channel.guild.name if shame_channel.guild else "THE SERVER"
        
        try:
            image_bytes = image_gen.generate_leaderboard(guild_name, f"{iteration_str} ANNUAL LEADERBOARD", top_users)
            file = discord.File(fp=image_bytes, filename="leaderboard.png")
            content = f"\U0001f3c6 **The {iteration_str} Wall of Shame Leaderboard is here!** \U0001f3c6"
            if interaction:
                await interaction.followup.send(content=content, file=file)
            else:
                await shame_channel.send(content=content, file=file)
        except Exception as e:
            if interaction:
                await interaction.followup.send(f"Failed to generate image graphic: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Shame(bot))
