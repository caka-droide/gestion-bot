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

# ── Config ───────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN_GESTION")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Configuration des salons importants
SALON_BIENVENUE_ID = 1521181917095923857
SALON_DEPART_ID = 1521181917095923857
SALON_LOGS_ID = 1521181898725134419
SALON_LOGS_TICKETS_ID = 1525912124923056288
CATEGORY_TICKETS_ID = 1521181911773348010

# Fonction utilitaire pour envoyer un log automatique dans le salon dédié
async def envoyer_log(guild, titre, description, couleur=0x7289DA, auteur=None):
    salon_logs = guild.get_channel(SALON_LOGS_ID)
    if salon_logs:
        embed = discord.Embed(title=titre, description=description, color=couleur, timestamp=datetime.now())
        if auteur:
            embed.set_footer(text=f"Action par : {auteur.name}", icon_url=auteur.display_avatar.url)
        await salon_logs.send(embed=embed)

# Fonction utilitaire pour générer et envoyer le transcript d'un ticket
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
# Render (tier gratuit) a un système de fichiers ÉPHÉMÈRE : à chaque redéploiement
# (donc à chaque push GitHub), tout fichier local créé à l'exécution (levels.json,
# warns.json, etc.) est perdu. On stocke donc les données dans une base Redis
# externe (Upstash, gratuite à vie, sans carte bancaire) qui survit aux redéploiements.
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

if not UPSTASH_URL or not UPSTASH_TOKEN:
    raise SystemExit(
        "❌ Il manque UPSTASH_REDIS_REST_URL ou UPSTASH_REDIS_REST_TOKEN dans les variables d'environnement"
    )

HEADERS_UPSTASH = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}

async def upstash_command(*args):
    """Envoie une commande Redis brute (ex: 'GET', 'levels') à l'API REST d'Upstash."""
    async with aiohttp.ClientSession() as session:
        async with session.post(UPSTASH_URL, headers=HEADERS_UPSTASH, json=list(args), timeout=10) as resp:
            payload = await resp.json()
    return payload.get("result")

async def load(key):
    """Charge un dict JSON depuis Redis. Retourne {} si la clé n'existe pas encore."""
    try:
        valeur = await upstash_command("GET", key)
        return json.loads(valeur) if valeur else {}
    except Exception as e:
        print(f"❌ Erreur chargement '{key}' depuis Upstash : {e}")
        return {}

async def save(key, data):
    """Sauvegarde un dict JSON dans Redis."""
    try:
        await upstash_command("SET", key, json.dumps(data))
    except Exception as e:
        print(f"❌ Erreur sauvegarde '{key}' vers Upstash : {e}")

# Les dicts sont initialisés vides ici, puis remplis dans setup_hook() au démarrage
# du bot (impossible de faire un appel réseau "await" à ce stade du script).
levels_data = {}
warns_data = {}
mutes_data = {}
invites_data = {}
giveaways_data = {}
salon_pauses_data = {}  # { "channel_id": délai_en_secondes }
reglement_data = {}  # { "message_id": {"guild_id":, "channel_id":, "role_id":} }
role_menus_data = {}  # { "message_id": {"guild_id":, "channel_id":, "role_ids": [...]} }

async def setup_hook():
    """Appelé automatiquement par discord.py juste avant la connexion au bot.
    C'est le bon endroit pour charger les données depuis Upstash, avant que
    la moindre commande ou le moindre message ne puisse arriver."""
    global levels_data, warns_data, mutes_data, invites_data, giveaways_data, salon_pauses_data
    global reglement_data, role_menus_data
    levels_data = await load("levels")
    warns_data = await load("warns")
    mutes_data = await load("mutes")
    invites_data = await load("invites")
    giveaways_data = await load("giveaways")
    salon_pauses_data = await load("salon_pauses")
    reglement_data = await load("reglement")
    role_menus_data = await load("role_menus")
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

PAUSE_DERNIER_MESSAGE = {}  # { "channel_id": timestamp du dernier message autorisé } — en mémoire uniquement

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    # ── Pause de salon : délai minimum entre CHAQUE message, tous auteurs confondus ──
    cid = str(message.channel.id)
    delai_pause = salon_pauses_data.get(cid)
    if delai_pause:
        maintenant_pause = datetime.now().timestamp()
        dernier_message = PAUSE_DERNIER_MESSAGE.get(cid)
        if dernier_message is not None and maintenant_pause - dernier_message < delai_pause:
            restant = delai_pause - (maintenant_pause - dernier_message)
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            try:
                await message.channel.send(
                    f"⏳ {message.author.mention} Ce salon est en pause, réessaie dans `{restant:.1f}s`.",
                    delete_after=5
                )
            except discord.Forbidden:
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
class CloseButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="fermer_ticket_btn", emoji="🔒")
    async def bouton_fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 **Le ticket va se fermer et être supprimé dans 5 secondes...**")
        
        # Génère le transcript avant de fermer
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
        except Exception as e:
            print(f"Erreur fermeture ticket : {e}")

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
            await ticket_channel.send(embed=embed, view=CloseButton())
            
            # Log de l'ouverture
            await envoyer_log(guild, "🎫 Ticket Ouvert", f"Ticket créé par {interaction.user.mention} ({ticket_channel.mention})", 0x00FF00, interaction.user)

        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas la permission de **Gérer les salons** ou de **Gérer les rôles**.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Impossible de créer le ticket. Erreur : `{e}`", ephemeral=True)

