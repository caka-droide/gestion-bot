"""Cog: giveaways (lancement, reroll, fin, boucle de vérification)."""
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import utils
from permissions import is_admin_staff_or_higher_app
from invites import count_new_invites

# Bonus par défaut (en points de %) accordé par invitation faite au-delà du
# minimum requis, si /gwinv n'a jamais été utilisé sur la guild.
DEFAULT_BONUS_PERCENT = 0.5


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = bot.store

    def cog_unload(self):
        self.check_giveaways.cancel()

    def _gw_settings(self, guild_id: int) -> dict:
        conf = self.store.gw_settings.get(str(guild_id), {})
        return {
            "min_invites": conf.get("min_invites", 0),
            "bonus_percent": conf.get("bonus_percent", DEFAULT_BONUS_PERCENT),
        }

    @staticmethod
    def _weighted_draw(participants_weights: list, k: int) -> list:
        """Tirage pondéré SANS remise (algorithme d'Efraimidis-Spirakis) :
        chaque participant reçoit une clé aléatoire dépendant de son poids,
        et on garde les k meilleures clés. Plus le poids est élevé, plus la
        probabilité d'être tiré est grande, exactement comme un tirage à la
        tombola où on aurait un nombre de tickets proportionnel au poids."""
        if k <= 0 or not participants_weights:
            return []
        keyed = []
        for user, weight in participants_weights:
            weight = max(weight, 1e-9)
            cle = random.random() ** (1.0 / weight)
            keyed.append((cle, user))
        keyed.sort(key=lambda x: x[0], reverse=True)
        return [user for _, user in keyed[:k]]

    def start_loop(self):
        """Démarre la boucle de vérification si elle ne tourne pas déjà.
        Appelé depuis on_ready (une seule fois), comme dans le code d'origine."""
        if not self.check_giveaways.is_running():
            self.check_giveaways.start()

    def _weighted_participants(self, data: dict, participants: list) -> list:
        """Calcule le poids de tirage de chaque participant à partir de ses
        invitations faites DEPUIS LE LANCEMENT du giveaway (data["start_time"]),
        sans toucher au compteur global utilisé par +i.

        - En dessous du minimum requis (data["min_invites"]) : exclu du
          tirage. C'est une sécurité en plus du retrait automatique de
          réaction (utile si le bot était hors ligne au moment du clic).
        - Poids de base = 1 pour tout le monde à l'exact minimum.
        - Chaque invitation au-delà du minimum ajoute un bonus calibré pour
          valoir ~`bonus_percent` points de % de chance, quel que soit le
          nombre de participants (le bonus est donc mis à l'échelle par le
          nombre de participants éligibles `n`)."""
        min_invites = data.get("min_invites", 0)
        bonus_percent = data.get("bonus_percent", DEFAULT_BONUS_PERCENT)
        start_time = data.get("start_time", 0)
        guild_id = data["guild_id"]

        comptes = {
            u.id: count_new_invites(self.store, guild_id, u.id, start_time)
            for u in participants
        }
        eligibles = [u for u in participants if comptes[u.id] >= min_invites]
        n = len(eligibles)
        if n == 0:
            return []

        return [
            (u, 1 + max(0, comptes[u.id] - min_invites) * (bonus_percent / 100) * n)
            for u in eligibles
        ]

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
        poids = self._weighted_participants(data, participants)

        nb_gagnants = force_gagnants if force_gagnants else data["gagnants"]
        gagnants = self._weighted_draw(poids, min(nb_gagnants, len(poids)))

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

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Empêche de participer à un giveaway tant que le nombre
        d'invitations minimum (faites après le lancement) n'est pas atteint.
        Ne touche à rien du système d'invitations lui-même : ne fait que le
        consulter via count_new_invites()."""
        if payload.member is None or payload.member.bot:
            return
        if str(payload.emoji) != config.GIVEAWAY_EMOJI:
            return

        data = self.store.giveaways.get(str(payload.message_id))
        if not data or data.get("ended"):
            return

        min_invites = data.get("min_invites", 0)
        if min_invites <= 0:
            return

        nb_invites = count_new_invites(
            self.store, data["guild_id"], payload.member.id, data.get("start_time", 0)
        )
        if nb_invites >= min_invites:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, payload.member)
        except discord.HTTPException:
            pass

        manque = min_invites - nb_invites
        texte = (
            f"❌ Tu ne peux pas encore participer à ce giveaway : il te manque "
            f"**{manque} invitation(s)** faite(s) *après le lancement du giveaway* "
            f"(minimum requis : {min_invites}, tu en as {nb_invites})."
        )
        try:
            await payload.member.send(texte)
        except discord.HTTPException:
            try:
                await channel.send(f"{payload.member.mention} {texte}", delete_after=10)
            except discord.HTTPException:
                pass

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

        debut = datetime.now(timezone.utc)
        fin = debut + timedelta(seconds=secondes)
        reglages = self._gw_settings(interaction.guild.id)
        min_invites = reglages["min_invites"]
        bonus_percent = reglages["bonus_percent"]

        description = f"**Lot : {prix}**\nFin : <t:{int(fin.timestamp())}:R>"
        if min_invites > 0:
            description += (
                f"\n\n🎟️ **Invitations requises : {min_invites}**"
                f" (nouveaux membres invités *après le lancement de ce giveaway*)"
                f"\n✨ Chaque invitation en plus donne **+{bonus_percent}%** de chance de gagner !"
            )
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=description,
            color=config.Couleurs.JAUNE,
        )
        await interaction.response.send_message("✅ Giveaway lancé !", ephemeral=True)
        message = await interaction.channel.send(embed=embed)
        await message.add_reaction(config.GIVEAWAY_EMOJI)

        self.store.giveaways[str(message.id)] = {
            "guild_id": interaction.guild.id, "channel_id": interaction.channel.id,
            "host_id": interaction.user.id, "prix": prix, "gagnants": gagnants,
            "start_time": debut.timestamp(), "end_time": fin.timestamp(), "ended": False,
            "min_invites": min_invites, "bonus_percent": bonus_percent,
        }
        await self.store.save("giveaways")

    @app_commands.command(name="gwinv", description="Régler le nombre d'invitations requis pour participer aux giveaways")
    @is_admin_staff_or_higher_app()
    async def gwinv_cmd(
        self,
        interaction: discord.Interaction,
        minimum: int,
        bonus_pourcent: float = DEFAULT_BONUS_PERCENT,
    ):
        if minimum < 0:
            await interaction.response.send_message("❌ Le minimum ne peut pas être négatif.", ephemeral=True)
            return
        if bonus_pourcent < 0:
            await interaction.response.send_message("❌ Le bonus ne peut pas être négatif.", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        self.store.gw_settings[gid] = {"min_invites": minimum, "bonus_percent": bonus_pourcent}
        await self.store.save("gw_settings")

        if minimum > 0:
            texte = (
                f"✅ Il faudra désormais **{minimum} invitation(s)** faites *après le lancement* "
                f"d'un giveaway pour pouvoir y participer.\n"
                f"✨ Chaque invitation en plus donnera **+{bonus_pourcent}%** de chance de gagner.\n"
                f"⚠️ Ce réglage s'applique aux **prochains** `/gw` lancés, pas à ceux déjà en cours."
            )
        else:
            texte = "✅ Plus aucun minimum d'invitations requis pour participer aux giveaways."
        await interaction.response.send_message(texte, ephemeral=True)

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
