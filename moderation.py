"""Cog de modération : warns, mutes (timeout natif), kick/ban, lock, clear."""
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
import utils
from permissions import is_staff_or_higher, is_admin_staff_or_higher, is_admin_staff_or_higher_app


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = bot.store

    # ── Warns ─────────────────────────────────────────────────────────────
    @commands.command()
    @is_staff_or_higher()
    async def warn(self, ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
        gid, uid = str(ctx.guild.id), str(membre.id)
        self.store.warns.setdefault(gid, {}).setdefault(uid, [])
        self.store.warns[gid][uid].append({"raison": raison, "date": str(datetime.now()), "by": str(ctx.author.id)})
        await self.store.save("warns")
        nb = len(self.store.warns[gid][uid])

        embed = discord.Embed(title="⚠️ Avertissement", color=config.Couleurs.AVERTISSEMENT)
        embed.add_field(name="Membre", value=membre.mention, inline=True)
        embed.add_field(name="Raison", value=raison, inline=True)
        embed.add_field(name="Total warns", value=str(nb), inline=True)
        await ctx.send(embed=embed)

        await utils.envoyer_log(
            ctx.guild, "⚠️ Membre Warn", f"Membre : {membre.mention}\nRaison : {raison}\nTotal : {nb} warn(s)",
            config.Couleurs.AVERTISSEMENT, ctx.author,
        )
        try:
            await membre.send(f"⚠️ Tu as reçu un avertissement sur **{ctx.guild.name}**\nRaison : {raison}\nTotal : {nb} warn(s)")
        except discord.HTTPException:
            pass

    @commands.command()
    @is_staff_or_higher()
    async def unwarn(self, ctx, membre: discord.Member):
        gid, uid = str(ctx.guild.id), str(membre.id)
        if gid in self.store.warns and uid in self.store.warns[gid]:
            self.store.warns[gid][uid] = []
            await self.store.save("warns")
        await ctx.send(f"✅ Warns de {membre.mention} supprimés.")
        await utils.envoyer_log(
            ctx.guild, "✨ Warns Effacés", f"Les avertissements de {membre.mention} ont été remis à zéro.",
            config.Couleurs.SUCCES, ctx.author,
        )

    # ── Mute (timeout natif) ────────────────────────────────────────────
    @commands.command()
    @is_staff_or_higher()
    async def mute(self, ctx, membre: discord.Member, duree_str: str, *, raison: str = "Aucune raison"):
        secondes = utils.parse_duree(duree_str)
        if not secondes:
            await ctx.send("❌ **Format de durée invalide.** Exemple : `3m` (3 minutes), `1h` (1 heure), `1d` (1 jour).")
            return
        if secondes > 2419200:  # Discord limite le timeout natif à 28 jours max
            await ctx.send("❌ La durée maximale de mute (exclusion native) est de 28 jours (`28d`).")
            return

        try:
            await membre.timeout(timedelta(seconds=secondes), reason=raison)
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission d'exclure temporairement ce membre (vérifie mes rôles et la hiérarchie).")
            return
        except discord.HTTPException as e:
            await ctx.send(f"❌ Une erreur est survenue lors du timeout : {e}")
            return

        embed = discord.Embed(title="🔇 Membre rendu muet (Timeout)", color=config.Couleurs.ERREUR)
        embed.add_field(name="Membre", value=membre.mention, inline=True)
        embed.add_field(name="Durée", value=duree_str, inline=True)
        embed.add_field(name="Raison", value=raison, inline=True)
        await ctx.send(embed=embed)
        await utils.envoyer_log(
            ctx.guild, "🔇 Membre Mute", f"Membre : {membre.mention}\nDurée : {duree_str}\nRaison : {raison}",
            config.Couleurs.DANGER_VIF, ctx.author,
        )

    @commands.command()
    @is_staff_or_higher()
    async def unmute(self, ctx, membre: discord.Member):
        try:
            await membre.timeout(None, reason=f"Unmute par {ctx.author.name}")
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission de retirer l'exclusion de ce membre.")
            return
        except discord.HTTPException as e:
            await ctx.send(f"❌ Une erreur est survenue : {e}")
            return

        await ctx.send(f"✅ {membre.mention} n'est plus muet.")
        await utils.envoyer_log(
            ctx.guild, "🔊 Membre Unmute", f"L'exclusion de {membre.mention} a été retirée.",
            config.Couleurs.SUCCES, ctx.author,
        )

    # ── Lock / Unlock ────────────────────────────────────────────────────
    @commands.command()
    @is_staff_or_higher()
    async def lock(self, ctx, *, raison: str = "Aucune raison"):
        cible = ctx.channel
        overwrite = cible.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is False:
            await ctx.send(f"❌ {cible.mention} est déjà verrouillé.")
            return

        overwrite.send_messages = False
        await cible.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=raison)

        embed = discord.Embed(title="🔒 Salon Verrouillé", color=config.Couleurs.ERREUR)
        embed.add_field(name="Salon", value=cible.mention, inline=True)
        embed.add_field(name="Raison", value=raison, inline=True)
        await ctx.send(embed=embed)
        await utils.envoyer_log(
            ctx.guild, "🔒 Salon Verrouillé", f"Salon : {cible.mention}\nRaison : {raison}",
            config.Couleurs.ERREUR, ctx.author,
        )

    @commands.command()
    @is_staff_or_higher()
    async def unlock(self, ctx):
        cible = ctx.channel
        overwrite = cible.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is not False:
            await ctx.send(f"❌ {cible.mention} n'est pas verrouillé.")
            return

        overwrite.send_messages = None
        if overwrite.is_empty():
            await cible.set_permissions(ctx.guild.default_role, overwrite=None)
        else:
            await cible.set_permissions(ctx.guild.default_role, overwrite=overwrite)

        embed = discord.Embed(title="🔓 Salon Déverrouillé", color=config.Couleurs.SUCCES)
        embed.add_field(name="Salon", value=cible.mention, inline=True)
        await ctx.send(embed=embed)
        await utils.envoyer_log(ctx.guild, "🔓 Salon Déverrouillé", f"Salon : {cible.mention}", config.Couleurs.SUCCES, ctx.author)

    # ── Kick / Ban / Unban ───────────────────────────────────────────────
    @commands.command()
    @is_admin_staff_or_higher()
    async def kick(self, ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
        await membre.kick(reason=raison)
        embed = discord.Embed(title="👢 Membre Expulsé", color=0xFF6600)
        embed.add_field(name="Membre", value=str(membre), inline=True)
        embed.add_field(name="Raison", value=raison, inline=True)
        await ctx.send(embed=embed)
        await utils.envoyer_log(
            ctx.guild, "👢 Membre Kické", f"Pseudo : **{membre}**\nRaison : {raison}",
            config.Couleurs.ORANGE_KICK, ctx.author,
        )

    @commands.command()
    @is_admin_staff_or_higher()
    async def ban(self, ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
        await membre.ban(reason=raison)
        embed = discord.Embed(title="🔨 Membre banni", color=config.Couleurs.ERREUR)
        embed.add_field(name="Membre", value=str(membre), inline=True)
        embed.add_field(name="Raison", value=raison, inline=True)
        await ctx.send(embed=embed)
        await utils.envoyer_log(
            ctx.guild, "🔨 Membre Banni", f"Pseudo : **{membre}**\nRaison : {raison}",
            config.Couleurs.NEUTRE, ctx.author,
        )

    @app_commands.command(name="unban", description="Débannir un membre")
    @is_admin_staff_or_higher_app()
    async def unban_cmd(self, interaction: discord.Interaction, user_id: str):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user)
            await interaction.response.send_message(f"✅ {user} débanni.", ephemeral=True)
            await utils.envoyer_log(
                interaction.guild, "🔓 Membre Débanni", f"L'utilisateur **{user}** ({user_id}) a été débanni.",
                config.Couleurs.SUCCES, interaction.user,
            )
        except (discord.NotFound, discord.HTTPException, ValueError):
            await interaction.response.send_message("❌ ID introuvable ou impossible de débannir ce membre.", ephemeral=True)

    # ── Divers ────────────────────────────────────────────────────────────
    @app_commands.command(name="slowmode", description="Définir le mode lent d'un salon")
    @is_admin_staff_or_higher_app()
    async def slowmode_cmd(self, interaction: discord.Interaction, secondes: int):
        await interaction.channel.edit(slowmode_delay=secondes)
        await interaction.response.send_message(f"✅ Mode lent : `{secondes}s`.")

    @app_commands.command(name="clear", description="Supprimer massivement des messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_cmd(self, interaction: discord.Interaction, montant: int = 100, membre: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        if membre:
            deleted = await interaction.channel.purge(limit=montant, check=lambda m: m.author.id == membre.id)
        else:
            deleted = await interaction.channel.purge(limit=montant)
        await interaction.followup.send(f"✅ `{len(deleted)}` messages supprimés.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
