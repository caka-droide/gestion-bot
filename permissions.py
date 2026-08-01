"""
Vérifications de permissions.

Avant : la logique "est-ce que cette personne est staff/admin staff" était
réécrite 3 fois (une version pour les commandes préfixe avec `ctx`, une
pour les commandes slash avec `interaction`, et une brute pour les boutons)
avec un commentaire dans le code qui admettait la duplication.

Ici, une seule fonction `_est_staff` / `_est_admin_staff` fait le calcul,
et les 4 décorateurs (2 styles de commandes x 2 niveaux) ne font que
l'adapter à `ctx` ou `interaction`. Comportement inchangé.
"""
import discord
from discord.ext import commands
from discord import app_commands

import config


def _est_staff(membre: discord.Member) -> bool:
    if membre.id == membre.guild.owner_id:
        return True
    roles_ids = {r.id for r in membre.roles}
    return config.ROLE_STAFF_ID in roles_ids or config.ROLE_ADMIN_STAFF_ID in roles_ids


def _est_admin_staff(membre: discord.Member) -> bool:
    if membre.id == membre.guild.owner_id:
        return True
    roles_ids = {r.id for r in membre.roles}
    return config.ROLE_ADMIN_STAFF_ID in roles_ids


def est_staff(membre: discord.Member) -> bool:
    """Utilisable hors commandes (ex: dans les callbacks de boutons)."""
    return _est_staff(membre)


def est_salon_ticket(channel) -> bool:
    """Vérifie qu'un salon fait partie de la catégorie tickets."""
    return getattr(channel, "category_id", None) == config.CATEGORY_TICKETS_ID


# ── Décorateurs pour commandes préfixe (`ctx`) ───────────────────────────────
def is_staff_or_higher():
    async def predicate(ctx):
        return _est_staff(ctx.author)
    return commands.check(predicate)


def is_admin_staff_or_higher():
    async def predicate(ctx):
        return _est_admin_staff(ctx.author)
    return commands.check(predicate)


# ── Décorateurs pour commandes slash (`interaction`) ─────────────────────────
def is_staff_or_higher_app():
    def predicate(interaction: discord.Interaction):
        return _est_staff(interaction.user)
    return app_commands.check(predicate)


def is_admin_staff_or_higher_app():
    def predicate(interaction: discord.Interaction):
        return _est_admin_staff(interaction.user)
    return app_commands.check(predicate)


def is_server_owner():
    def predicate(interaction: discord.Interaction):
        return interaction.user.id == interaction.guild.owner_id
    return app_commands.check(predicate)