# ── Système de Règlement (bouton "J'ai lu et j'accepte") ─────────────────────
class ReglementView(discord.ui.View):
    """Vue persistante attachée au message du règlement. Liée à un message précis
    via message_id (voir bot.add_view(..., message_id=...)), donc le même
    custom_id peut être réutilisé sans risque même si plusieurs règlements
    (sur plusieurs serveurs, ou avec des rôles différents) sont configurés."""
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="J'ai lu et j'accepte le règlement", style=discord.ButtonStyle.success, custom_id="reglement_accept_btn", emoji="✅")
    async def bouton_accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ Le rôle configuré pour le règlement est introuvable. Préviens un administrateur.", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.response.send_message("✅ Tu as déjà validé le règlement, tu as accès au serveur !", ephemeral=True)
            return

        try:
            await interaction.user.add_roles(role, reason="Règlement accepté")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de t'attribuer ce rôle (vérifie la position de mon rôle bot).", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ Merci d'avoir lu le règlement ! Le rôle **{role.name}** t'a été attribué, bienvenue sur le serveur 🎉",
            ephemeral=True
        )
        await envoyer_log(interaction.guild, "📜 Règlement Accepté", f"{interaction.user.mention} a accepté le règlement et reçu le rôle {role.mention}.", 0x2ECC71, interaction.user)

