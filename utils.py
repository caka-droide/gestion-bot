"""Fonctions utilitaires partagées par plusieurs cogs."""
import os
from datetime import datetime

import discord

import config


async def envoyer_log(guild, titre, description, couleur=config.Couleurs.DEFAUT, auteur=None):
    salon_logs = guild.get_channel(config.SALON_LOGS_ID)
    if not salon_logs:
        return
    embed = discord.Embed(title=titre, description=description, color=couleur, timestamp=datetime.now())
    if auteur:
        embed.set_footer(text=f"Action par : {auteur.name}", icon_url=auteur.display_avatar.url)
    await salon_logs.send(embed=embed)


async def envoyer_transcript(guild, salon_ticket, ferme_par):
    salon_logs_tickets = guild.get_channel(config.SALON_LOGS_TICKETS_ID)
    if not salon_logs_tickets:
        return

    messages = [msg async for msg in salon_ticket.history(limit=None, oldest_first=True)]

    lignes = [
        f"=== Transcript du ticket {salon_ticket.name} ===",
        f"Fermé par : {ferme_par} le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
        "",
    ]
    for msg in messages:
        horodatage = msg.created_at.strftime("%d/%m/%Y %H:%M")
        contenu = msg.content if msg.content else "[Embed / Pièce jointe]"
        lignes.append(f"[{horodatage}] {msg.author} : {contenu}")

    texte_transcript = "\n".join(lignes)
    nom_fichier = f"transcript-{salon_ticket.name}.txt"
    with open(nom_fichier, "w", encoding="utf-8") as f:
        f.write(texte_transcript)

    embed = discord.Embed(
        title="📄 Transcript du Ticket",
        description=f"Ticket : `{salon_ticket.name}`\nFermé par : {ferme_par}\nNombre de messages : {len(messages)}",
        color=config.Couleurs.INFO_SOMBRE,
        timestamp=datetime.now(),
    )
    try:
        await salon_logs_tickets.send(embed=embed, file=discord.File(nom_fichier))
    finally:
        if os.path.exists(nom_fichier):
            os.remove(nom_fichier)


def parse_duree(duree_str: str):
    """Parse '3m', '1h', '1d', '30s' -> nombre de secondes, ou None si invalide."""
    duree_str = duree_str.strip().lower()
    if len(duree_str) < 2:
        return None
    unite = duree_str[-1]
    nombre = duree_str[:-1]
    unites = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if unite not in unites or not nombre.isdigit():
        return None
    return int(nombre) * unites[unite]
