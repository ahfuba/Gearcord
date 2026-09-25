import discord
from discord import app_commands
from discord.ext import commands

class Voting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="tally_votes", description="Tally the votes for clips in a specific forum channel")
    @app_commands.describe(channel="The forum channel to tally votes from")
    async def tally_votes(self, interaction: discord.Interaction, channel: discord.ForumChannel):
        await interaction.response.defer()
        
        leaderboard = []
        
        for thread in channel.threads:
            try:
                starter_message = await thread.fetch_message(thread.id)
                upvotes = 0
                for reaction in starter_message.reactions:
                    # Taking the count of the first reaction found (typically the default forum emoji)
                    upvotes = reaction.count
                    break
                    
                leaderboard.append({
                    'thread': thread,
                    'votes': upvotes
                })
            except discord.NotFound:
                continue 
                
        leaderboard.sort(key=lambda x: x['votes'], reverse=True)
        
        if not leaderboard:
            await interaction.followup.send("No active threads found or no votes cast yet.")
            return
            
        response = "**🏆 Current Clip Leaderboard 🏆**\n\n"
        for i, entry in enumerate(leaderboard[:10]):
            response += f"**{i+1}.** {entry['thread'].mention} - {entry['votes']} votes\n"
            
        await interaction.followup.send(response)

async def setup(bot: commands.Bot):
    await bot.add_cog(Voting(bot))
