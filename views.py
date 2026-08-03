"""
Composants d'interface persistants (boutons, menus, modals).

Regroupés ici car ce sont tous des discord.ui.View/Modal avec
timeout=None et des custom_id fixes : ils doivent être ré-enregistrés au
démarrage via bot.add_view(...) pour rester fonctionnels après un redémarrage.
Les garder ensemble facilite cette étape d'enregistrement dans bot.py.
"""
import asyncio
from datetime import datetime

import discord

import config
import guild_settings
import utils
from permissions import est_staff


async def creer_salon_ticket(guild: discord.Guild, membre: discord.Member, raison: str = None,
                              staff_qui_accepte: discord.Member = None, store=None):
    """Crée le salon privé du ticket et y poste le message d'accueil.

    Seul `staff_qui_accepte` (le membre du staff qui a cliqué Accepter) a accès
    au salon, en plus du demandeur. On refuse explicitement les rôles Staff et
    Admin Staff : sans ça, si ces rôles ont accès à la catégorie "Tickets", ils
    verraient quand même le salon par héritage. Un autre membre du staff peut
    toujours être ajouté ponctuellement via `+staff <@membre>`.
    """
    category_id = guild_settings.get_id(guild.id, "CATEGORY_TICKETS_ID")
    category = guild.get_channel(category_id)
    nom_salon = f"ticket-{membre.name.lower()}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        membre: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }

    role_staff = guild.get_role(guild_settings.get_id(guild.id, "ROLE_STAFF_ID"))
    role_admin_staff = guild.get_role(guild_settings.get_id(guild.id, "ROLE_ADMIN_STAFF_ID"))
    if role_staff:
        overwrites[role_staff] = discord.PermissionOverwrite(read_messages=False)
    if role_admin_staff:
        overwrites[role_admin_staff] = discord.PermissionOverwrite(read_messages=False)

    if staff_qui_accepte:
        # Overwrite explicite sur le membre : passe devant le refus du rôle
        # ci-dessus, donc lui seul (parmi le staff) garde accès.
        overwrites[staff_qui_accepte] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

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

    await ticket_channel.send(embed=embed, view=CloseButton())
    await utils.envoyer_log(
        guild, "🎫 Ticket Ouvert", f"Ticket créé par {membre.mention} ({ticket_channel.mention})",
        config.Couleurs.SUCCES, membre,
    )

    if store is not None and staff_qui_accepte is not None:
        store.tickets_info[str(ticket_channel.id)] = {
            "guild_id": guild.id,
            "staff_id": staff_qui_accepte.id,
            "staff_name": staff_qui_accepte.display_name,
            "demandeur_id": membre.id,
            "ticket_nom": ticket_channel.name,
        }
        await store.save("tickets_info")

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

        store = interaction.client.store
        ticket_info = store.tickets_info.pop(str(interaction.channel.id), None)
        if ticket_info is not None:
            await store.save("tickets_info")

        try:
            await utils.envoyer_transcript(interaction.guild, interaction.channel, interaction.user)
        except Exception as e:
            print(f"Erreur génération transcript : {e}")

        await utils.envoyer_log(
            interaction.guild, "🔒 Ticket Fermé", f"Le salon `{interaction.channel.name}` a été supprimé.",
            config.Couleurs.ERREUR, interaction.user,
        )

        if ticket_info is not None:
            await demander_avis(interaction.client, ticket_info)

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


async def demander_avis(bot, ticket_info: dict):
    """Envoie en MP au demandeur une demande d'avis sur le staff qui a traité
    son ticket, juste avant que le salon ne soit supprimé.

    `ticket_info` vient de `store.tickets_info` : {guild_id, staff_id,
    staff_name, demandeur_id, ticket_nom}. Si le membre a ses MP fermés,
    on abandonne silencieusement (rien de plus à faire côté bot).
    """
    demandeur = bot.get_user(ticket_info["demandeur_id"])
    if demandeur is None:
        try:
            demandeur = await bot.fetch_user(ticket_info["demandeur_id"])
        except discord.HTTPException:
            return

    embed = discord.Embed(
        title="⭐ Ton avis compte !",
        description=(
            f"Ton ticket `{ticket_info['ticket_nom']}` vient d'être fermé.\n"
            f"Merci de noter **{ticket_info['staff_name']}**, le membre du staff qui t'a pris en charge.\n\n"
            "Clique sur le nombre d'étoiles correspondant à ton expérience."
        ),
        color=config.Couleurs.JAUNE,
    )
    try:
        dm_message = await demandeur.send(embed=embed, view=AvisTicketView())
    except discord.HTTPException:
        return

    bot.store.avis_attente[str(dm_message.id)] = ticket_info
    await bot.store.save("avis_attente")


