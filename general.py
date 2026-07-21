"""Cog: commandes générales accessibles à tous (aide, stats, avis)."""
import discord
from discord import app_commands
from discord.ext import commands

import config


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = bot.store

    @commands.command()
    async def help(self, ctx):
        embed = discord.Embed(
            title="📚 Menu d'Aide du Bot",
            description="Voici la liste des commandes disponibles, classées par permissions.",
            color=config.Couleurs.INFO_SOMBRE,
        )
        embed.add_field(name="👥 Membres", value=(
            "`+i` / `/invitations` : Voir tes invitations.\n"
            "`/niveau` : Consulter ton niveau d'XP.\n"
            "`/classement` : Voir le classement XP du serveur.\n"
            "`/avis` : Laisser un avis sur le serveur.\n"
            "`/avis_stats` : Voir les stats des avis.\n"
            "`/stats` : Voir les statistiques du serveur."
        ), inline=False)
        embed.add_field(name="🛡️ Staff", value=(
            "`+warn <@membre> <raison>` : Avertir un membre.\n"
            "`+unwarn <@membre>` : Retirer les avertissements.\n"
            "`+mute <@membre> <durée> <raison>` : Mute un membre avec l'exclusion native Discord (ex: `+mute @membre 3m raison`).\n"
            "`+unmute <@membre>` : Retirer le mute.\n"
            "`+lock` / `+unlock` : Verrouiller ou déverrouiller le salon actuel.\n"
            "`+rename <nom>` : Renommer le ticket en cours.\n"
            "`+staff <id/@membre>` : Ajouter quelqu'un au ticket en cours.\n"
            "`+unstaff <id/@membre>` : Retirer quelqu'un du ticket en cours.\n"
            "`/clear` : Supprimer des messages (avec filtre par membre en option)."
        ), inline=False)
        embed.add_field(name="🔨 Admin Staff", value=(
            "`+kick <@membre> <raison>` : Expulser du serveur.\n"
            "`+ban <@membre> <raison>` : Bannir du serveur.\n"
            "`/unban <id>` : Débannir un membre.\n"
            "`/slowmode` : Régler le mode lent d'un salon.\n"
            "`/pause` : Mettre un salon en cooldown global.\n"
            "`/gw` / `/gw_reroll` / `/gw_end` : Gérer les giveaways."
        ), inline=False)
        embed.add_field(name="👑 Propriétaire", value=(
            "`/setup_ticket` / `/setup_reglement` / `/setup_roles` : Configurer le serveur."
        ), inline=False)
        embed.set_footer(text=f"Demandé par {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @app_commands.command(name="log", description="Redirige vers le salon des logs")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def log_cmd(self, interaction: discord.Interaction):
        salon_logs = interaction.guild.get_channel(config.SALON_LOGS_ID)
        embed = discord.Embed(
            title="📋 Suivi des Logs",
            description=f"Toutes les actions sont enregistrées dans {salon_logs.mention if salon_logs else 'le salon introuvable'}.",
            color=config.Couleurs.DEFAUT,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="Statistiques du serveur")
    async def stats_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=f"📊 Stats de {guild.name}", color=config.Couleurs.DEFAUT)
        embed.add_field(name="👥 Membres", value=str(guild.member_count))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avis", description="Laisser un avis")
    @app_commands.choices(note=[app_commands.Choice(name=f"{i} étoiles", value=i) for i in range(1, 6)])
    async def avis_cmd(self, interaction: discord.Interaction, theme: str,
                        note: app_commands.Choice[int], texte: str, image: discord.Attachment = None):
        etoiles = "⭐" * note.value + "☆" * (5 - note.value)
        embed = discord.Embed(title="📝 Nouvel avis", color=config.Couleurs.JAUNE)
        embed.add_field(name="Thème", value=theme, inline=True)
        embed.add_field(name="Note", value=f"{etoiles} ({note.value}/5)", inline=True)
        embed.add_field(name="Avis", value=texte, inline=False)
        if image:
            embed.set_image(url=image.url)
        await interaction.response.send_message(embed=embed)

        gid = str(interaction.guild.id)
        self.store.avis.setdefault(gid, []).append({
            "theme": theme, "note": note.value, "texte": texte,
            "image_url": image.url if image else None, "auteur_id": interaction.user.id,
        })
        await self.store.save("avis")

    @app_commands.command(name="avis_stats", description="Voir la moyenne des avis")
    async def avis_stats_cmd(self, interaction: discord.Interaction, theme: str = None):
        gid = str(interaction.guild.id)
        tous_avis = self.store.avis.get(gid, [])
        avis_liste = [a for a in tous_avis if a["theme"].lower() == theme.lower()] if theme else tous_avis
        if not avis_liste:
            await interaction.response.send_message("❌ Aucun avis trouvé.", ephemeral=True)
            return

        moyenne = sum(a["note"] for a in avis_liste) / len(avis_liste)
        arrondi = round(moyenne)
        embed = discord.Embed(title="📊 Avis", color=config.Couleurs.JAUNE)
        embed.add_field(name="Moyenne", value=f"{'⭐' * arrondi}{'☆' * (5 - arrondi)} ({moyenne:.1f}/5)")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