# ── Système de Rôles à la carte (menu déroulant auto-attribuable) ────────────
class RoleMenuView(discord.ui.View):
    """Vue persistante avec un menu déroulant multi-sélection. Comme pour le
    règlement, elle est liée à un message précis via message_id, donc le
    custom_id du select ("role_menu_select") peut être réutilisé sur plusieurs
    menus différents sans qu'ils ne se marchent dessus."""
    def __init__(self, roles: list):
        super().__init__(timeout=None)
        self.roles_map = {str(r.id): r for r in roles}

        self.select = discord.ui.Select(
            placeholder="Choisis un ou plusieurs rôles...",
            min_values=0,
            max_values=len(roles),
            custom_id="role_menu_select",
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
            doit_avoir = role_id in selectionnes
            if doit_avoir and not a_le_role:
                ajoutes.append(role)
            elif not doit_avoir and a_le_role:
                retires.append(role)

        try:
            if ajoutes:
                await membre.add_roles(*ajoutes, reason="Choix via le menu de rôles")
            if retires:
                await membre.remove_roles(*retires, reason="Retiré via le menu de rôles")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de gérer ces rôles (vérifie la position de mon rôle bot).", ephemeral=True)
            return

        parties = []
        if ajoutes:
            parties.append("✅ Ajouté(s) : " + ", ".join(r.mention for r in ajoutes))
        if retires:
            parties.append("➖ Retiré(s) : " + ", ".join(r.mention for r in retires))
        await interaction.response.send_message("\n".join(parties) if parties else "Aucun changement.", ephemeral=True)

# ── Initialisation ────────────────────────────────────────────────────────────
# on_ready se redéclenche à CHAQUE reconnexion à la gateway Discord (coupure
# réseau, resume raté, spin-down/wake sur Render...), pas seulement au premier
# démarrage. Sans garde, ça relance le sync des commandes + un appel guild.invites()
# par serveur à chaque reconnexion, ce qui peut suffire à déclencher un blocage
# global (429) si plusieurs reconnexions surviennent en peu de temps.
premiere_connexion = True

@bot.event
async def on_ready():
    global premiere_connexion
    print(f"✅ Bot connecté : {bot.user}")

    if not premiere_connexion:
        print("🔁 Reconnexion à la gateway détectée — sync et scan des invitations ignorés (déjà faits au premier démarrage).")
        return
    premiere_connexion = False

    bot.add_view(TicketButton())
    bot.add_view(CloseButton())

    # Reconstruction des vues persistantes du règlement (une par message configuré)
    for message_id, data in reglement_data.items():
        guild = bot.get_guild(data["guild_id"])
        if not guild:
            continue
        role = guild.get_role(data["role_id"])
        if not role:
            print(f"⚠️ Rôle introuvable pour le règlement du message {message_id}, vue ignorée.")
            continue
        try:
            bot.add_view(ReglementView(role.id), message_id=int(message_id))
        except Exception as e:
            print(f"❌ Erreur reconstruction vue règlement ({message_id}) : {e}")

    # Reconstruction des vues persistantes des menus de rôles (une par message configuré)
    for message_id, data in role_menus_data.items():
        guild = bot.get_guild(data["guild_id"])
        if not guild:
            continue
        roles = [guild.get_role(rid) for rid in data.get("role_ids", [])]
        roles = [r for r in roles if r is not None]
        if not roles:
            print(f"⚠️ Aucun rôle valide pour le menu {message_id}, vue ignorée.")
            continue
        try:
            bot.add_view(RoleMenuView(roles), message_id=int(message_id))
        except Exception as e:
            print(f"❌ Erreur reconstruction vue menu de rôles ({message_id}) : {e}")

    print(f"✅ {len(reglement_data)} règlement(s) et {len(role_menus_data)} menu(s) de rôles rechargés.")

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
        except Exception as e:
            print(f"❌ Erreur chargement invites pour {guild.name} : {e}")

    # is_running() en plus du flag : évite un RuntimeError ("task already launched")
    # si jamais cette section devait un jour être ré-exécutée.
    if not check_mutes.is_running():
        check_mutes.start()
    if not check_giveaways.is_running():
        check_giveaways.start()

@bot.event
async def on_resumed():
    print("🔁 Session Discord reprise (resume) après une coupure réseau.")

@bot.event
async def on_disconnect():
    print("⚠️ Déconnecté de la gateway Discord (reconnexion en cours...).")

# ── Système de Bienvenue, Départs et Invitations ──────────────────────────────
@bot.event
async def on_invite_create(invite):
    gid = str(invite.guild.id)
    if gid not in invites_data:
        invites_data[gid] = {}
    invites_data[gid][invite.code] = {
        "inviter_id": str(invite.inviter.id) if invite.inviter else None,
        "uses": 0,
        "joined": [],
        "left": []
    }
    await save("invites", invites_data)

@bot.event
async def on_member_join(member):
    gid = str(member.guild.id)
    
    try:
        await member.send(
            f"Salut {member.mention} ! Bienvenue sur **{member.guild.name}** ! 🎉\n"
            f"N'hésite pas à aller lire le règlement et à passer un bon moment avec nous !"
        )
    except discord.Forbidden:
        print(f"Impossible d'envoyer un DM de bienvenue à {member.display_name} (DMs fermés).")

    salon_bienvenue = member.guild.get_channel(SALON_BIENVENUE_ID)
    if salon_bienvenue:
        embed = discord.Embed(
            title="👋 Un nouveau membre vient d'arriver !",
            description=f"Bienvenue {member.mention} sur **{member.guild.name}** !\nNous sommes maintenant {member.guild.member_count} membres.",
            color=0x00FF00
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1513873145910530208/1521214368082296842/896D0229-19B8-4AD8-BD18-48C1FB5F1651.gif?ex=6a4404c8&is=6a42b348&hm=f888ab2f293ed8b23ce2b67a6c8a382e0f4bfd62293a5dad02a3d1ca3d9518e3&") 
        embed.set_thumbnail(url=member.display_avatar.url)
        await salon_bienvenue.send(embed=embed)

    try:
        new_invites = await member.guild.invites()
        old_invites = invites_data.get(gid, {})

        print(f"🔍 [{member.display_name}] Ancien état : {old_invites}")
        print(f"🔍 [{member.display_name}] Nouvel état : {[(i.code, i.uses) for i in new_invites]}")

        for inv in new_invites:
            old = old_invites.get(inv.code, {})
            old_uses = old.get("uses", 0)
            print(f"🔍 Comparaison {inv.code} : uses={inv.uses} vs old_uses={old_uses}")
            if inv.uses is not None and inv.uses > old_uses:
                if gid not in invites_data:
                    invites_data[gid] = {}
                if inv.code not in invites_data[gid]:
                    invites_data[gid][inv.code] = {
                        "inviter_id": str(inv.inviter.id) if inv.inviter else None,
                        "uses": 0,
                        "joined": [],
                        "left": []
                    }
                invites_data[gid][inv.code]["uses"] = inv.uses
                invites_data[gid][inv.code]["joined"].append(str(member.id))
                await save("invites", invites_data)
                print(f"✅ Invitation {inv.code} attribuée à {member.display_name}")
                break
    except Exception as e:
        print(f"❌ Erreur tracking invitation : {e}")

@bot.event
async def on_member_remove(member):
    gid = str(member.guild.id)
    uid = str(member.id)
    
    salon_depart = member.guild.get_channel(SALON_DEPART_ID)  # ← changé ici
    if salon_depart:
        embed = discord.Embed(
            title="😢 Départ d'un membre",
            description=f"**{member.display_name}** a quitté le serveur. À bientôt...",
            color=0xFF0000
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1520903056202530940/1522952890904215683/image0.gif?ex=6a4a57e8&is=6a490668&hm=4e242b93c14d591d3b2d9814fa23ad4a40166e5be625360c9debecfb30a0a993&")
        await salon_depart.send(embed=embed)

    if gid in invites_data:
        for code, data in invites_data[gid].items():
            if uid in data.get("joined", []):
                data["left"].append(uid)
                await save("invites", invites_data)
                break
# ── Tâche mutes temporaires ──────────────────────────────────────────────────
@tasks.loop(seconds=30)
async def check_mutes():
    now = datetime.now().timestamp()
    to_unmute = []
    for gid, users in mutes_data.items():
        for uid, data in users.items():
            if data.get("end_time") and now >= data["end_time"]:
                to_unmute.append((gid, uid))

    for gid, uid in to_unmute:
        guild = bot.get_guild(int(gid))
        if guild:
            member = guild.get_member(int(uid))
            if member:
                mute_role = discord.utils.get(guild.roles, name="Muted")
                if mute_role and mute_role in member.roles:
                    await member.remove_roles(mute_role)
        del mutes_data[gid][uid]
    if to_unmute:
        await save("mutes", mutes_data)

# ── Système de Giveaways ──────────────────────────────────────────────────────
GIVEAWAY_EMOJI = "🎉"

def parse_duree(duree_str):
    """Convertit '30s', '10m', '2h', '1d' en secondes. Retourne None si invalide."""
    duree_str = duree_str.strip().lower()
    if len(duree_str) < 2:
        return None
    unite = duree_str[-1]
    nombre = duree_str[:-1]
    unites = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if unite not in unites or not nombre.isdigit():
        return None
    return int(nombre) * unites[unite]

async def terminer_giveaway(message_id, force_gagnants=None):
    """Tire au sort le(s) gagnant(s) d'un giveaway, annonce le résultat et met à jour l'embed."""
    data = giveaways_data.get(str(message_id))
    if not data:
        return None

    guild = bot.get_guild(data["guild_id"])
    if not guild:
        return None
    channel = guild.get_channel(data["channel_id"])
    if not channel:
        return None

    try:
        message = await channel.fetch_message(int(message_id))
    except (discord.NotFound, discord.Forbidden):
        data["ended"] = True
        await save("giveaways", giveaways_data)
        return None

    reaction = discord.utils.get(message.reactions, emoji=GIVEAWAY_EMOJI)
    participants = []
    if reaction:
        async for user in reaction.users():
            if not user.bot:
                participants.append(user)

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
    embed.description = (
        f"**Lot : {data['prix']}**\n\n"
        f"Gagnant(s) : {mentions}\n"
        f"Organisé par : <@{data['host_id']}>"
    )
    embed.color = 0x95A5A6
    try:
        await message.edit(embed=embed)
    except:
        pass

    try:
        await channel.send(texte_resultat)
    except:
        pass

    data["ended"] = True
    await save("giveaways", giveaways_data)
    return gagnants

@tasks.loop(seconds=30)
async def check_giveaways():
    now = datetime.now().timestamp()
    a_terminer = [mid for mid, d in giveaways_data.items() if not d.get("ended") and now >= d.get("end_time", 0)]
    for mid in a_terminer:
        try:
            await terminer_giveaway(mid)
        except Exception as e:
            print(f"Erreur fin de giveaway {mid} : {e}")

# ── Commandes de Logs ────────────────────────────────────────────────────────
@bot.tree.command(name="log", description="Affiche les dernières actions ou redirige vers le salon des logs")
@app_commands.checks.has_permissions(manage_messages=True)
async def log_cmd(interaction: discord.Interaction):
    salon_logs = interaction.guild.get_channel(SALON_LOGS_ID)
    if not salon_logs:
        await interaction.response.send_message("❌ Le salon de logs configuré est introuvable. Modifie l'ID dans le code.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📋 Suivi des Logs du Serveur",
        description=f"Toutes les actions de modération et d'activité du bot sont enregistrées directement dans {salon_logs.mention}.\n\n"
                    f"**Ce qui est tracé :**\n"
                    f"• 🎫 Ouvertures et fermetures de tickets\n"
                    f"• ⚠️ Avertissements (Warns)\n"
                    f"• 🔇 Mutes et Unmutes\n"
                    f"• 👢 Expulsions (Kick) & Bannissements (Ban)",
        color=0x7289DA
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ── Commandes Nouvelles (Tickets, Clear) ──────────────────────────────────────
@bot.tree.command(name="setup_ticket", description="Configure le panel pour créer des tickets")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
    title="📞 Support et Tickets",
        description="Clique sur le bouton ci-dessous pour ouvrir un ticket et contacter l'équipe du serveur.",
        color=0x2b2d31
    )
    await interaction.channel.send(embed=embed, view=TicketButton())
    await interaction.response.send_message("✅ Panel de tickets créé avec succès.", ephemeral=True)

# ── Commande de configuration du Règlement ────────────────────────────────────
@bot.tree.command(name="setup_reglement", description="Poste le règlement avec un bouton à cocher qui donne le rôle membre")
@app_commands.describe(
    role="Le rôle attribué automatiquement une fois le règlement accepté",
    texte="Le texte du règlement à afficher (utilise \\n pour des retours à la ligne)",
    salon="Le salon où poster le règlement (défaut : salon actuel)"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_reglement_cmd(interaction: discord.Interaction, role: discord.Role, texte: str, salon: discord.TextChannel = None):
    cible = salon or interaction.channel

    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            f"❌ Mon rôle est trop bas dans la hiérarchie pour attribuer **{role.name}**.\n"
            f"Monte le rôle du bot au-dessus de **{role.name}** dans les paramètres du serveur, puis réessaie.",
            ephemeral=True
        )
        return

    embed = discord.Embed(title="📜 Règlement du serveur", description=texte.replace("\\n", "\n"), color=0x2b2d31)
    embed.set_footer(text="Clique sur le bouton ci-dessous une fois le règlement lu pour accéder au serveur.")

    view = ReglementView(role.id)
    message = await cible.send(embed=embed, view=view)

    reglement_data[str(message.id)] = {
        "guild_id": interaction.guild.id,
        "channel_id": cible.id,
        "role_id": role.id
    }
    await save("reglement", reglement_data)
    bot.add_view(view, message_id=message.id)

    await interaction.response.send_message(f"✅ Règlement posté dans {cible.mention}. Le rôle {role.mention} sera donné dès qu'il est accepté.", ephemeral=True)
    await envoyer_log(interaction.guild, "📜 Règlement Configuré", f"Salon : {cible.mention}\nRôle attribué : {role.mention}", 0x2b2d31, interaction.user)

# ── Commande de configuration des Rôles à la carte ────────────────────────────
@bot.tree.command(name="setup_roles", description="Poste un menu déroulant permettant à chacun de choisir ses propres rôles")
@app_commands.describe(
    role1="Rôle proposé dans le menu",
    role2="Rôle proposé dans le menu (optionnel)",
    role3="Rôle proposé dans le menu (optionnel)",
    role4="Rôle proposé dans le menu (optionnel)",
    role5="Rôle proposé dans le menu (optionnel)",
    role6="Rôle proposé dans le menu (optionnel)",
    role7="Rôle proposé dans le menu (optionnel)",
    role8="Rôle proposé dans le menu (optionnel)",
    role9="Rôle proposé dans le menu (optionnel)",
    role10="Rôle proposé dans le menu (optionnel)",
    salon="Le salon où poster le menu (défaut : salon actuel)",
    titre="Titre de l'embed (optionnel)",
    description="Texte affiché au-dessus du menu (optionnel)"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_roles_cmd(
    interaction: discord.Interaction,
    role1: discord.Role,
    role2: discord.Role = None, role3: discord.Role = None, role4: discord.Role = None, role5: discord.Role = None,
    role6: discord.Role = None, role7: discord.Role = None, role8: discord.Role = None, role9: discord.Role = None,
    role10: discord.Role = None,
    salon: discord.TextChannel = None,
    titre: str = "🎭 Choisis tes rôles",
    description: str = "Sélectionne dans le menu ci-dessous le ou les rôles que tu veux obtenir.\nDésélectionne-le pour te le retirer."
):
    cible = salon or interaction.channel
    roles = [r for r in [role1, role2, role3, role4, role5, role6, role7, role8, role9, role10] if r is not None]

    roles_trop_hauts = [r for r in roles if r >= interaction.guild.me.top_role]
    if roles_trop_hauts:
        noms = ", ".join(r.name for r in roles_trop_hauts)
        await interaction.response.send_message(
            f"❌ Mon rôle est trop bas dans la hiérarchie pour gérer : **{noms}**.\n"
            f"Monte le rôle du bot au-dessus de ces rôles dans les paramètres du serveur, puis réessaie.",
            ephemeral=True
        )
        return

    embed = discord.Embed(title=titre, description=description, color=0x7289DA)
    embed.set_footer(text=f"{len(roles)} rôle(s) disponible(s)")

    view = RoleMenuView(roles)
    message = await cible.send(embed=embed, view=view)

    role_menus_data[str(message.id)] = {
        "guild_id": interaction.guild.id,
        "channel_id": cible.id,
        "role_ids": [r.id for r in roles]
    }
    await save("role_menus", role_menus_data)
    bot.add_view(view, message_id=message.id)

    await interaction.response.send_message(f"✅ Menu de rôles créé dans {cible.mention} avec {len(roles)} rôle(s).", ephemeral=True)
    await envoyer_log(interaction.guild, "🎭 Menu de Rôles Créé", f"Salon : {cible.mention}\nRôles : {', '.join(r.mention for r in roles)}", 0x7289DA, interaction.user)

@bot.tree.command(name="clear", description="Supprimer massivement des messages dans un salon")
@app_commands.describe(montant="Nombre de messages à supprimer", salon="Le salon à nettoyer (par défaut : salon actuel)")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_cmd(interaction: discord.Interaction, montant: int = 1000, salon: discord.TextChannel = None):
    cible = salon or interaction.channel
    await interaction.response.defer(ephemeral=True)
    
    try:
        deleted = await cible.purge(limit=montant)
        await interaction.followup.send(f"✅ `{len(deleted)}` messages ont été supprimés dans {cible.mention}.")
        await envoyer_log(interaction.guild, "🧹 Salon Nettoyé", f"`{len(deleted)}` messages ont été purgés dans {cible.mention}.", 0x3498DB, interaction.user)
    except discord.Forbidden:
        await interaction.followup.send("❌ Je n'ai pas la permission de gérer les messages dans ce salon.")
    except Exception as e:
        await interaction.followup.send(f"❌ Une erreur s'est produite : {e}")

# ── Commandes Niveaux ─────────────────────────────────────────────────────────
@bot.tree.command(name="niveau", description="Voir ton niveau ou celui d'un membre")
@app_commands.describe(membre="Le membre à inspecter (optionnel)")
async def niveau_cmd(interaction: discord.Interaction, membre: discord.Member = None):
    cible = membre or interaction.user
    gid = str(interaction.guild.id)
    uid = str(cible.id)

    data = levels_data.get(gid, {}).get(uid, {"xp": 0, "niveau": 0, "messages": 0})
    niveau = data["niveau"]
    xp = data["xp"]
    xp_actuel = xp - sum(xp_pour_niveau(i) for i in range(1, niveau + 1)) if niveau > 0 else xp
    xp_prochain = xp_pour_niveau(niveau + 1)

    classement = sorted(levels_data.get(gid, {}).items(), key=lambda x: x[1].get("xp", 0), reverse=True)
    rank = next((i+1 for i, (u, _) in enumerate(classement) if u == uid), "?")

    embed = discord.Embed(title=f"⭐ Niveau de {cible.display_name}", color=0xFFD700)
    embed.add_field(name="Niveau", value=str(niveau), inline=True)
    embed.add_field(name="XP", value=f"{xp_actuel} / {xp_prochain}", inline=True)
    embed.add_field(name="Classement", value=f"#{rank}", inline=True)
    embed.add_field(name="Messages", value=str(data.get("messages", 0)), inline=True)
    embed.set_thumbnail(url=cible.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="classement", description="Top 10 des membres les plus actifs")
async def classement_cmd(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    membres = levels_data.get(gid, {})
    top = sorted(membres.items(), key=lambda x: x[1].get("xp", 0), reverse=True)[:10]

    embed = discord.Embed(title="🏆 Classement du serveur", color=0xFFD700)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, data) in enumerate(top):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        lines.append(f"{medal} <@{uid}> — Niveau **{data['niveau']}** ({data['xp']} XP)")

    embed.description = "\n".join(lines) if lines else "Aucun membre actif."
    await interaction.response.send_message(embed=embed)

# ── Commandes Invitations ─────────────────────────────────────────────────────
@bot.tree.command(name="invitations", description="Voir les invitations d'un membre")
@app_commands.describe(membre="Le membre à inspecter (optionnel)")
async def invitations_cmd(interaction: discord.Interaction, membre: discord.Member = None):
    cible = membre or interaction.user
    gid = str(interaction.guild.id)
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
    await interaction.response.send_message(embed=embed)

# ── Commandes Modération ──────────────────────────────────────────────────────
@bot.tree.command(name="warn", description="Avertir un membre")
@app_commands.describe(membre="Le membre à avertir", raison="La raison")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    if gid not in warns_data: warns_data[gid] = {}
    if uid not in warns_data[gid]: warns_data[gid][uid] = []
    warns_data[gid][uid].append({"raison": raison, "date": str(datetime.now()), "by": str(interaction.user.id)})
    await save("warns", warns_data)
    nb = len(warns_data[gid][uid])
    embed = discord.Embed(title="⚠️ Avertissement", color=0xFFA500)
    embed.add_field(name="Membre", value=membre.mention, inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    embed.add_field(name="Total warns", value=str(nb), inline=True)
    await interaction.response.send_message(embed=embed)
    
    await envoyer_log(interaction.guild, "⚠️ Membre Warn", f"Membre : {membre.mention}\nRaison : {raison}\nTotal : {nb} warn(s)", 0xFFA500, interaction.user)
    try:
        await membre.send(f"⚠️ Tu as reçu un avertissement sur **{interaction.guild.name}**\nRaison : {raison}\nTotal : {nb} warn(s)")
    except:
        pass

@bot.tree.command(name="warns", description="Voir les avertissements d'un membre")
@app_commands.describe(membre="Le membre")
@app_commands.checks.has_permissions(manage_messages=True)
async def warns_cmd(interaction: discord.Interaction, membre: discord.Member):
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    liste = warns_data.get(gid, {}).get(uid, [])
    embed = discord.Embed(title=f"⚠️ Warns de {membre.display_name}", color=0xFFA500)
    if not liste:
        embed.description = "Aucun avertissement."
    else:
        for i, w in enumerate(liste, 1):
            embed.add_field(name=f"Warn #{i}", value=f"Raison : {w['raison']}\nPar : <@{w['by']}>", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarns", description="Supprimer les warns d'un membre")
@app_commands.describe(membre="Le membre")
@app_commands.checks.has_permissions(administrator=True)
async def clearwarns_cmd(interaction: discord.Interaction, membre: discord.Member):
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    if gid in warns_data and uid in warns_data[gid]:
        warns_data[gid][uid] = []
        await save("warns", warns_data)
    await interaction.response.send_message(f"✅ Warns de {membre.mention} supprimés.", ephemeral=True)
    await envoyer_log(interaction.guild, "✨ Warns Effacés", f"Les avertissements de {membre.mention} ont été remis à zéro.", 0x2ECC71, interaction.user)

@bot.tree.command(name="mute", description="Rendre muet un membre")
@app_commands.describe(membre="Le membre", duree="Durée en minutes (0 = permanent)", raison="La raison")
@app_commands.checks.has_permissions(manage_roles=True)
async def mute_cmd(interaction: discord.Interaction, membre: discord.Member, duree: int = 0, raison: str = "Aucune raison"):
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await interaction.guild.create_role(name="Muted")
        for channel in interaction.guild.channels:
            await channel.set_permissions(mute_role, send_messages=False, speak=False)

    await membre.add_roles(mute_role)
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    if gid not in mutes_data: mutes_data[gid] = {}
    end_time = (datetime.now() + timedelta(minutes=duree)).timestamp() if duree > 0 else None
    mutes_data[gid][uid] = {"end_time": end_time, "raison": raison}
    await save("mutes", mutes_data)

    duree_str = f"{duree} minute(s)" if duree > 0 else "Permanent"
    embed = discord.Embed(title="🔇 Membre muet", color=0xFF0000)
    embed.add_field(name="Membre", value=membre.mention, inline=True)
    embed.add_field(name="Durée", value=duree_str, inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await interaction.response.send_message(embed=embed)
    
    await envoyer_log(interaction.guild, "🔇 Membre Mute", f"Membre : {membre.mention}\nDurée : {duree_str}\nRaison : {raison}", 0xE74C3C, interaction.user)

@bot.tree.command(name="unmute", description="Retirer le mute d'un membre")
@app_commands.describe(membre="Le membre")
@app_commands.checks.has_permissions(manage_roles=True)
async def unmute_cmd(interaction: discord.Interaction, membre: discord.Member):
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if mute_role and mute_role in membre.roles:
        await membre.remove_roles(mute_role)
    gid = str(interaction.guild.id)
    uid = str(membre.id)
    if gid in mutes_data and uid in mutes_data[gid]:
        del mutes_data[gid][uid]
        await save("mutes", mutes_data)
    await interaction.response.send_message(f"✅ {membre.mention} n'est plus muet.", ephemeral=True)
    await envoyer_log(interaction.guild, "🔊 Membre Unmute", f"Le rôle Muted a été retiré à {membre.mention}.", 0x2ECC71, interaction.user)

@bot.tree.command(name="kick", description="Expulser un membre")
@app_commands.describe(membre="Le membre", raison="La raison")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    await membre.kick(reason=raison)
    embed = discord.Embed(title="👢 Membre expulsé", color=0xFF6600)
    embed.add_field(name="Membre", value=str(membre), inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await interaction.response.send_message(embed=embed)
    await envoyer_log(interaction.guild, "👢 Membre Kické", f"Pseudo : **{membre}**\nRaison : {raison}", 0xE67E22, interaction.user)

@bot.tree.command(name="ban", description="Bannir un membre")
@app_commands.describe(membre="Le membre", raison="La raison")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    await membre.ban(reason=raison)
    embed = discord.Embed(title="🔨 Membre banni", color=0xFF0000)
    embed.add_field(name="Membre", value=str(membre), inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await interaction.response.send_message(embed=embed)
    await envoyer_log(interaction.guild, "🔨 Membre Banni", f"Pseudo : **{membre}**\nRaison : {raison}", 0x95A5A6, interaction.user)

@bot.tree.command(name="unban", description="Débannir un membre")
@app_commands.describe(user_id="L'ID du membre banni")
@app_commands.checks.has_permissions(ban_members=True)
async def unban_cmd(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ {user} a été débanni.", ephemeral=True)
        await envoyer_log(interaction.guild, "🔓 Membre Débanni", f"ID de l'utilisateur : `{user_id}` (Nom : {user})", 0x2ECC71, interaction.user)
    except:
        await interaction.response.send_message("❌ Utilisateur introuvable ou pas banni.", ephemeral=True)

# ── Verrouillage de salons ─────────────────────────────────────────────────────
@bot.tree.command(name="lock", description="Verrouiller un salon (empêche l'envoi de messages)")
@app_commands.describe(salon="Le salon à verrouiller (défaut : salon actuel)", raison="La raison du verrouillage")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock_cmd(interaction: discord.Interaction, salon: discord.TextChannel = None, raison: str = "Aucune raison"):
    cible = salon or interaction.channel
    overwrite = cible.overwrites_for(interaction.guild.default_role)

    if overwrite.send_messages is False:
        await interaction.response.send_message(f"❌ {cible.mention} est déjà verrouillé.", ephemeral=True)
        return

    overwrite.send_messages = False
    try:
        await cible.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=raison)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Je n'ai pas la permission de gérer ce salon.", ephemeral=True)
        return

    embed = discord.Embed(title="🔒 Salon Verrouillé", color=0xFF0000)
    embed.add_field(name="Salon", value=cible.mention, inline=True)
    embed.add_field(name="Raison", value=raison, inline=True)
    await interaction.response.send_message(embed=embed)
    try:
        await cible.send("🔒 **Ce salon vient d'être verrouillé.** Personne ne peut envoyer de message pour le moment.")
    except:
        pass

    await envoyer_log(interaction.guild, "🔒 Salon Verrouillé", f"Salon : {cible.mention}\nRaison : {raison}", 0xFF0000, interaction.user)

@bot.tree.command(name="unlock", description="Déverrouiller un salon")
@app_commands.describe(salon="Le salon à déverrouiller (défaut : salon actuel)")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock_cmd(interaction: discord.Interaction, salon: discord.TextChannel = None):
    cible = salon or interaction.channel
    overwrite = cible.overwrites_for(interaction.guild.default_role)

    if overwrite.send_messages is not False:
        await interaction.response.send_message(f"❌ {cible.mention} n'est pas verrouillé.", ephemeral=True)
        return

    overwrite.send_messages = None
    try:
        if overwrite.is_empty():
            await cible.set_permissions(interaction.guild.default_role, overwrite=None)
        else:
            await cible.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Je n'ai pas la permission de gérer ce salon.", ephemeral=True)
        return

    embed = discord.Embed(title="🔓 Salon Déverrouillé", color=0x2ECC71)
    embed.add_field(name="Salon", value=cible.mention, inline=True)
    await interaction.response.send_message(embed=embed)
    try:
        await cible.send("🔓 **Ce salon a été déverrouillé.** Vous pouvez à nouveau envoyer des messages.")
    except:
        pass

    await envoyer_log(interaction.guild, "🔓 Salon Déverrouillé", f"Salon : {cible.mention}", 0x2ECC71, interaction.user)

@bot.tree.command(name="slowmode", description="Définir le mode lent d'un salon")
@app_commands.describe(secondes="Délai en secondes entre chaque message (0 pour désactiver)", salon="Le salon concerné (défaut : salon actuel)")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode_cmd(interaction: discord.Interaction, secondes: int, salon: discord.TextChannel = None):
    cible = salon or interaction.channel
    if secondes < 0 or secondes > 21600:
        await interaction.response.send_message("❌ Le délai doit être compris entre 0 et 21600 secondes (6h).", ephemeral=True)
        return

    await cible.edit(slowmode_delay=secondes)
    if secondes == 0:
        await interaction.response.send_message(f"✅ Mode lent désactivé dans {cible.mention}.")
    else:
        await interaction.response.send_message(f"✅ Mode lent réglé à `{secondes}s` dans {cible.mention}.")

    await envoyer_log(interaction.guild, "🐌 Mode Lent Modifié", f"Salon : {cible.mention}\nDélai : {secondes}s", 0x3498DB, interaction.user)

@bot.tree.command(name="pause", description="Cooldown global sur un salon : délai minimum entre CHAQUE message, tous utilisateurs confondus")
@app_commands.describe(secondes="Délai en secondes entre chaque message, peu importe l'auteur (0 pour désactiver)", salon="Le salon concerné (défaut : salon actuel)")
@app_commands.checks.has_permissions(manage_channels=True)
async def pause_cmd(interaction: discord.Interaction, secondes: int, salon: discord.TextChannel = None):
    cible = salon or interaction.channel
    cid = str(cible.id)

    if secondes < 0 or secondes > 21600:
        await interaction.response.send_message("❌ Le délai doit être compris entre 0 et 21600 secondes (6h).", ephemeral=True)
        return

    if secondes == 0:
        if cid not in salon_pauses_data:
            await interaction.response.send_message(f"❌ {cible.mention} n'est pas en pause.", ephemeral=True)
            return
        salon_pauses_data.pop(cid, None)
        PAUSE_DERNIER_MESSAGE.pop(cid, None)
        await save("salon_pauses", salon_pauses_data)
        await interaction.response.send_message(f"✅ Pause désactivée dans {cible.mention}.")
        await envoyer_log(interaction.guild, "⏳ Pause de Salon Désactivée", f"Salon : {cible.mention}", 0x3498DB, interaction.user)
        return

    salon_pauses_data[cid] = secondes
    PAUSE_DERNIER_MESSAGE.pop(cid, None)  # on repart de zéro pour ne pas bloquer sur un ancien horodatage
    await save("salon_pauses", salon_pauses_data)

    await interaction.response.send_message(
        f"✅ Pause réglée à `{secondes}s` dans {cible.mention}.\n"
        f"Après chaque message, plus personne ne pourra en envoyer un autre avant la fin du délai."
    )
    await envoyer_log(interaction.guild, "⏳ Pause de Salon Activée", f"Salon : {cible.mention}\nDélai : {secondes}s", 0x3498DB, interaction.user)

# ── Stats du serveur ──────────────────────────────────────────────────────────
@bot.tree.command(name="stats", description="Statistiques du serveur")
async def stats_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    total = guild.member_count
    bots = sum(1 for m in guild.members if m.bot)
    humains = total - bots
    en_ligne = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
    salons_texte = len(guild.text_channels)
    salons_vocal = len(guild.voice_channels)
    roles = len(guild.roles)
    boosts = guild.premium_subscription_count

    embed = discord.Embed(title=f"📊 Stats de {guild.name}", color=0x7289DA)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="👥 Membres", value=str(humains), inline=True)
    embed.add_field(name="🤖 Bots", value=str(bots), inline=True)
    embed.add_field(name="🟢 En ligne", value=str(en_ligne), inline=True)
    embed.add_field(name="💬 Salons texte", value=str(salons_texte), inline=True)
    embed.add_field(name="🔊 Salons vocal", value=str(salons_vocal), inline=True)
    embed.add_field(name="🎭 Rôles", value=str(roles), inline=True)
    embed.add_field(name="🚀 Boosts", value=str(boosts), inline=True)
    embed.add_field(name="📅 Créé le", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="👑 Propriétaire", value=f"<@{guild.owner_id}>", inline=True)
    await interaction.response.send_message(embed=embed)

# ── Commandes Giveaway ─────────────────────────────────────────────────────────
@bot.tree.command(name="gw", description="Lancer un giveaway")
@app_commands.describe(
    duree="Durée du giveaway (ex : 30s, 10m, 2h, 1d)",
    prix="Le lot à gagner",
    gagnants="Nombre de gagnants (défaut : 1)",
    salon="Le salon où lancer le giveaway (défaut : salon actuel)"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def gw_cmd(interaction: discord.Interaction, duree: str, prix: str, gagnants: int = 1, salon: discord.TextChannel = None):
    cible = salon or interaction.channel
    secondes = parse_duree(duree)

    if secondes is None or secondes <= 0:
        await interaction.response.send_message("❌ Format de durée invalide. Utilise par exemple : `30s`, `10m`, `2h`, `1d`.", ephemeral=True)
        return
    if gagnants < 1:
        await interaction.response.send_message("❌ Le nombre de gagnants doit être au moins 1.", ephemeral=True)
        return

    fin = datetime.now(timezone.utc) + timedelta(seconds=secondes)
    end_timestamp = int(fin.timestamp())

    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=(
            f"**Lot : {prix}**\n\n"
            f"Réagis avec 🎉 pour participer !\n"
            f"Nombre de gagnants : **{gagnants}**\n"
            f"Fin : <t:{end_timestamp}:R> (<t:{end_timestamp}:f>)\n"
            f"Organisé par : {interaction.user.mention}"
        ),
        color=0xF1C40F
    )
    embed.set_footer(text="ID sera visible après l'envoi")

    await interaction.response.send_message(f"✅ Giveaway lancé dans {cible.mention} !", ephemeral=True)
    message = await cible.send(embed=embed)
    await message.add_reaction(GIVEAWAY_EMOJI)

    embed.set_footer(text=f"ID : {message.id}")
    await message.edit(embed=embed)

    giveaways_data[str(message.id)] = {
        "guild_id": interaction.guild.id,
        "channel_id": cible.id,
        "host_id": interaction.user.id,
        "prix": prix,
        "gagnants": gagnants,
        "end_time": fin.timestamp(),
        "ended": False
    }
    await save("giveaways", giveaways_data)

    await envoyer_log(interaction.guild, "🎉 Giveaway Lancé", f"Lot : **{prix}**\nSalon : {cible.mention}\nGagnants : {gagnants}\nOrganisé par : {interaction.user.mention}", 0xF1C40F, interaction.user)

@bot.tree.command(name="gw_reroll", description="Retirer au sort de nouveaux gagnants pour un giveaway déjà terminé")
@app_commands.describe(message_id="L'ID du message du giveaway (visible dans le footer de l'embed)", gagnants="Nombre de nouveaux gagnants à tirer (défaut : 1)")
@app_commands.checks.has_permissions(manage_guild=True)
async def gw_reroll_cmd(interaction: discord.Interaction, message_id: str, gagnants: int = 1):
    if message_id not in giveaways_data:
        await interaction.response.send_message("❌ Giveaway introuvable pour cet ID.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    resultat = await terminer_giveaway(message_id, force_gagnants=gagnants)

    if resultat:
        await interaction.followup.send("✅ Nouveau(x) gagnant(s) tiré(s) au sort.", ephemeral=True)
    else:
        await interaction.followup.send("❌ Impossible de tirer au sort (aucun participant ou message introuvable).", ephemeral=True)

@bot.tree.command(name="gw_end", description="Terminer un giveaway immédiatement")
@app_commands.describe(message_id="L'ID du message du giveaway (visible dans le footer de l'embed)")
@app_commands.checks.has_permissions(manage_guild=True)
async def gw_end_cmd(interaction: discord.Interaction, message_id: str):
    data = giveaways_data.get(message_id)
    if not data:
        await interaction.response.send_message("❌ Giveaway introuvable pour cet ID.", ephemeral=True)
        return
    if data.get("ended"):
        await interaction.response.send_message("❌ Ce giveaway est déjà terminé. Utilise `/gw_reroll` pour retirer au sort.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await terminer_giveaway(message_id)
    await interaction.followup.send("✅ Giveaway terminé manuellement.", ephemeral=True)

# ── Gestionnaire d'erreurs pour les commandes Slash ─────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        perms = ", ".join(error.missing_permissions)
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ **Accès refusé :** Tu n'as pas les permissions nécessaires ({perms}).", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ **Accès refusé :** Tu n'as pas les permissions nécessaires ({perms}).", ephemeral=True)
    else:
        print(f"Erreur non gérée : {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Une erreur est survenue lors de l'exécution de la commande.", ephemeral=True)

# ── Lancement ────────────────────────────────────────────────────────────────
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Erreur : DISCORD_TOKEN_GESTION introuvable.")
