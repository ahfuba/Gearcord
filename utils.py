import discord
from discord import app_commands

DEV_ID = 482438633173811201

def has_perms_or_dev():
    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id == DEV_ID:
            return True
        if interaction.user.guild_permissions.view_audit_log and interaction.user.guild_permissions.manage_channels:
            return True
        return False
    return app_commands.check(predicate)
