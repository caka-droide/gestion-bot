"""
Vérifications de permissions.

Une seule fonction _est_staff / _est_admin_staff fait le calcul, et les
4 décorateurs (2 styles de commandes x 2 niveaux) ne font que l'adapter à
ctx ou interaction.

Support par-guild : guild_settings.py fournit, pour chaque guild, un
override optionnel de ROLE_STAFF_ID / ROLE_ADMIN_STAFF_ID / CATEGORY_TICKETS_ID
ainsi qu'une liste ALLOWED_ADMINS / ALLOWED_STAFF (IDs de membres traités
comme staff/admin sans avoir le rôle Discord correspondant). Une guild non
listée dans guild_settings.json retombe strictement sur config.py, donc le
comportement du serveur principal est inchangé.
"""
import discord
from discord.ext import commands
from discord import app_commands

import guild_settings


def _est_staff(membre: discord.Member) -> bool:
    if membre.id == membre.guild.owner_id:
        return True
    guild_id = membre.guild.id
    if membre.id in guild_settings.get_allowed_admins(guild_id) or membre.id in guild_settings.get_allowed_staff(guild_id):
        return True
    roles_ids = {r.id for r in membre.roles}
    role_staff = guild_settings.get_id(guild_id, "ROLE_STAFF_ID")
    role_admin_staff = guild_settings.get_id(guild_id, "ROLE_ADMIN_STAFF_ID")
    return role_staff in roles_ids or role_admin_staff in roles_ids


def _est_admin_staff(membre: discord.Member) -> bool:
    if membre.id == membre.guild.owner_id:
        return True
    guild_id = membre.guild.id
    if membre.id in guild_settings.get_allowed_admins(guild_id):
        return True
    roles_ids = {r.id for r in membre.roles}
    role_admin_staff = guild_settings.get_id(guild_id, "ROLE_ADMIN_STAFF_ID")
    return role_admin_staff in roles_ids


def est_staff(membre: discord.Member) -> bool:
    """Utilisable hors commandes (ex: dans les callbacks de boutons)."""
    return _est_staff(membre)


def est_salon_ticket(channel) -> bool:
    """Vérifie qu'un salon fait partie de la catégorie tickets (de sa guild)."""
    category_id = guild_settings.get_id(channel.guild.id, "CATEGORY_TICKETS_ID")
    return getattr(channel, "category_id", None) == category_id


def is_staff_or_higher():
    async def predicate(ctx):
        return _est_staff(ctx.author)
    return commands.check(predicate)


def is_admin_staff_or_higher():
    async def predicate(ctx):
        return _est_admin_staff(ctx.author)
    return commands.check(predicate)


def is_staff_or_higher_app():
    def predicate(interaction: discord.Interaction):
        return _est_staff(interaction.user)
    return app_commands.check(predicate)


def is_admin_staff_or_higher_app():
    def predicate(interaction: discord.Interaction):
        return _est_admin_staff(interaction.user)
    return app_commands.check(predicate)


def is_server_owner():
    """Réservé au propriétaire du serveur, + aux ALLOWED_ADMINS déclarés pour
    cette guild dans guild_settings.json."""
    def predicate(interaction: discord.Interaction):
        if interaction.user.id == interaction.guild.owner_id:
            return True
        return interaction.user.id in guild_settings.get_allowed_admins(interaction.guild.id)
    return app_commands.check(predicate)
