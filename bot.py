"""
Point d'entrée du bot.

Contient uniquement la "colle" : création du bot, chargement des cogs et des
données, ré-enregistrement des Views persistantes, sync des commandes, et les
gestionnaires d'erreurs globaux. Toute la logique métier vit dans les cogs.
"""
import discord
from discord.ext import commands
from discord import app_commands

import config
from storage import UpstashClient, DataStore
from views import TicketButton, CloseButton, TicketRequestView, ReglementView, RoleMenuView

EXTENSIONS = (
    "cogs.activity",
    "cogs.moderation",
    "cogs.tickets",
    "cogs.invites",
    "cogs.giveaways",
    "cogs.owner",
    "cogs.general",
)


class GestionBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=config.COMMAND_PREFIXES, intents=intents, help_command=None)
        self.store = DataStore(UpstashClient(config.UPSTASH_URL, config.UPSTASH_TOKEN))
        # Équivalent du `premiere_connexion` global de l'ancien fichier : on_ready
        # peut être redéclenché après une reconnexion, on ne veut faire
        # l'initialisation (views/sync/cache d'invites/loop) qu'une seule fois.
        self._deja_initialise = False

    async def setup_hook(self):
        await self.store.load_all()
        for extension in EXTENSIONS:
            await self.load_extension(extension)

    async def on_ready(self):
        print(f"✅ Bot connecté : {self.user}")

        if self._deja_initialise:
            return
        self._deja_initialise = True

        self.add_view(TicketButton())
        self.add_view(CloseButton())
        self.add_view(TicketRequestView())

        for message_id, data in self.store.reglement.items():
            guild = self.get_guild(data["guild_id"])
            role = guild.get_role(data["role_id"]) if guild else None
            if role:
                self.add_view(ReglementView(role.id), message_id=int(message_id))

        for message_id, data in self.store.role_menus.items():
            guild = self.get_guild(data["guild_id"])
            if guild:
                roles = [r for rid in data.get("role_ids", []) if (r := guild.get_role(rid))]
                if roles:
                    self.add_view(RoleMenuView(roles), message_id=int(message_id))

        try:
            synced = await self.tree.sync()
            print(f"✅ {len(synced)} commandes synchronisées")
        except discord.HTTPException as e:
            print(f"❌ Erreur sync : {e}")

        await self.get_cog("Invites").refresh_invite_cache()
        self.get_cog("Giveaways").start_loop()

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, (commands.MissingPermissions, commands.CheckFailure)):
            await ctx.send("❌ **Accès refusé :** Tu n'as pas les permissions pour cette commande.")
            return
        if isinstance(error, commands.MemberNotFound):
            await ctx.send(f"❌ Membre introuvable : `{error.argument}`. Utilise une mention ou un ID valide.")
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Il manque un argument (`{error.param.name}`). Tape `+help` pour voir la syntaxe.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send("❌ Argument invalide. Vérifie la syntaxe de la commande avec `+help`.")
            return
        print(f"❌ Erreur non gérée sur la commande '{ctx.command}' : {error}")


bot = GestionBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.CheckFailure):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ **Accès refusé :** Commande réservée.", ephemeral=True)
        return
    print(f"❌ Erreur non gérée sur la commande slash '{interaction.command}' : {error}")
