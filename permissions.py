"""
Vérifications de permissions.

Version améliorée : support des paramètres par-guild (par serveur) via
un fichier JSON local `guild_settings.json`. Si une valeur n'existe pas pour
la guild, on retombe sur les constantes définies dans `config.py` — ce qui
assure que ton serveur principal reste inchangé tant que tu ne changes pas
les constantes ou n'ajoutes pas d'entrée pour ce serveur dans le JSON.

Ajout d'options par-guild : ALLOWED_ADMINS et ALLOWED_STAFF permettent de
donner des droits à des utilisateurs spécifiques (IDs) pour une guild sans
leur attribuer un rôle. Utile pour ton cas où tu veux que ton compte soit
administrateur sur le serveur secondaire sans modifier ton serveur
principal.

Le reste du comportement (décorateurs pour ctx / interactions...) est
préservé.
"""
import json
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands

import config

# Chemin du fichier de settings par-guild (au même niveau que ce module).
_GUILD_SETTINGS_PATH = Path(__file__).parent / "guild_settings.json"

# Chargement en mémoire (fallback sur un dict vide si absent / invalide)
try:
    if _GUILD_SETTINGS_PATH.exists():
        with _GUILD_SETTINGS_PATH.open("r", encoding="utf-8") as f:
            _GUILD_SETTINGS = json.load(f)
    else:
        _GUILD_SETTINGS = {}
except Exception:
    # En cas d'erreur de parsing, on logera éventuellement plus tard;
    # pour l'instant on se rabat sur les valeurs par défaut.
    _GUILD_SETTINGS = {}


def _get_guild_setting(guild_id: int, key: str, default):
    """Renvoie la valeur configurée pour la guild (si présente), sinon default.

    Les clés attendues sont : ROLE_STAFF_ID, ROLE_ADMIN_STAFF_ID,
    CATEGORY_TICKETS_ID, ALLOWED_ADMINS, ALLOWED_STAFF.
    """
    return _GUILD_SETTINGS.get(str(guild_id), {}).get(key, default)


def _ids_from_setting(guild_id: int, key: str):
    """Retourne un set d'entiers pour une clé de liste d'IDs dans le JSON.

    Si la valeur n'est pas présente, renvoie un set vide. Tente de caster en
    int pour tolérer des nombres encodés comme chaînes.
    """
    raw = _get_guild_setting(guild_id, key, [])
    if not isinstance(raw, (list, tuple, set)):
        return set()
    ids = set()
    for v in raw:
        try:
            ids.add(int(v))
        except Exception:
            continue
    return ids


def _est_staff(membre: discord.Member) -> bool:
    if membre.id == membre.guild.owner_id:
        return True
    # Rôles configurés (fallback sur config.py)
    staff_id = _get_guild_setting(membre.guild.id, "ROLE_STAFF_ID", config.ROLE_STAFF_ID)
    admin_id = _get_guild_setting(membre.guild.id, "ROLE_ADMIN_STAFF_ID", config.ROLE_ADMIN_STAFF_ID)
    roles_ids = {r.id for r in membre.roles}
    if staff_id in roles_ids or admin_id in roles_ids:
        return True
    # Overrides par utilisateur
    allowed_staff = _ids_from_setting(membre.guild.id, "ALLOWED_STAFF")
    allowed_admins = _ids_from_setting(membre.guild.id, "ALLOWED_ADMINS")
    if membre.id in allowed_staff or membre.id in allowed_admins:
        return True
    return False


def _est_admin_staff(membre: discord.Member) -> bool:
    if membre.id == membre.guild.owner_id:
        return True
    admin_id = _get_guild_setting(membre.guild.id, "ROLE_ADMIN_STAFF_ID", config.ROLE_ADMIN_STAFF_ID)
    roles_ids = {r.id for r in membre.roles}
    if admin_id in roles_ids:
        return True
    # Overrides par utilisateur
    allowed_admins = _ids_from_setting(membre.guild.id, "ALLOWED_ADMINS")
    if membre.id in allowed_admins:
        return True
    return False


def est_staff(membre: discord.Member) -> bool:
    """Utilisable hors commandes (ex: dans les callbacks de boutons)."""
    return _est_staff(membre)


def est_salon_ticket(channel) -> bool:
    """Vérifie qu'un salon fait partie de la catégorie tickets.

    Si le channel n'est pas rattaché à une guild (ex: DM), retourne False.
    """
    guild = getattr(channel, "guild", None)
    if guild is None:
        return False
    cat_id = _get_guild_setting(guild.id, "CATEGORY_TICKETS_ID", config.CATEGORY_TICKETS_ID)
    return getattr(channel, "category_id", None) == cat_id


# ── Décorateurs pour commandes préfixe (`ctx`) ───────────────────────────────
def is_staff_or_higher():
    async def predicate(ctx):
        return _est_staff(ctx.author)
    return commands.check(predicate)


def is_admin_staff_or_higher():
    async def predicate(ctx):
        return _est_admin_staff(ctx.author)
    return commands.check(predicate)


# ── Décorateurs pour commandes slash (`interaction`) ────��────────────────────
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
