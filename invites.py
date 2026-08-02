"""Cog: tracking des invitations, messages de bienvenue/départ."""
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
import guild_settings


def _entry_id(entry) -> str:
    """Les anciennes entrées 'joined'/'left' sont de simples ID (str).
    Les nouvelles sont des dicts {"id": ..., "at": ...}. Cette fonction
    gère les deux formats pour rester compatible avec les données déjà
    stockées avant l'ajout de l'horodatage."""
    return entry.get("id") if isinstance(entry, dict) else entry


def _entry_time(entry):
    """Renvoie l'ISO timestamp d'une entrée, ou None si absent (ancienne donnée)."""
    return entry.get("at") if isinstance(entry, dict) else None


def _fmt_ts(iso: str) -> str:
    if not iso:
        return "date inconnue"
    try:
        dt = datetime.fromisoformat(iso)
        unix = int(dt.timestamp())
        return f"<t:{unix}:f> (<t:{unix}:R>)"
    except (ValueError, TypeError):
        return "date inconnue"


class Invites(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = bot.store

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        gid = str(invite.guild.id)
        self.store.invites.setdefault(gid, {})
        self.store.invites[gid][invite.code] = {
            "inviter_id": str(invite.inviter.id) if invite.inviter else None,
            "uses": 0, "joined": [], "left": [],
        }
        await self.store.save("invites")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        gid = str(member.guild.id)
        try:
            await member.send(f"Salut {member.mention} ! Bienvenue sur **{member.guild.name}** ! 🎉")
        except discord.HTTPException:
            pass

        salon_bienvenue = member.guild.get_channel(
            guild_settings.get_id(member.guild.id, "SALON_BIENVENUE_ID")
        )
        if salon_bienvenue:
            embed = discord.Embed(
                title="👋 Un nouveau membre vient d'arriver !",
                description=(
                    f"Bienvenue {member.mention} sur **{member.guild.name}** !\n"
                    f"Nous sommes maintenant {member.guild.member_count} membres."
                ),
                color=config.Couleurs.SUCCES,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await salon_bienvenue.send(embed=embed)

        try:
            new_invites = await member.guild.invites()
        except discord.HTTPException:
            return

        old_invites = self.store.invites.get(gid, {})
        for inv in new_invites:
            old_uses = old_invites.get(inv.code, {}).get("uses", 0)
            if inv.uses is not None and inv.uses > old_uses:
                self.store.invites.setdefault(gid, {})
                self.store.invites[gid].setdefault(
                    inv.code,
                    {"inviter_id": str(inv.inviter.id) if inv.inviter else None, "uses": 0, "joined": [], "left": []},
                )
                self.store.invites[gid][inv.code]["uses"] = inv.uses
                self.store.invites[gid][inv.code]["joined"].append({
                    "id": str(member.id),
                    "at": datetime.now(timezone.utc).isoformat(),
                })
                await self.store.save("invites")
                break

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        gid = str(member.guild.id)
        uid = str(member.id)
        salon_depart = member.guild.get_channel(
            guild_settings.get_id(member.guild.id, "SALON_DEPART_ID")
        )
        if salon_depart:
            embed = discord.Embed(
                title="😢 Départ d'un membre",
                description=f"**{member.display_name}** a quitté le serveur. À bientôt...",
                color=config.Couleurs.ERREUR,
            )
            await salon_depart.send(embed=embed)

        if gid in self.store.invites:
            for code, data in self.store.invites[gid].items():
                joined_ids = [_entry_id(e) for e in data.get("joined", [])]
                if uid in joined_ids:
                    data.setdefault("left", []).append({
                        "id": uid,
                        "at": datetime.now(timezone.utc).isoformat(),
                    })
                    await self.store.save("invites")
                    break

    @commands.command(name="i")
    async def i_cmd(self, ctx, *args: str):
        """
        +i                -> stats globales de l'auteur (comme avant)
        +i 5              -> stats globales de l'auteur + 5 dernières invitations avec l'heure
        +i @membre        -> stats globales d'un autre membre
        +i @membre 5      -> stats globales d'un autre membre + ses 5 dernières invitations
        (fonctionne aussi avec un ID brut à la place de la mention)
        """
        cible = ctx.author
        nombre = None

        if ctx.message.mentions:
            cible = ctx.message.mentions[0]

        for arg in args:
            if not arg.isdigit():
                continue
            valeur = int(arg)
            candidat = ctx.guild.get_member(valeur)
            if candidat and not ctx.message.mentions:
                cible = candidat
            else:
                nombre = valeur

        gid, uid = str(ctx.guild.id), str(cible.id)

        total_joins = total_left = 0
        codes_utilises = []
        derniers_joins = []
        for code, data in self.store.invites.get(gid, {}).items():
            if data.get("inviter_id") == uid:
                joined_list = data.get("joined", [])
                left_list = data.get("left", [])
                joins = len(joined_list)
                left = len(left_list)
                total_joins += joins
                total_left += left
                if joins > 0:
                    codes_utilises.append(f"`{code}` : {joins} invités ({left} partis)")
                for entry in joined_list:
                    derniers_joins.append((_entry_id(entry), _entry_time(entry)))

        restes = total_joins - total_left
        embed = discord.Embed(title=f"📨 Invitations de {cible.display_name}", color=config.Couleurs.DEFAUT)
        embed.add_field(name="Total invités", value=str(total_joins), inline=True)
        embed.add_field(name="Restés", value=str(restes), inline=True)
        embed.add_field(name="Partis", value=str(total_left), inline=True)
        if codes_utilises:
            embed.add_field(name="Détail par lien", value="\n".join(codes_utilises[:5]), inline=False)

        if derniers_joins and nombre is not None:
            # Les entrées sans horodatage (invitations enregistrées avant cette
            # mise à jour) sont triées en dernier.
            derniers_joins.sort(key=lambda entry: entry[1] or "", reverse=True)
            limite = max(1, min(nombre, 25))
            lignes = [f"<@{mid}> — {_fmt_ts(at)}" for mid, at in derniers_joins[:limite]]
            embed.add_field(
                name=f"🕒 Dernières invitations ({min(len(derniers_joins), limite)}/{len(derniers_joins)})",
                value="\n".join(lignes),
                inline=False,
            )

        embed.set_thumbnail(url=cible.display_avatar.url)
        await ctx.send(embed=embed)

    @app_commands.command(name="invitations", description="Voir tes invitations")
    async def invitations_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "👉 Utilise la commande `+i` dans le chat pour voir tes invitations !", ephemeral=True
        )

    async def refresh_invite_cache(self):
        """Recharge le cache d'invitations pour tous les serveurs (appelé au démarrage)."""
        for guild in self.bot.guilds:
            gid = str(guild.id)
            try:
                invites = await guild.invites()
            except discord.HTTPException:
                continue
            self.store.invites.setdefault(gid, {})
            for inv in invites:
                existing = self.store.invites[gid].get(inv.code, {})
                self.store.invites[gid][inv.code] = {
                    "inviter_id": str(inv.inviter.id) if inv.inviter else None,
                    "uses": inv.uses,
                    "joined": existing.get("joined", []),
                    "left": existing.get("left", []),
                }
            await self.store.save("invites")


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
