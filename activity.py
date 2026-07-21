"""
Cog "activité" : pause de salon + système d'XP.

⚠️ Ces deux features vivent dans le même `on_message` volontairement, comme
dans le fichier d'origine : la pause doit court-circuiter (delete + return)
*avant* tout gain d'XP pour le même message. Les séparer en deux listeners
`on_message` indépendants dans deux cogs différents changerait le
comportement (un message supprimé pour cause de pause pourrait quand même
donner de l'XP, car discord.py appelle tous les listeners enregistrés).
On les garde donc groupés ici pour ne rien changer au comportement, avec
ce commentaire pour que le prochain lecteur ne les sépare pas par erreur.
"""
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

import config
from permissions import is_admin_staff_or_higher_app


class Activity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = bot.store
        self._cooldown_xp: dict[str, float] = {}
        self._pause_dernier_message: dict[str, float] = {}

    # ── Gate de pause + XP ───────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        cid = str(message.channel.id)
        delai_pause = self.store.salon_pauses.get(cid)
        if delai_pause:
            maintenant_pause = datetime.now().timestamp()
            dernier_message = self._pause_dernier_message.get(cid)
            if dernier_message is not None and maintenant_pause - dernier_message < delai_pause:
                restant = delai_pause - (maintenant_pause - dernier_message)
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                try:
                    await message.channel.send(
                        f"⏳ {message.author.mention} Ce salon est en pause, réessaie dans `{restant:.1f}s`.",
                        delete_after=5,
                    )
                except discord.HTTPException:
                    pass
                return
            self._pause_dernier_message[cid] = maintenant_pause

        uid = str(message.author.id)
        gid = str(message.guild.id)
        now = datetime.now().timestamp()

        key = f"{gid}_{uid}"
        if key in self._cooldown_xp and now - self._cooldown_xp[key] < config.XP_COOLDOWN_SECONDS:
            await self.bot.process_commands(message)
            return

        self._cooldown_xp[key] = now

        levels = self.store.levels
        levels.setdefault(gid, {})
        levels[gid].setdefault(uid, {"xp": 0, "niveau": 0, "messages": 0})

        ancien_niveau = levels[gid][uid]["niveau"]
        levels[gid][uid]["xp"] += config.XP_PAR_MESSAGE
        levels[gid][uid]["messages"] += 1
        nouveau_niveau = self._get_niveau(levels[gid][uid]["xp"])
        levels[gid][uid]["niveau"] = nouveau_niveau
        await self.store.save("levels")

        if nouveau_niveau > ancien_niveau:
            embed = discord.Embed(
                title="⭐ Level Up !",
                description=f"Bravo {message.author.mention} ! Tu es maintenant **niveau {nouveau_niveau}** !",
                color=config.Couleurs.OR,
            )
            await message.channel.send(embed=embed)

            if nouveau_niveau in config.ROLES_NIVEAUX:
                role = discord.utils.get(message.guild.roles, name=config.ROLES_NIVEAUX[nouveau_niveau])
                if role:
                    await message.author.add_roles(role)

        await self.bot.process_commands(message)

    @staticmethod
    def _xp_pour_niveau(niveau: int) -> int:
        return 100 * (niveau ** 2)

    def _get_niveau(self, xp: int) -> int:
        niveau = 0
        while xp >= self._xp_pour_niveau(niveau + 1):
            niveau += 1
        return niveau

    # ── Commandes ─────────────────────────────────────────────────────────
    @app_commands.command(name="pause", description="Cooldown global sur un salon")
    @is_admin_staff_or_higher_app()
    async def pause_cmd(self, interaction: discord.Interaction, secondes: int):
        cid = str(interaction.channel.id)
        if secondes == 0:
            self.store.salon_pauses.pop(cid, None)
            self._pause_dernier_message.pop(cid, None)
        else:
            self.store.salon_pauses[cid] = secondes
            self._pause_dernier_message.pop(cid, None)
        await self.store.save("salon_pauses")
        await interaction.response.send_message(f"✅ Pause réglée à `{secondes}s`.")

    @app_commands.command(name="niveau", description="Voir ton niveau d'XP")
    async def niveau_cmd(self, interaction: discord.Interaction, membre: discord.Member = None):
        cible = membre or interaction.user
        gid = str(interaction.guild.id)
        data = self.store.levels.get(gid, {}).get(str(cible.id), {"xp": 0, "niveau": 0})
        embed = discord.Embed(title=f"⭐ Niveau de {cible.display_name}", color=config.Couleurs.OR)
        embed.add_field(name="Niveau", value=str(data["niveau"]), inline=True)
        embed.add_field(name="XP", value=str(data["xp"]), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="classement", description="Top 10 du classement XP")
    async def classement_cmd(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        top = sorted(self.store.levels.get(gid, {}).items(), key=lambda x: x[1].get("xp", 0), reverse=True)[:10]
        description = "\n".join(f"<@{u}> : Lvl {d['niveau']} ({d['xp']} XP)" for u, d in top) or "Aucun membre."
        embed = discord.Embed(title="🏆 Classement", description=description, color=config.Couleurs.OR)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Activity(bot))
