import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random
import asyncio
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
SALON_BIENVENUE_ID = 1479435186973446286
SALON_DEPART_ID = 1479435186973446287
SALON_LOGS_ID = 1479435189129318524
CATEGORY_TICKETS_ID = 1479435189611397183

# Fonction utilitaire pour envoyer un log automatique dans le salon dédié
async def envoyer_log(guild, titre, description, couleur=0x7289DA, auteur=None):
    salon_logs = guild.get_channel(SALON_LOGS_ID)
    if salon_logs:
        embed = discord.Embed(title=titre, description=description, color=couleur, timestamp=datetime.now())
        if auteur:
            embed.set_footer(text=f"Action par : {auteur.name}", icon_url=auteur.display_avatar.url)
        await salon_logs.send(embed=embed)

# ── Fichiers de données ───────────────────────────────────────────────────────
FILES = {
    "levels": "levels.json",
    "warns": "warns.json",
    "mutes": "mutes.json",
    "invites": "invites.json",
}

def load(key):
    if os.path.exists(FILES[key]):
        with open(FILES[key], "r") as f:
            return json.load(f)
    return {}

def save(key, data):
    with open(FILES[key], "w") as f:
        json.dump(data, f, indent=2)

levels_data = load("levels")
warns_data  = load("warns")
mutes_data  = load("mutes")
invites_data = load("invites")

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

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

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
    save("levels", levels_data)

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

# ── Initialisation ────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user}")
    bot.add_view(TicketButton())
    bot.add_view(CloseButton())
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées")
    except Exception as e:
        print(f"❌ Erreur sync : {e}")

    for guild in bot.guilds:
        gid = str(guild.id)
        try:
            invites = await guild.fetch_invites()
            if gid not in invites_data:
                invites_data[gid] = {}
            for inv in invites:
                invites_data[gid][inv.code] = {
                    "inviter_id": str(inv.inviter.id) if inv.inviter else None,
                    "uses": inv.uses,
                    "joined": [],
                    "left": []
                }
            save("invites", invites_data)
        except:
            pass
    check_mutes.start()

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
    save("invites", invites_data)

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
        new_invites = await member.guild.fetch_invites()
        old_invites = invites_data.get(gid, {})

        for inv in new_invites:
            old = old_invites.get(inv.code, {})
            old_uses = old.get("uses", 0)
            if inv.uses > old_uses:
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
                save("invites", invites_data)
                break
    except:
        pass

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
                save("invites", invites_data)
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
        save("mutes", mutes_data)

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
    codes_utilisés = []

    for code, data in invites_data.get(gid, {}).items():
        if data.get("inviter_id") == uid:
            joins = len(data.get("joined", []))
            left = len(data.get("left", []))
            total_joins += joins
            total_left += left
            if joins > 0:
                codes_utilisés.append(f"`{code}` : {joins} invités ({left} partis)")

    restés = total_joins - total_left

    embed = discord.Embed(title=f"📨 Invitations de {cible.display_name}", color=0x7289DA)
    embed.add_field(name="Total invités", value=str(total_joins), inline=True)
    embed.add_field(name="Restés", value=str(restés), inline=True)
    embed.add_field(name="Partis", value=str(total_left), inline=True)
    if codes_utilisés:
        embed.add_field(name="Détail par lien", value="\n".join(codes_utilisés[:5]), inline=False)
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
    save("warns", warns_data)
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
        save("warns", warns_data)
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
    save("mutes", mutes_data)

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
        save("mutes", mutes_data)
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
