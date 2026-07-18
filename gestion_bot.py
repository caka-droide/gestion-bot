import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Configuration des ID à remplir ───────────────────────────────────────────
ROLE_STAFF_ID = 1521181880207147189  
ROLE_ADMIN_STAFF_ID = 1521181879141797952  

SALON_BIENVENUE_ID = 1521181917095923857
SALON_DEPART_ID = 1521181917095923857  # ⚠️ Même ID que SALON_BIENVENUE_ID : vérifie si c'est voulu ou si tu dois mettre l'ID d'un autre salon
SALON_LOGS_ID = 1521181898725134419
SALON_LOGS_TICKETS_ID = 1525912124923056288
CATEGORY_TICKETS_ID = 1521181911773348010

# ── Serveur Web pour Render ──────────────────────────────────────────────────
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Gestion en ligne !")
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# ── Config Bot ───────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN_GESTION")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=["!", "+"], intents=intents, help_command=None)

# ── Checks personnalisés ─────────────────────────────────────────────────────
def is_staff_or_higher():
    async def predicate(ctx):
        if ctx.author.id == ctx.guild.owner_id:
            return True
        roles_ids = [r.id for r in ctx.author.roles]
        return ROLE_STAFF_ID in roles_ids or ROLE_ADMIN_STAFF_ID in roles_ids
    return commands.check(predicate)

def is_admin_staff_or_higher():
    async def predicate(ctx):
        if ctx.author.id == ctx.guild.owner_id:
            return True
        roles_ids = [r.id for r in ctx.author.roles]
        return ROLE_ADMIN_STAFF_ID in roles_ids
    return commands.check(predicate)

def is_server_owner():
    def predicate(interaction: discord.Interaction):
        return interaction.user.id == interaction.guild.owner_id
    return app_commands.check(predicate)

# Équivalents des checks staff/admin pour les commandes slash (les checks
# ci-dessus utilisent `ctx`, incompatibles avec les commandes / qui reçoivent `interaction`)
def is_staff_or_higher_app():
    def predicate(interaction: discord.Interaction):
        if interaction.user.id == interaction.guild.owner_id:
            return True
        roles_ids = [r.id for r in interaction.user.roles]
        return ROLE_STAFF_ID in roles_ids or ROLE_ADMIN_STAFF_ID in roles_ids
    return app_commands.check(predicate)

def is_admin_staff_or_higher_app():
    def predicate(interaction: discord.Interaction):
        if interaction.user.id == interaction.guild.owner_id:
            return True
        roles_ids = [r.id for r in interaction.user.roles]
        return ROLE_ADMIN_STAFF_ID in roles_ids
    return app_commands.check(predicate)

def est_salon_ticket(channel):
    """Vérifie qu'un salon fait partie de la catégorie tickets."""
    return getattr(channel, "category_id", None) == CATEGORY_TICKETS_ID

async def envoyer_log(guild, titre, description, couleur=0x7289DA, auteur=None):
    salon_logs = guild.get_channel(SALON_LOGS_ID)
    if salon_logs:
        embed = discord.Embed(title=titre, description=description, color=couleur, timestamp=datetime.now())
        if auteur:
            embed.set_footer(text=f"Action par : {auteur.name}", icon_url=auteur.display_avatar.url)
        await salon_logs.send(embed=embed)

async def envoyer_transcript(guild, salon_ticket, ferme_par):
    salon_logs_tickets = guild.get_channel(SALON_LOGS_TICKETS_ID)
    if not salon_logs_tickets:
        return

    messages = [msg async for msg in salon_ticket.history(limit=None, oldest_first=True)]

    lignes = [f"=== Transcript du ticket {salon_ticket.name} ==="]
    lignes.append(f"Fermé par : {ferme_par} le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
    lignes.append("")

    for msg in messages:
        horodatage = msg.created_at.strftime("%d/%m/%Y %H:%M")
        contenu = msg.content if msg.content else "[Embed / Pièce jointe]"
        lignes.append(f"[{horodatage}] {msg.author} : {contenu}")

    texte_transcript = "\n".join(lignes)

    nom_fichier = f"transcript-{salon_ticket.name}.txt"
    with open(nom_fichier, "w", encoding="utf-8") as f:
        f.write(texte_transcript)

    embed = discord.Embed(
        title="📄 Transcript du Ticket",
        description=f"Ticket : `{salon_ticket.name}`\nFermé par : {ferme_par}\nNombre de messages : {len(messages)}",
        color=0x2b2d31,
        timestamp=datetime.now()
    )

    try:
        await salon_logs_tickets.send(embed=embed, file=discord.File(nom_fichier))
    finally:
        if os.path.exists(nom_fichier):
            os.remove(nom_fichier)

# ── Stockage persistant (Upstash Redis) ─────────────────────────────────────────
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

if not UPSTASH_URL or not UPSTASH_TOKEN:
    raise SystemExit(
        "❌ Il manque UPSTASH_REDIS_REST_URL ou UPSTASH_REDIS_REST_TOKEN dans les variables d'environnement"
    )

HEADERS_UPSTASH = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}

