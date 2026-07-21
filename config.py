"""
Configuration centralisée du bot.

Tout ce qui était éparpillé sous forme de magic numbers / constantes en tête
de l'ancien fichier monolithique vit maintenant ici. Un seul endroit à modifier
pour reconfigurer le bot sur un autre serveur.
"""
import os

# ── IDs Discord à remplir ────────────────────────────────────────────────────
ROLE_STAFF_ID = 1521181880207147189
ROLE_ADMIN_STAFF_ID = 1521181879141797952

SALON_BIENVENUE_ID = 1521181917095923857
# ⚠️ Même ID que SALON_BIENVENUE_ID dans le fichier d'origine : vérifie si
# c'est voulu ou si tu dois mettre l'ID d'un autre salon pour les départs.
SALON_DEPART_ID = 1521181917095923857
SALON_LOGS_ID = 1521181898725134419
SALON_LOGS_TICKETS_ID = 1525912124923056288
CATEGORY_TICKETS_ID = 1521181911773348010
SALON_DEMANDE_TICKET_ID = 1521181952697172161

# ── Secrets / environnement ──────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN_GESTION")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

# ── Préfixes ──────────────────────────────────────────────────────────────────
COMMAND_PREFIXES = ["!", "+"]

# ── XP / Niveaux ──────────────────────────────────────────────────────────────
XP_PAR_MESSAGE = 15
XP_COOLDOWN_SECONDS = 60

ROLES_NIVEAUX = {
    5: "Niveau 5",
    10: "Niveau 10",
    20: "Niveau 20",
    50: "Niveau 50",
}

# ── Giveaways ─────────────────────────────────────────────────────────────────
GIVEAWAY_EMOJI = "🎉"
GIVEAWAY_CHECK_INTERVAL_SECONDS = 30

# ── Couleurs (thème) ──────────────────────────────────────────────────────────
# Centralisées ici pour éviter les magic numbers répétés dans tout le code.
class Couleurs:
    DEFAUT = 0x7289DA
    SUCCES = 0x2ECC71
    ERREUR = 0xFF0000
    AVERTISSEMENT = 0xFFA500
    DANGER_VIF = 0xE74C3C
    NEUTRE = 0x95A5A6
    INFO_SOMBRE = 0x2B2D31
    OR = 0xFFD700
    JAUNE = 0xF1C40F
    ORANGE_KICK = 0xE67E22
