import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

class ClipBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        # Automatically load all cogs from the 'cogs' folder
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await self.load_extension(f'cogs.{filename[:-3]}')
                print(f"Loaded cog: {filename}")
        
        # Sync the slash commands and context menus globally
        await self.tree.sync()
        print(f"Logged in as {self.user} and synced commands.")

if __name__ == '__main__':
    if not TOKEN:
        print("ERROR: Please set your DISCORD_TOKEN in the .env file.")
    else:
        bot = ClipBot()
        bot.run(TOKEN)
