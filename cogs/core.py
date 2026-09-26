import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import db

class Core(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available bot commands and features.")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Bot Help & Features", 
            description="Here is a list of everything I can do to help manage clips, contests, and archives!",
            color=discord.Color.blurple()
        )
        
        embed.add_field(name="\U0001f4f8 Archiving (Walkthrough)", value="""
**1. Setup Right-Click Archiving:**
Run `/setup_archive` to pick a default forum channel. Once set, you can Right-Click any message -> Apps -> `Archive to Forum` to instantly save it as its own thread.

**2. Bulk Sweep a Channel:**
Run `/archive_channel` to move large amounts of messages into a single thread.
\u2022 Select the source channel, target forum, and a filter (like `Videos Only`).
\u2022 Choose the style (`Embed` or `Webhook Impersonation`).
\u2022 The bot will **Scan** the channel and show you how many messages it found.
\u2022 Once you click **Proceed**, it will queue your task, show a live progress bar with an ETA, and safely copy the messages.
*(Note: Archiving commands require View Audit Log & Manage Channels permissions)*
        """, inline=False)

        embed.add_field(name="\U0001f921 Wall of Shame", value="""
**`/setup_shame`**: Configure the emoji, channel, and reaction threshold.
**`/force_leaderboard`**: Generate and post the graphical leaderboard right now.
        """, inline=False)

        embed.add_field(name="\U0001f3c6 Voting & Contests", value="""
**`/tally_votes`**: Scan any forum channel, count up the default reactions on starter messages, and print a Top 10 Leaderboard.
        """, inline=False)
        
        embed.add_field(name="\u2699\ufe0f Core", value="""
**`/stats`**: View statistics about how many shameful messages and votes have been logged.
        """, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="View bot statistics and Wall of Shame totals.")
    async def stats_command(self, interaction: discord.Interaction):
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        
        # Get total shame messages
        cursor.execute("SELECT COUNT(*) FROM shame_messages")
        total_shamed = cursor.fetchone()[0]
        
        # Get total votes cast
        cursor.execute("SELECT COUNT(*) FROM shame_votes")
        total_votes = cursor.fetchone()[0]
        
        conn.close()
        
        embed = discord.Embed(title="\U0001f4ca Bot Statistics", color=discord.Color.green())
        embed.add_field(name="Total Shamed Messages", value=f"{total_shamed:,}", inline=True)
        embed.add_field(name="Total Unique Votes", value=f"{total_votes:,}", inline=True)
        
        iteration = db.get_config('shame_iteration')
        if iteration:
            embed.set_footer(text=f"Currently on Wall of Shame Iteration #{iteration}")
            
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
