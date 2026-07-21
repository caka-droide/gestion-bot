"""Cog: giveaways (lancement, reroll, fin, boucle de vérification)."""
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import utils
from permissions import is_admin_staff_or_higher_app


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = bot.store

    def cog_unload(self):
        self.check_giveaways.cancel()

    def start_loop(self):
        """Démarre la boucle de vérification si elle ne tourne pas déjà.
        Appelé depuis on_ready (une seule fois), comme dans le code d'origine."""
        if not self.check_giveaways.is_running():
            self.check_giveaways.start()

    async def terminer_giveaway(self, message_id, force_gagnants: int = None):
        data = self.store.giveaways.get(str(message_id))
        if not data:
            return None
        guild = self.bot.get_guild(data["guild_id"])
        if not guild:
            return None
        channel = guild.get_channel(data["channel_id"])
        if not channel:
            return None
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.HTTPException:
            data["ended"] = True
            await self.store.save("giveaways")
            return None

        reaction = discord.utils.get(message.reactions, emoji=config.GIVEAWAY_EMOJI)
        participants = [u async for u in reaction.users() if not u.bot] if reaction else []

        nb_gagnants = force_gagnants if force_gagnants else data["gagnants"]
        gagnants = random.sample(participants, min(nb_gagnants, len(participants))) if participants else []

        if gagnants:
            mentions = ", ".join(g.mention for g in gagnants)
            texte_resultat = f"🎉 Félicitations {mentions} ! Tu remportes **{data['prix']}** !"
        else:
            mentions = "Personne n'a participé"
            texte_resultat = f"😢 Personne n'a participé, aucun gagnant pour **{data['prix']}**."

        embed = message.embeds[0] if message.embeds else discord.Embed()
        embed.title = "🎉 GIVEAWAY TERMINÉ 🎉"
        embed.description = f"**Lot : {data['prix']}**\nGagnant(s) : {mentions}\nOrganisé par : <@{data['host_id']}>"
        embed.color = config.Couleurs.NEUTRE
        try:
            await message.edit(embed=embed)
        except discord.HTTPException:
            pass
        try:
            await channel.send(texte_resultat)
        except discord.HTTPException:
            pass

        data["ended"] = True
        await self.store.save("giveaways")
        return gagnants

    @tasks.loop(seconds=config.GIVEAWAY_CHECK_INTERVAL_SECONDS)
    async def check_giveaways(self):
        now = datetime.now().timestamp()
        a_terminer = [
            mid for mid, d in self.store.giveaways.items()
            if not d.get("ended") and now >= d.get("end_time", 0)
        ]
        for mid in a_terminer:
            await self.terminer_giveaway(mid)

    @app_commands.command(name="gw", description="Lancer un giveaway")
    @is_admin_staff_or_higher_app()
    async def gw_cmd(self, interaction: discord.Interaction, duree: str, prix: str, gagnants: int = 1):
        secondes = utils.parse_duree(duree)
        if not secondes:
            await interaction.response.send_message("❌ Durée invalide.", ephemeral=True)
            return

        fin = datetime.now(timezone.utc) + timedelta(seconds=secondes)
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"**Lot : {prix}**\nFin : <t:{int(fin.timestamp())}:R>",
            color=config.Couleurs.JAUNE,
        )
        await interaction.response.send_message("✅ Giveaway lancé !", ephemeral=True)
        message = await interaction.channel.send(embed=embed)
        await message.add_reaction(config.GIVEAWAY_EMOJI)

        self.store.giveaways[str(message.id)] = {
            "guild_id": interaction.guild.id, "channel_id": interaction.channel.id,
            "host_id": interaction.user.id, "prix": prix, "gagnants": gagnants,
            "end_time": fin.timestamp(), "ended": False,
        }
        await self.store.save("giveaways")

    @app_commands.command(name="gw_reroll", description="Retirer de nouveaux gagnants")
    @is_admin_staff_or_higher_app()
    async def gw_reroll_cmd(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        if await self.terminer_giveaway(message_id):
            await interaction.followup.send("✅ Gagnants retirés.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Erreur de reroll.", ephemeral=True)

    @app_commands.command(name="gw_end", description="Terminer un giveaway")
    @is_admin_staff_or_higher_app()
    async def gw_end_cmd(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        await self.terminer_giveaway(message_id)
        await interaction.followup.send("✅ Terminé.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
