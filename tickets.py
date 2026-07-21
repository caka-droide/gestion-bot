"""Cog: commandes préfixe utilisées à l'intérieur d'un salon de ticket."""
import discord
from discord.ext import commands

import config
import utils
from permissions import is_staff_or_higher, est_salon_ticket


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="rename")
    @is_staff_or_higher()
    async def rename_cmd(self, ctx, *, nouveau_nom: str):
        if not est_salon_ticket(ctx.channel):
            await ctx.send("❌ Cette commande ne peut être utilisée que dans un salon de ticket.")
            return

        nouveau_nom_propre = nouveau_nom.lower().strip().replace(" ", "-")[:100]
        ancien_nom = ctx.channel.name

        try:
            await ctx.channel.edit(name=nouveau_nom_propre)
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission de renommer ce salon.")
            return
        except discord.HTTPException as e:
            await ctx.send(f"❌ Impossible de renommer ce salon : {e}")
            return

        await ctx.send(f"✅ Ticket renommé en `{nouveau_nom_propre}`.")
        await utils.envoyer_log(
            ctx.guild, "✏️ Ticket Renommé", f"`{ancien_nom}` → `{nouveau_nom_propre}` par {ctx.author.mention}",
            config.Couleurs.DEFAUT, ctx.author,
        )

    @commands.command(name="staff")
    @is_staff_or_higher()
    async def staff_cmd(self, ctx, membre: discord.Member):
        if not est_salon_ticket(ctx.channel):
            await ctx.send("❌ Cette commande ne peut être utilisée que dans un salon de ticket.")
            return
        try:
            await ctx.channel.set_permissions(membre, read_messages=True, send_messages=True,
                                               reason=f"Ajouté au ticket par {ctx.author}")
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission de modifier les accès de ce salon.")
            return

        await ctx.send(f"✅ {membre.mention} a été ajouté à ce ticket.")
        await utils.envoyer_log(
            ctx.guild, "➕ Staff Ajouté au Ticket",
            f"{membre.mention} ajouté au ticket {ctx.channel.mention} par {ctx.author.mention}",
            config.Couleurs.SUCCES, ctx.author,
        )

    @commands.command(name="unstaff")
    @is_staff_or_higher()
    async def unstaff_cmd(self, ctx, membre: discord.Member):
        if not est_salon_ticket(ctx.channel):
            await ctx.send("❌ Cette commande ne peut être utilisée que dans un salon de ticket.")
            return
        try:
            await ctx.channel.set_permissions(membre, overwrite=None, reason=f"Retiré du ticket par {ctx.author}")
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission de modifier les accès de ce salon.")
            return

        await ctx.send(f"✅ {membre.mention} a été retiré de ce ticket.")
        await utils.envoyer_log(
            ctx.guild, "➖ Staff Retiré du Ticket",
            f"{membre.mention} retiré du ticket {ctx.channel.mention} par {ctx.author.mention}",
            config.Couleurs.ORANGE_KICK, ctx.author,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