async def upstash_command(*args):
    async with aiohttp.ClientSession() as session:
        async with session.post(UPSTASH_URL, headers=HEADERS_UPSTASH, json=list(args), timeout=10) as resp:
            payload = await resp.json()
    return payload.get("result")

async def load(key):
    try:
        valeur = await upstash_command("GET", key)
        return json.loads(valeur) if valeur else {}
    except Exception as e:
        print(f"❌ Erreur chargement '{key}' depuis Upstash : {e}")
        return {}

async def save(key, data):
    try:
        await upstash_command("SET", key, json.dumps(data))
    except Exception as e:
        print(f"❌ Erreur sauvegarde '{key}' vers Upstash : {e}")

levels_data = {}
warns_data = {}
mutes_data = {}
invites_data = {}
giveaways_data = {}
salon_pauses_data = {}
reglement_data = {}
role_menus_data = {}
avis_data = {}

async def setup_hook():
    global levels_data, warns_data, mutes_data, invites_data, giveaways_data, salon_pauses_data
    global reglement_data, role_menus_data, avis_data
    levels_data = await load("levels")
    warns_data = await load("warns")
    mutes_data = await load("mutes")
    invites_data = await load("invites")
    giveaways_data = await load("giveaways")
    salon_pauses_data = await load("salon_pauses")
    reglement_data = await load("reglement")
    role_menus_data = await load("role_menus")
    avis_data = await load("avis")
    print("✅ Données chargées depuis Upstash Redis")

bot.setup_hook = setup_hook

# ── XP / Niveaux ─────────────────────────────────────────────────────────────
XP_PAR_MESSAGE = 15
COOLDOWN_XP = {}

def xp_pour_niveau(niveau):
    return 100 * (niveau ** 2)

def get_niveau(xp):
    niveau = 0
    while xp >= xp_pour_niveau(niveau + 1):
        niveau += 1
    return niveau

ROLES_NIVEAUX = {
    5:  "Niveau 5",
    10: "Niveau 10",
    20: "Niveau 20",
    50: "Niveau 50",
}

PAUSE_DERNIER_MESSAGE = {}

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    cid = str(message.channel.id)
    delai_pause = salon_pauses_data.get(cid)
    if delai_pause:
        maintenant_pause = datetime.now().timestamp()
        dernier_message = PAUSE_DERNIER_MESSAGE.get(cid)
        if dernier_message is not None and maintenant_pause - dernier_message < delai_pause:
            restant = delai_pause - (maintenant_pause - dernier_message)
            try:
                await message.delete()
            except:
                pass
            try:
                await message.channel.send(
                    f"⏳ {message.author.mention} Ce salon est en pause, réessaie dans `{restant:.1f}s`.",
                    delete_after=5
                )
            except:
                pass
            return
        PAUSE_DERNIER_MESSAGE[cid] = maintenant_pause

    uid = str(message.author.id)
    gid = str(message.guild.id)
    now = datetime.now().timestamp()

    key = f"{gid}_{uid}"
    if key in COOLDOWN_XP and now - COOLDOWN_XP[key] < 60:
        await bot.process_commands(message)
        return

    COOLDOWN_XP[key] = now

    if gid not in levels_data:
        levels_data[gid] = {}
    if uid not in levels_data[gid]:
        levels_data[gid][uid] = {"xp": 0, "niveau": 0, "messages": 0}

    ancien_niveau = levels_data[gid][uid]["niveau"]
    levels_data[gid][uid]["xp"] += XP_PAR_MESSAGE
    levels_data[gid][uid]["messages"] += 1
    nouveau_niveau = get_niveau(levels_data[gid][uid]["xp"])
    levels_data[gid][uid]["niveau"] = nouveau_niveau
    await save("levels", levels_data)

    if nouveau_niveau > ancien_niveau:
        embed = discord.Embed(
            title="⭐ Level Up !",
            description=f"Bravo {message.author.mention} ! Tu es maintenant **niveau {nouveau_niveau}** !",
            color=0xFFD700
        )
        await message.channel.send(embed=embed)

        if nouveau_niveau in ROLES_NIVEAUX:
            role = discord.utils.get(message.guild.roles, name=ROLES_NIVEAUX[nouveau_niveau])
            if role:
                await message.author.add_roles(role)

    await bot.process_commands(message)

# ── Bouton de Fermeture des Tickets ──────────────────────────────────────────
class ConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirmer(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🔒 **Le ticket va se fermer et être supprimé dans 5 secondes...**", view=self)
        try:
            await envoyer_transcript(interaction.guild, interaction.channel, interaction.user)
        except Exception as e:
            print(f"Erreur génération transcript : {e}")

        await envoyer_log(interaction.guild, "🔒 Ticket Fermé", f"Le salon `{interaction.channel.name}` a été supprimé.", 0xFF0000, interaction.user)
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

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="fermer_ticket_btn", emoji="🔒")
    async def bouton_fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "⚠️ **Es-tu sûr de vouloir fermer ce ticket ?** Le salon sera supprimé définitivement.",
            view=ConfirmCloseView()
        )

