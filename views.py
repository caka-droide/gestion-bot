"""
Composants d'interface persistants (boutons, menus, modals).

Regroupés ici car ce sont tous des `discord.ui.View`/`Modal` avec
`timeout=None` et des `custom_id` fixes : ils doivent être ré-enregistrés au
démarrage via `bot.add_view(...)` pour rester fonctionnels après un redémarrage.
Les garder ensemble facilite cette étape d'enregistrement dans `bot.py`.
"""
import asyncio

import discord

import config
import utils
from permissions import est_staff


# ── Tickets ───────────────────────────────────────────────────────────────────
async def creer_salon_ticket(guild: discord.Guild, membre: discord.Member, raison: str = None):
    """Crée le salon privé du ticket et y poste le message d'accueil."""
    category = guild.get_channel(config.CATEGORY_TICKETS_ID)
    nom_salon = f"ticket-{membre.name.lower()}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        membre: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }

    ticket_channel = await guild.create_text_channel(name=nom_salon, category=category, overwrites=overwrites)

    embed = discord.Embed(
        title="🎫 Nouveau Ticket",
        description=(
            f"Bonjour {membre.mention},\nL'équipe du staff te répondra dès que possible.\n\n"
            "*Pour fermer ce ticket, clique sur le bouton rouge ci-dessous.*"
        ),
        color=config.Couleurs.INFO_SOMBRE,
    )
    if raison:
        embed.add_field(name="Raison de l'ouverture", value=raison, inline=False)

    message_ping = f"<@&{config.ROLE_STAFF_ID}> <@&{config.ROLE_ADMIN_STAFF_ID}>"
    await ticket_channel.send(content=message_ping, embed=embed, view=CloseButton())
    await utils.envoyer_log(
        guild, "🎫 Ticket Ouvert", f"Ticket créé par {membre.mention} ({ticket_channel.mention})",
        config.Couleurs.SUCCES, membre,
    )
    return ticket_channel


class ConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🔒 **Le ticket va se fermer et être supprimé dans 5 secondes...**", view=self
        )
        try:
            await utils.envoyer_transcript(interaction.guild, interaction.channel, interaction.user)
        except Exception as e:
            print(f"Erreur génération transcript : {e}")

        await utils.envoyer_log(
            interaction.guild, "🔒 Ticket Fermé", f"Le salon `{interaction.channel.name}` a été supprimé.",
            config.Couleurs.ERREUR, interaction.user,
        )
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas la permission de supprimer ce salon.", ephemeral=True)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def annuler(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Fermeture annulée.", view=self)


class CloseButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger,
                       custom_id="fermer_ticket_btn", emoji="🔒")
    async def bouton_fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "⚠️ **Es-tu sûr de vouloir fermer ce ticket ?** Le salon sera supprimé définitivement.",
            view=ConfirmCloseView(),
        )