class AvisTicketModal(discord.ui.Modal, title="Ton avis sur le staff"):
    commentaire = discord.ui.TextInput(
        label="Commentaire (optionnel)",
        style=discord.TextStyle.paragraph,
        placeholder="Explique brièvement ton expérience...",
        max_length=500,
        required=False,
    )

    def __init__(self, note: int, dm_message_id: int):
        super().__init__()
        self.note = note
        self.dm_message_id = dm_message_id

    async def on_submit(self, interaction: discord.Interaction):
        store = interaction.client.store
        info = store.avis_attente.pop(str(self.dm_message_id), None)
        await store.save("avis_attente")

        if info is None:
            await interaction.response.send_message(
                "❌ Cette demande d'avis n'est plus valide (avis déjà envoyé ?).", ephemeral=True
            )
            return

        gid = str(info["guild_id"])
        store.avis_tickets.setdefault(gid, []).append({
            "staff_id": info["staff_id"],
            "staff_name": info["staff_name"],
            "note": self.note,
            "texte": self.commentaire.value or None,
            "demandeur_id": info["demandeur_id"],
            "ticket_nom": info["ticket_nom"],
        })
        await store.save("avis_tickets")

        avis_de_ce_staff = [a for a in store.avis_tickets[gid] if a["staff_id"] == info["staff_id"]]
        moyenne = sum(a["note"] for a in avis_de_ce_staff) / len(avis_de_ce_staff)

        guild = interaction.client.get_guild(info["guild_id"])
        salon_avis = guild.get_channel(guild_settings.get_id(info["guild_id"], "SALON_AVIS_TICKETS_ID")) if guild else None
        if salon_avis:
            embed = discord.Embed(
                title="📊 Nouveau Avis",
                description="⭐" * self.note,
                color=config.Couleurs.JAUNE,
                timestamp=datetime.now(),
            )
            embed.add_field(name="👮 Staff", value=info["staff_name"], inline=False)
            embed.add_field(name="⭐ Note", value=f"{self.note}/5", inline=False)
            embed.add_field(name="📊 Moyenne", value=f"{moyenne:.2f}/5", inline=False)
            if self.commentaire.value:
                embed.add_field(name="📝 Commentaire", value=self.commentaire.value, inline=False)
            embed.set_footer(text="Système d'évaluation des tickets")
            try:
                await salon_avis.send(embed=embed)
            except discord.Forbidden:
                pass

        try:
            dm_channel = interaction.channel
            message_original = await dm_channel.fetch_message(self.dm_message_id)
            await message_original.edit(
                embed=discord.Embed(
                    description="✅ Merci, ton avis a bien été envoyé !", color=config.Couleurs.SUCCES
                ),
                view=None,
            )
        except discord.HTTPException:
            pass

        await interaction.response.send_message("✅ Merci pour ton avis, il a bien été enregistré !", ephemeral=True)


class AvisTicketView(discord.ui.View):
    """Boutons étoiles envoyés en MP au demandeur après la fermeture de son
    ticket. La note (1 à 5) est obligatoire pour arriver jusqu'à la modale ;
    le commentaire demandé dans la modale, lui, reste facultatif."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _noter(self, interaction: discord.Interaction, note: int):
        info = interaction.client.store.avis_attente.get(str(interaction.message.id))
        if info is None:
            await interaction.response.send_message(
                "❌ Cette demande d'avis n'est plus valide (peut-être déjà traitée).", ephemeral=True
            )
            return
        await interaction.response.send_modal(AvisTicketModal(note=note, dm_message_id=interaction.message.id))

    @discord.ui.button(label="1", emoji="⭐", style=discord.ButtonStyle.secondary, custom_id="avis_ticket_note_1")
    async def note_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._noter(interaction, 1)

    @discord.ui.button(label="2", emoji="⭐", style=discord.ButtonStyle.secondary, custom_id="avis_ticket_note_2")
    async def note_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._noter(interaction, 2)

    @discord.ui.button(label="3", emoji="⭐", style=discord.ButtonStyle.secondary, custom_id="avis_ticket_note_3")
    async def note_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._noter(interaction, 3)

    @discord.ui.button(label="4", emoji="⭐", style=discord.ButtonStyle.secondary, custom_id="avis_ticket_note_4")
    async def note_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._noter(interaction, 4)

    @discord.ui.button(label="5", emoji="⭐", style=discord.ButtonStyle.success, custom_id="avis_ticket_note_5")
    async def note_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._noter(interaction, 5)


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
            ticket_channel = await creer_salon_ticket(
                interaction.guild, membre, raison, staff_qui_accepte=interaction.user,
                store=interaction.client.store,
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas la permission de créer le salon.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = config.Couleurs.SUCCES
        embed.add_field(name="Statut", value=f"✅ Accepté par {interaction.user.mention}", inline=False)
        await interaction.edit_original_response(embed=embed, view=self)

        await utils.envoyer_log(
            interaction.guild, "🎫 Ticket Réclamé",
            f"{interaction.user.mention} a accepté la demande de {membre.mention} ({ticket_channel.mention})",
            config.Couleurs.SUCCES, interaction.user,
        )

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
        salon_demande_id = guild_settings.get_id(guild.id, "SALON_DEMANDE_TICKET_ID")
        salon_demande = guild.get_channel(salon_demande_id)
        if not salon_demande:
            await interaction.response.send_message(
                "❌ Le salon de demandes de tickets est introuvable, contacte un admin.", ephemeral=True
            )
            return

        embed = discord.Embed(title="🎫 Nouvelle demande de ticket", color=config.Couleurs.JAUNE)
        embed.add_field(name="Demandeur", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Raison", value=self.raison.value, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        role_staff_id = guild_settings.get_id(guild.id, "ROLE_STAFF_ID")
        role_admin_staff_id = guild_settings.get_id(guild.id, "ROLE_ADMIN_STAFF_ID")
        ping = f"<@&{role_staff_id}> <@&{role_admin_staff_id}>"

        await salon_demande.send(content=ping, embed=embed, view=TicketRequestView())
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

        store = interaction.client.store
        avis_en_attente = any(
            info["demandeur_id"] == interaction.user.id and info["guild_id"] == guild.id
            for info in store.avis_attente.values()
        )
        if avis_en_attente:
            await interaction.response.send_message(
                "❌ Tu dois d'abord laisser un avis sur ton dernier ticket fermé (regarde tes messages privés) "
                "avant de pouvoir en ouvrir un nouveau.",
                ephemeral=True,
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