# ── Système de Tickets (Ouverture) ───────────────────────────────────────────
class TicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket", style=discord.ButtonStyle.primary, custom_id="creer_ticket_btn", emoji="🎫")
    async def bouton_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        category = guild.get_channel(CATEGORY_TICKETS_ID)

        nom_salon = f"ticket-{interaction.user.name.lower()}"
        salon_existant = discord.utils.get(guild.text_channels, name=nom_salon)
        
        if salon_existant:
            await interaction.followup.send(f"❌ Tu as déjà un ticket ouvert : {salon_existant.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        try:
            ticket_channel = await guild.create_text_channel(name=nom_salon, category=category, overwrites=overwrites)
            await interaction.followup.send(f"✅ Ton ticket a été créé : {ticket_channel.mention}", ephemeral=True)
            
            embed = discord.Embed(
                title="🎫 Nouveau Ticket",
                description=f"Bonjour {interaction.user.mention},\nExplique ton problème ici. L'équipe du staff te répondra dès que possible.\n\n*Pour fermer ce ticket, clique sur le bouton rouge ci-dessous.*",
                color=0x2b2d31
            )
            
            message_ping = f"<@&{ROLE_STAFF_ID}> <@&{ROLE_ADMIN_STAFF_ID}>"
            await ticket_channel.send(content=message_ping, embed=embed, view=CloseButton())
            
            await envoyer_log(guild, "🎫 Ticket Ouvert", f"Ticket créé par {interaction.user.mention} ({ticket_channel.mention})", 0x00FF00, interaction.user)

        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas la permission de **Gérer les salons** ou de **Gérer les rôles**.", ephemeral=True)

# ── Règlement / Roles ────────────────────────────────────────────────────────
class ReglementView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="J'ai lu et j'accepte le règlement", style=discord.ButtonStyle.success, custom_id="reglement_accept_btn", emoji="✅")
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
        except:
            await interaction.response.send_message("❌ Je n'ai pas la permission de t'attribuer ce rôle.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Merci d'avoir lu le règlement ! Le rôle **{role.name}** t'a été attribué.", ephemeral=True)

class RoleMenuView(discord.ui.View):
    def __init__(self, roles: list):
        super().__init__(timeout=None)
        self.roles_map = {str(r.id): r for r in roles}
        self.select = discord.ui.Select(
            placeholder="Choisis un ou plusieurs rôles...",
            min_values=0, max_values=len(roles), custom_id="role_menu_select",
            options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in roles]
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
            if ajoutes: await membre.add_roles(*ajoutes)
            if retires: await membre.remove_roles(*retires)
        except:
            await interaction.response.send_message("❌ Je n'ai pas la permission de gérer ces rôles.", ephemeral=True)
            return
        
        await interaction.response.send_message("✅ Tes rôles ont été mis à jour !", ephemeral=True)

# ── Initialisation ────────────────────────────────────────────────────────────
premiere_connexion = True

@bot.event
async def on_ready():
    global premiere_connexion
    print(f"✅ Bot connecté : {bot.user}")

    if not premiere_connexion:
        return
    premiere_connexion = False

    bot.add_view(TicketButton())
    bot.add_view(CloseButton())

    for message_id, data in reglement_data.items():
        guild = bot.get_guild(data["guild_id"])
        if guild and (role := guild.get_role(data["role_id"])):
            bot.add_view(ReglementView(role.id), message_id=int(message_id))

    for message_id, data in role_menus_data.items():
        guild = bot.get_guild(data["guild_id"])
        if guild:
            roles = [r for rid in data.get("role_ids", []) if (r := guild.get_role(rid))]
            if roles: bot.add_view(RoleMenuView(roles), message_id=int(message_id))

    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées")
    except Exception as e:
        print(f"❌ Erreur sync : {e}")

    for guild in bot.guilds:
        gid = str(guild.id)
        try:
            invites = await guild.invites()
            if gid not in invites_data:
                invites_data[gid] = {}
            for inv in invites:
                existing = invites_data[gid].get(inv.code, {})
                invites_data[gid][inv.code] = {
                    "inviter_id": str(inv.inviter.id) if inv.inviter else None,
                    "uses": inv.uses,
                    "joined": existing.get("joined", []),
                    "left": existing.get("left", [])
                }
            await save("invites", invites_data)
        except:
            pass

    if not check_giveaways.is_running(): check_giveaways.start()

# ── Bienvenue & Invites ──────────────────────────────────────────────────────
@bot.event
async def on_invite_create(invite):
    gid = str(invite.guild.id)
    if gid not in invites_data: invites_data[gid] = {}
    invites_data[gid][invite.code] = {"inviter_id": str(invite.inviter.id) if invite.inviter else None, "uses": 0, "joined": [], "left": []}
    await save("invites", invites_data)