class TicketRequestView(discord.ui.View):
    """Boutons Accepter/Refuser postés dans le salon de demandes. Sans état interne
    (tout est relu depuis l'embed) pour rester fonctionnel même après un redémarrage du bot."""

    def __init__(self):
        super().__init__(timeout=None)

    def _lire_demande(self, message: discord.Message):
        embed = message.embeds[0]
        champ_demandeur = discord.utils.get(embed.fields, name="Demandeur")
        champ_raison = discord.utils.get(embed.fields, name="Raison")
        demandeur_id = int(champ_demandeur.value.split("`")[1])
        raison = champ_raison.value if champ_raison else None
        return demandeur_id, raison

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success,
                       custom_id="accepter_demande_ticket_btn", emoji="✅")
    async def accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not est_staff(interaction.user):
            await interaction.response.send_message("❌ Réservé au staff.", ephemeral=True)
            return

        demandeur_id, raison = self._lire_demande(interaction.message)
        membre = interaction.guild.get_member(demandeur_id)
        if not membre:
            await interaction.response.send_message(
                "❌ Ce membre a quitté le serveur, impossible de créer le ticket.", ephemeral=True
            )
            return

        nom_salon = f"ticket-{membre.name.lower()}"
        if discord.utils.get(interaction.guild.text_channels, name=nom_salon):
            await interaction.response.send_message("❌ Un ticket est déjà ouvert pour ce membre.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            ticket_channel = await creer_salon_ticket(interaction.guild, membre, raison)
        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas la permission de créer le salon.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = config.Couleurs.SUCCES
        embed.add_field(name="Statut", value=f"✅ Accepté par {interaction.user.mention}", inline=False)
        await interaction.edit_original_response(embed=embed, view=self)

        try:
            await membre.send(f"✅ Ton ticket a été accepté : {ticket_channel.mention}")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger,
                       custom_id="refuser_demande_ticket_btn", emoji="✖️")
    async def refuser(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not est_staff(interaction.user):
            await interaction.response.send_message("❌ Réservé au staff.", ephemeral=True)
            return

        demandeur_id, _ = self._lire_demande(interaction.message)
        membre = interaction.guild.get_member(demandeur_id)

        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = 0xE74C3C
        embed.add_field(name="Statut", value=f"❌ Refusé par {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        if membre:
            try:
                await membre.send("❌ Ta demande de ticket a été refusée par le staff.")
            except discord.HTTPException:
                pass


class TicketReasonModal(discord.ui.Modal, title="Ouvrir un ticket"):
    raison = discord.ui.TextInput(
        label="Raison de l'ouverture du ticket",
        style=discord.TextStyle.paragraph,
        placeholder="Explique brièvement ta demande...",
        max_length=500,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        salon_demande = guild.get_channel(config.SALON_DEMANDE_TICKET_ID)
        if not salon_demande:
            await interaction.response.send_message(
                "❌ Le salon de demandes de tickets est introuvable, contacte un admin.", ephemeral=True
            )
            return

        embed = discord.Embed(title="🎫 Nouvelle demande de ticket", color=config.Couleurs.JAUNE)
        embed.add_field(name="Demandeur", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Raison", value=self.raison.value, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await salon_demande.send(embed=embed, view=TicketRequestView())
        await interaction.response.send_message(
            "✅ Ta demande a été envoyée au staff, tu seras notifié dès qu'elle sera traitée !", ephemeral=True
        )


class TicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket", style=discord.ButtonStyle.primary,
                       custom_id="creer_ticket_btn", emoji="🎫")
    async def bouton_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        nom_salon = f"ticket-{interaction.user.name.lower()}"
        salon_existant = discord.utils.get(guild.text_channels, name=nom_salon)

        if salon_existant:
            await interaction.response.send_message(
                f"❌ Tu as déjà un ticket ouvert : {salon_existant.mention}", ephemeral=True
            )
            return

        await interaction.response.send_modal(TicketReasonModal())


# ── Règlement / Rôles ─────────────────────────────────────────────────────────
class ReglementView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="J'ai lu et j'accepte le règlement", style=discord.ButtonStyle.success,
                       custom_id="reglement_accept_btn", emoji="✅")
    async def bouton_accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ Le rôle configuré pour le règlement est introuvable.", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.response.send_message("✅ Tu as déjà validé le règlement, tu as accès au serveur !", ephemeral=True)
            return

        try:
            await interaction.user.add_roles(role, reason="Règlement accepté")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de t'attribuer ce rôle.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ Merci d'avoir lu le règlement ! Le rôle **{role.name}** t'a été attribué.", ephemeral=True
        )


class RoleMenuView(discord.ui.View):
    def __init__(self, roles: list):
        super().__init__(timeout=None)
        self.roles_map = {str(r.id): r for r in roles}
        self.select = discord.ui.Select(
            placeholder="Choisis un ou plusieurs rôles...",
            min_values=0, max_values=len(roles), custom_id="role_menu_select",
            options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in roles],
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        selectionnes = set(self.select.values)
        membre = interaction.user
        ajoutes, retires = [], []
        for role_id, role in self.roles_map.items():
            a_le_role = role in membre.roles
            if role_id in selectionnes and not a_le_role:
                ajoutes.append(role)
            elif role_id not in selectionnes and a_le_role:
                retires.append(role)
        try:
            if ajoutes:
                await membre.add_roles(*ajoutes)
            if retires:
                await membre.remove_roles(*retires)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de gérer ces rôles.", ephemeral=True)
            return

        await interaction.response.send_message("✅ Tes rôles ont été mis à jour !", ephemeral=True)