@bot.event
async def on_member_join(member):
    gid = str(member.guild.id)
    try:
        await member.send(f"Salut {member.mention} ! Bienvenue sur **{member.guild.name}** ! 🎉")
    except:
        pass

    salon_bienvenue = member.guild.get_channel(SALON_BIENVENUE_ID)
    if salon_bienvenue:
        embed = discord.Embed(title="👋 Un nouveau membre vient d'arriver !", description=f"Bienvenue {member.mention} sur **{member.guild.name}** !\nNous sommes maintenant {member.guild.member_count} membres.", color=0x00FF00)
        embed.set_thumbnail(url=member.display_avatar.url)
        await salon_bienvenue.send(embed=embed)

    try:
        new_invites = await member.guild.invites()
        old_invites = invites_data.get(gid, {})
        for inv in new_invites:
            old_uses = old_invites.get(inv.code, {}).get("uses", 0)
            if inv.uses is not None and inv.uses > old_uses:
                if gid not in invites_data: invites_data[gid] = {}
                if inv.code not in invites_data[gid]:
                    invites_data[gid][inv.code] = {"inviter_id": str(inv.inviter.id) if inv.inviter else None, "uses": 0, "joined": [], "left": []}
                invites_data[gid][inv.code]["uses"] = inv.uses
                invites_data[gid][inv.code]["joined"].append(str(member.id))
                await save("invites", invites_data)
                break
    except:
        pass

@bot.event
async def on_member_remove(member):
    gid = str(member.guild.id)
    uid = str(member.id)
    salon_depart = member.guild.get_channel(SALON_DEPART_ID)
    if salon_depart:
        embed = discord.Embed(title="😢 Départ d'un membre", description=f"**{member.display_name}** a quitté le serveur. À bientôt...", color=0xFF0000)
        await salon_depart.send(embed=embed)

    if gid in invites_data:
        for code, data in invites_data[gid].items():
            if uid in data.get("joined", []):
                data["left"].append(uid)
                await save("invites", invites_data)
                break

# ── Giveaways ────────────────────────────────────────────────────────────────
GIVEAWAY_EMOJI = "🎉"

def parse_duree(duree_str):
    duree_str = duree_str.strip().lower()
    if len(duree_str) < 2: return None
    unite = duree_str[-1]
    nombre = duree_str[:-1]
    unites = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if unite not in unites or not nombre.isdigit(): return None
    return int(nombre) * unites[unite]

async def terminer_giveaway(message_id, force_gagnants=None):
    data = giveaways_data.get(str(message_id))
    if not data: return None
    guild = bot.get_guild(data["guild_id"])
    if not guild: return None
    channel = guild.get_channel(data["channel_id"])
    if not channel: return None
    try: message = await channel.fetch_message(int(message_id))
    except:
        data["ended"] = True
        await save("giveaways", giveaways_data)
        return None

    reaction = discord.utils.get(message.reactions, emoji=GIVEAWAY_EMOJI)
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
    embed.color = 0x95A5A6
    try: await message.edit(embed=embed)
    except: pass
    try: await channel.send(texte_resultat)
    except: pass

    data["ended"] = True
    await save("giveaways", giveaways_data)
    return gagnants

@tasks.loop(seconds=30)
async def check_giveaways():
    now = datetime.now().timestamp()
    a_terminer = [mid for mid, d in giveaways_data.items() if not d.get("ended") and now >= d.get("end_time", 0)]
    for mid in a_terminer:
        await terminer_giveaway(mid)

# ── COMMANDES PROPRIÉTAIRE (IDENTITÉ DU BOT) ─────────────────────────────────
@bot.command()
@commands.is_owner()
async def setbotname(ctx, *, nouveau_nom: str):
    try:
        await bot.user.edit(username=nouveau_nom)
        await ctx.send(f"✅ Nom du bot changé en : **{nouveau_nom}**")
    except discord.HTTPException as e:
        await ctx.send(f"❌ Erreur lors du changement de nom : {e}")

@bot.command()
@commands.is_owner()
async def setpdp(ctx):
    if not ctx.message.attachments:
        await ctx.send("❌ Tu dois attacher une image à ton message pour changer la photo de profil.")
        return
    try:
        image_bytes = await ctx.message.attachments[0].read()
        await bot.user.edit(avatar=image_bytes)
        await ctx.send("✅ Photo de profil mise à jour !")
    except discord.HTTPException as e:
        await ctx.send(f"❌ Erreur lors du changement d'avatar : {e}")

# ── MENU HELP (Custom) ───────────────────────────────────────────────────────
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="📚 Menu d'Aide du Bot",
        description="Voici la liste des commandes disponibles, classées par permissions.",
        color=0x2b2d31
    )
    
    # Membres
    embed.add_field(name="👥 Membres", value=(
        "`+i` / `/invitations` : Voir tes invitations.\n"
        "`/niveau` : Consulter ton niveau d'XP.\n"
        "`/classement` : Voir le classement XP du serveur.\n"
        "`/avis` : Laisser un avis sur le serveur.\n"
        "`/avis_stats` : Voir les stats des avis.\n"
        "`/stats` : Voir les statistiques du serveur."
    ), inline=False)
    
    # Staff
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
    
    # Admin Staff
    embed.add_field(name="🔨 Admin Staff", value=(
        "`+kick <@membre> <raison>` : Expulser du serveur.\n"
        "`+ban <@membre> <raison>` : Bannir du serveur.\n"
        "`/unban <id>` : Débannir un membre.\n"
        "`/slowmode` : Régler le mode lent d'un salon.\n"
        "`/pause` : Mettre un salon en cooldown global.\n"
        "`/gw` / `/gw_reroll` / `/gw_end` : Gérer les giveaways."
    ), inline=False)
    
    # Propriétaire
    embed.add_field(name="👑 Propriétaire", value=(
        "`/setup_ticket` / `/setup_reglement` / `/setup_roles` : Configurer le serveur."
    ), inline=False)
    
    embed.set_footer(text=f"Demandé par {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

# ── COMMANDES PREFIX MODERATION (+ban, +mute, etc.) ──────────────────────────

@bot.command()
@is_staff_or_higher()
async def warn(ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
    gid = str(ctx.guild.id)
    uid = str(membre.id)
    if gid not in warns_data: warns_data[gid] = {}
    if uid not in warns_data[gid]: warns_data[gid][uid] = []
    warns_data[gid][uid].append({"raison": raison, "date": str(datetime.now()), "by": str(ctx.author.id)})
    await save("warns", warns_data)
    nb = len(warns_data[gid][uid])
    
    embed = discord.Embed(title="⚠️ Avertissement", color=0xFFA500)
    embed.add_field(name="Membre", value=membre.mention, inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    embed.add_field(name="Total warns", value=str(nb), inline=True)
    await ctx.send(embed=embed)
    
    await envoyer_log(ctx.guild, "⚠️ Membre Warn", f"Membre : {membre.mention}\nRaison : {raison}\nTotal : {nb} warn(s)", 0xFFA500, ctx.author)
    try: await membre.send(f"⚠️ Tu as reçu un avertissement sur **{ctx.guild.name}**\nRaison : {raison}\nTotal : {nb} warn(s)")
    except: pass

@bot.command()
@is_staff_or_higher()
async def unwarn(ctx, membre: discord.Member):
    gid = str(ctx.guild.id)
    uid = str(membre.id)
    if gid in warns_data and uid in warns_data[gid]:
        warns_data[gid][uid] = []
        await save("warns", warns_data)
    await ctx.send(f"✅ Warns de {membre.mention} supprimés.")
    await envoyer_log(ctx.guild, "✨ Warns Effacés", f"Les avertissements de {membre.mention} ont été remis à zéro.", 0x2ECC71, ctx.author)

@bot.command()
@is_staff_or_higher()
async def mute(ctx, membre: discord.Member, duree_str: str, *, raison: str = "Aucune raison"):
    secondes = parse_duree(duree_str)
    if not secondes:
        await ctx.send("❌ **Format de durée invalide.** Exemple : `3m` (3 minutes), `1h` (1 heure), `1d` (1 jour).")
        return

    # Discord limite le timeout natif à 28 jours maximum
    if secondes > 2419200:
        await ctx.send("❌ La durée maximale de mute (exclusion native) est de 28 jours (`28d`).")
        return

    duree_td = timedelta(seconds=secondes)
    try:
        await membre.timeout(duree_td, reason=raison)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission d'exclure temporairement ce membre (vérifie mes rôles et la hiérarchie).")
        return
    except Exception as e:
        await ctx.send(f"❌ Une erreur est survenue lors du timeout : {e}")
        return

    embed = discord.Embed(title="🔇 Membre rendu muet (Timeout)", color=0xFF0000)
    embed.add_field(name="Membre", value=membre.mention, inline=True)
    embed.add_field(name="Durée", value=duree_str, inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await ctx.send(embed=embed)
    await envoyer_log(ctx.guild, "🔇 Membre Mute", f"Membre : {membre.mention}\nDurée : {duree_str}\nRaison : {raison}", 0xE74C3C, ctx.author)

@bot.command()
@is_staff_or_higher()
async def unmute(ctx, membre: discord.Member):
    try:
        await membre.timeout(None, reason=f"Unmute par {ctx.author.name}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de retirer l'exclusion de ce membre.")
        return
    except Exception as e:
        await ctx.send(f"❌ Une erreur est survenue : {e}")
        return

    await ctx.send(f"✅ {membre.mention} n'est plus muet.")
    await envoyer_log(ctx.guild, "🔊 Membre Unmute", f"L'exclusion de {membre.mention} a été retirée.", 0x2ECC71, ctx.author)

@bot.command()
@is_staff_or_higher()
async def lock(ctx, *, raison: str = "Aucune raison"):
    cible = ctx.channel
    overwrite = cible.overwrites_for(ctx.guild.default_role)
    if overwrite.send_messages is False:
        await ctx.send(f"❌ {cible.mention} est déjà verrouillé.")
        return

    overwrite.send_messages = False
    await cible.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=raison)

    embed = discord.Embed(title="🔒 Salon Verrouillé", color=0xFF0000)
    embed.add_field(name="Salon", value=cible.mention, inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await ctx.send(embed=embed)
    await envoyer_log(ctx.guild, "🔒 Salon Verrouillé", f"Salon : {cible.mention}\nRaison : {raison}", 0xFF0000, ctx.author)

@bot.command()
@is_staff_or_higher()
async def unlock(ctx):
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

    embed = discord.Embed(title="🔓 Salon Déverrouillé", color=0x2ECC71)
    embed.add_field(name="Salon", value=cible.mention, inline=True)
    await ctx.send(embed=embed)
    await envoyer_log(ctx.guild, "🔓 Salon Déverrouillé", f"Salon : {cible.mention}", 0x2ECC71, ctx.author)

@bot.command()
@is_admin_staff_or_higher()
async def kick(ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
    await membre.kick(reason=raison)
    embed = discord.Embed(title="👢 Membre Expulsé", color=0xFF6600)
    embed.add_field(name="Membre", value=str(membre), inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await ctx.send(embed=embed)
    await envoyer_log(ctx.guild, "👢 Membre Kické", f"Pseudo : **{membre}**\nRaison : {raison}", 0xE67E22, ctx.author)

@bot.command()
@is_admin_staff_or_higher()
async def ban(ctx, membre: discord.Member, *, raison: str = "Aucune raison"):
    await membre.ban(reason=raison)
    embed = discord.Embed(title="🔨 Membre banni", color=0xFF0000)
    embed.add_field(name="Membre", value=str(membre), inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await ctx.send(embed=embed)
    await envoyer_log(ctx.guild, "🔨 Membre Banni", f"Pseudo : **{membre}**\nRaison : {raison}", 0x95A5A6, ctx.author)

@bot.command(name="i")
async def i_cmd(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    gid = str(ctx.guild.id)
    uid = str(cible.id)

    total_joins = 0
    total_left = 0
    codes_utilises = []

    for code, data in invites_data.get(gid, {}).items():
        if data.get("inviter_id") == uid:
            joins = len(data.get("joined", []))
            left = len(data.get("left", []))
            total_joins += joins
            total_left += left
            if joins > 0:
                codes_utilises.append(f"`{code}` : {joins} invités ({left} partis)")

    restes = total_joins - total_left
    embed = discord.Embed(title=f"📨 Invitations de {cible.display_name}", color=0x7289DA)
    embed.add_field(name="Total invités", value=str(total_joins), inline=True)
    embed.add_field(name="Restés", value=str(restes), inline=True)
    embed.add_field(name="Partis", value=str(total_left), inline=True)
    if codes_utilises:
        embed.add_field(name="Détail par lien", value="\n".join(codes_utilises[:5]), inline=False)
    embed.set_thumbnail(url=cible.display_avatar.url)
    await ctx.send(embed=embed)

# ── COMMANDES PREFIX TICKETS ──────────────────────────────────────────────────

@bot.command(name="rename")
@is_staff_or_higher()
async def rename_cmd(ctx, *, nouveau_nom: str):
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
    await envoyer_log(ctx.guild, "✏️ Ticket Renommé", f"`{ancien_nom}` → `{nouveau_nom_propre}` par {ctx.author.mention}", 0x7289DA, ctx.author)

@bot.command(name="staff")
@is_staff_or_higher()
async def staff_cmd(ctx, membre: discord.Member):
    if not est_salon_ticket(ctx.channel):
        await ctx.send("❌ Cette commande ne peut être utilisée que dans un salon de ticket.")
        return

    try:
        await ctx.channel.set_permissions(membre, read_messages=True, send_messages=True, reason=f"Ajouté au ticket par {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de modifier les accès de ce salon.")
        return

    await ctx.send(f"✅ {membre.mention} a été ajouté à ce ticket.")
    await envoyer_log(ctx.guild, "➕ Staff Ajouté au Ticket", f"{membre.mention} ajouté au ticket {ctx.channel.mention} par {ctx.author.mention}", 0x2ECC71, ctx.author)

@bot.command(name="unstaff")
@is_staff_or_higher()
async def unstaff_cmd(ctx, membre: discord.Member):
    if not est_salon_ticket(ctx.channel):
        await ctx.send("❌ Cette commande ne peut être utilisée que dans un salon de ticket.")
        return

    try:
        await ctx.channel.set_permissions(membre, overwrite=None, reason=f"Retiré du ticket par {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de modifier les accès de ce salon.")
        return

    await ctx.send(f"✅ {membre.mention} a été retiré de ce ticket.")
    await envoyer_log(ctx.guild, "➖ Staff Retiré du Ticket", f"{membre.mention} retiré du ticket {ctx.channel.mention} par {ctx.author.mention}", 0xE67E22, ctx.author)


# ── COMMANDES SLASH RESTANTES (Admin / Utils) ────────────────────────────────

@bot.tree.command(name="log", description="Redirige vers le salon des logs")
@app_commands.checks.has_permissions(manage_messages=True)
async def log_cmd(interaction: discord.Interaction):
    salon_logs = interaction.guild.get_channel(SALON_LOGS_ID)
    embed = discord.Embed(
        title="📋 Suivi des Logs",
        description=f"Toutes les actions sont enregistrées dans {salon_logs.mention if salon_logs else 'le salon introuvable'}.",
        color=0x7289DA
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup_ticket", description="Configure le panel pour créer des tickets")
@is_server_owner()
async def setup_ticket_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📞 Support et Tickets", description="Clique sur le bouton ci-dessous pour ouvrir un ticket.", color=0x2b2d31)
    await interaction.channel.send(embed=embed, view=TicketButton())
    await interaction.response.send_message("✅ Panel créé.", ephemeral=True)

@bot.tree.command(name="setup_reglement", description="Poste le règlement")
@is_server_owner()
async def setup_reglement_cmd(interaction: discord.Interaction, role: discord.Role, texte: str, salon: discord.TextChannel = None):
    cible = salon or interaction.channel
    embed = discord.Embed(title="📜 Règlement du serveur", description=texte.replace("\\n", "\n"), color=0x2b2d31)
    view = ReglementView(role.id)
    message = await cible.send(embed=embed, view=view)
    reglement_data[str(message.id)] = {"guild_id": interaction.guild.id, "channel_id": cible.id, "role_id": role.id}
    await save("reglement", reglement_data)
    bot.add_view(view, message_id=message.id)
    await interaction.response.send_message("✅ Règlement posté.", ephemeral=True)

@bot.tree.command(name="setup_roles", description="Poste un menu de rôles")
@is_server_owner()
async def setup_roles_cmd(interaction: discord.Interaction, role1: discord.Role, role2: discord.Role = None, salon: discord.TextChannel = None):
    cible = salon or interaction.channel
    roles = [r for r in [role1, role2] if r is not None]
    embed = discord.Embed(title="🎭 Choisis tes rôles", description="Sélectionne tes rôles.", color=0x7289DA)
    view = RoleMenuView(roles)
    message = await cible.send(embed=embed, view=view)
    role_menus_data[str(message.id)] = {"guild_id": interaction.guild.id, "channel_id": cible.id, "role_ids": [r.id for r in roles]}
    await save("role_menus", role_menus_data)
    bot.add_view(view, message_id=message.id)
    await interaction.response.send_message("✅ Menu créé.", ephemeral=True)

@bot.tree.command(name="avis", description="Laisser un avis")
@app_commands.choices(note=[app_commands.Choice(name=f"{i} étoiles", value=i) for i in range(1, 6)])
async def avis_cmd(interaction: discord.Interaction, theme: str, note: app_commands.Choice[int], texte: str, image: discord.Attachment = None):
    etoiles = "⭐" * note.value + "☆" * (5 - note.value)
    embed = discord.Embed(title="📝 Nouvel avis", color=0xF1C40F)
    embed.add_field(name="Thème", value=theme, inline=True)
    embed.add_field(name="Note", value=f"{etoiles} ({note.value}/5)", inline=True)
    embed.add_field(name="Avis", value=texte, inline=False)
    if image: embed.set_image(url=image.url)
    await interaction.response.send_message(embed=embed)
    gid = str(interaction.guild.id)
    avis_data.setdefault(gid, []).append({
        "theme": theme, "note": note.value, "texte": texte, 
        "image_url": image.url if image else None, "auteur_id": interaction.user.id
    })
    await save("avis", avis_data)

@bot.tree.command(name="avis_stats", description="Voir la moyenne des avis")
async def avis_stats_cmd(interaction: discord.Interaction, theme: str = None):
    gid = str(interaction.guild.id)
    tous_avis = avis_data.get(gid, [])
    avis_liste = [a for a in tous_avis if a["theme"].lower() == theme.lower()] if theme else tous_avis
    if not avis_liste:
        return await interaction.response.send_message("❌ Aucun avis trouvé.", ephemeral=True)
    moyenne = sum(a["note"] for a in avis_liste) / len(avis_liste)
    arrondi = round(moyenne)
    embed = discord.Embed(title="📊 Avis", color=0xF1C40F)
    embed.add_field(name="Moyenne", value=f"{'⭐'*arrondi}{'☆'*(5-arrondi)} ({moyenne:.1f}/5)")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="Supprimer massivement des messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_cmd(interaction: discord.Interaction, montant: int = 100, membre: discord.Member = None):
    await interaction.response.defer(ephemeral=True)
    if membre:
        deleted = await interaction.channel.purge(limit=montant, check=lambda m: m.author.id == membre.id)
    else:
        deleted = await interaction.channel.purge(limit=montant)
    await interaction.followup.send(f"✅ `{len(deleted)}` messages supprimés.")

@bot.tree.command(name="niveau", description="Voir ton niveau d'XP")
async def niveau_cmd(interaction: discord.Interaction, membre: discord.Member = None):
    cible = membre or interaction.user
    gid = str(interaction.guild.id)
    data = levels_data.get(gid, {}).get(str(cible.id), {"xp": 0, "niveau": 0})
    embed = discord.Embed(title=f"⭐ Niveau de {cible.display_name}", color=0xFFD700)
    embed.add_field(name="Niveau", value=str(data["niveau"]), inline=True)
    embed.add_field(name="XP", value=str(data["xp"]), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="classement", description="Top 10 du classement XP")
async def classement_cmd(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    top = sorted(levels_data.get(gid, {}).items(), key=lambda x: x[1].get("xp", 0), reverse=True)[:10]
    embed = discord.Embed(title="🏆 Classement", description="\n".join([f"<@{u}> : Lvl {d['niveau']} ({d['xp']} XP)" for u, d in top]) or "Aucun membre.", color=0xFFD700)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="invitations", description="Voir tes invitations")
async def invitations_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("👉 Utilise la commande `+i` dans le chat pour voir tes invitations !", ephemeral=True)

@bot.tree.command(name="unban", description="Débannir un membre")
@is_admin_staff_or_higher()
async def unban_cmd(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ {user} débanni.", ephemeral=True)
        
        # Envoi dans les logs
        await envoyer_log(interaction.guild, "🔓 Membre Débanni", f"L'utilisateur **{user}** ({user_id}) a été débanni.", 0x2ECC71, interaction.user)
    except Exception as e:
        await interaction.response.send_message("❌ ID introuvable ou impossible de débannir ce membre.", ephemeral=True)
        

@bot.tree.command(name="slowmode", description="Définir le mode lent d'un salon")
@is_admin_staff_or_higher_app()
async def slowmode_cmd(interaction: discord.Interaction, secondes: int):
    await interaction.channel.edit(slowmode_delay=secondes)
    await interaction.response.send_message(f"✅ Mode lent : `{secondes}s`.")

@bot.tree.command(name="pause", description="Cooldown global sur un salon")
@is_admin_staff_or_higher_app()
async def pause_cmd(interaction: discord.Interaction, secondes: int):
    cid = str(interaction.channel.id)
    if secondes == 0:
        salon_pauses_data.pop(cid, None)
        PAUSE_DERNIER_MESSAGE.pop(cid, None)
    else:
        salon_pauses_data[cid] = secondes
        PAUSE_DERNIER_MESSAGE.pop(cid, None)
    await save("salon_pauses", salon_pauses_data)
    await interaction.response.send_message(f"✅ Pause réglée à `{secondes}s`.")

@bot.tree.command(name="stats", description="Statistiques du serveur")
async def stats_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"📊 Stats de {guild.name}", color=0x7289DA)
    embed.add_field(name="👥 Membres", value=str(guild.member_count))
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="gw", description="Lancer un giveaway")
@is_admin_staff_or_higher_app()
async def gw_cmd(interaction: discord.Interaction, duree: str, prix: str, gagnants: int = 1):
    secondes = parse_duree(duree)
    if not secondes: return await interaction.response.send_message("❌ Durée invalide.", ephemeral=True)
    fin = datetime.now(timezone.utc) + timedelta(seconds=secondes)
    embed = discord.Embed(title="🎉 GIVEAWAY 🎉", description=f"**Lot : {prix}**\nFin : <t:{int(fin.timestamp())}:R>", color=0xF1C40F)
    await interaction.response.send_message("✅ Giveaway lancé !", ephemeral=True)
    message = await interaction.channel.send(embed=embed)
    await message.add_reaction(GIVEAWAY_EMOJI)
    giveaways_data[str(message.id)] = {"guild_id": interaction.guild.id, "channel_id": interaction.channel.id, "host_id": interaction.user.id, "prix": prix, "gagnants": gagnants, "end_time": fin.timestamp(), "ended": False}
    await save("giveaways", giveaways_data)

@bot.tree.command(name="gw_reroll", description="Retirer de nouveaux gagnants")
@is_admin_staff_or_higher_app()
async def gw_reroll_cmd(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(ephemeral=True)
    if await terminer_giveaway(message_id): await interaction.followup.send("✅ Gagnants retirés.", ephemeral=True)
    else: await interaction.followup.send("❌ Erreur de reroll.", ephemeral=True)

@bot.tree.command(name="gw_end", description="Terminer un giveaway")
@is_admin_staff_or_higher_app()
async def gw_end_cmd(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(ephemeral=True)
    await terminer_giveaway(message_id)
    await interaction.followup.send("✅ Terminé.", ephemeral=True)

# ── Gestionnaire d'erreurs ──────────────────────────────────────────────────
@bot.event
async def on_command_error(ctx, error):
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

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.CheckFailure):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ **Accès refusé :** Commande réservée.", ephemeral=True)

# ── Lancement ────────────────────────────────────────────────────────────────
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Erreur : DISCORD_TOKEN_GESTION introuvable.")
    
