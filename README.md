# Gestion Bot — structure refactorisée

Même bot, même comportement, mais découpé en modules au lieu d'un seul
fichier de 1181 lignes. Aucune commande, aucun message, aucun embed n'a été
changé — voir l'analyse d'architecture fournie dans la conversation pour le
détail des problèmes corrigés.

## Structure

```
config.py          → IDs, couleurs, constantes (tout ce qui était en tête de fichier)
storage.py          → client Upstash + DataStore (remplace les 9 dicts globaux)
permissions.py       → une seule implémentation des checks staff/admin/owner
utils.py             → envoyer_log, envoyer_transcript, parse_duree
keepalive.py         → serveur HTTP pour Render
views.py             → tous les boutons/menus/modals persistants
bot.py               → sous-classe Bot, setup_hook, on_ready, erreurs
main.py              → point d'entrée (lance keep-alive + bot)
cogs/
  activity.py         → pause de salon + XP/niveaux (+niveau, +classement, +pause)
  moderation.py        → warn/mute/kick/ban/lock/clear/unban/slowmode
  tickets.py            → +rename, +staff, +unstaff
  invites.py            → tracking invitations, bienvenue/départ, +i
  giveaways.py          → /gw, /gw_reroll, /gw_end
  owner.py              → setbotname, setpdp, /setup_ticket, /setup_reglement, /setup_roles
  general.py            → help, /stats, /avis, /avis_stats, /log
```

## Migration depuis l'ancien fichier unique

1. Remplace `gestion_bot.py` par ces fichiers (mêmes variables d'environnement :
   `DISCORD_TOKEN_GESTION`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`,
   `PORT`). Aucune donnée Upstash n'a besoin d'être migrée : les clés
   (`levels`, `warns`, `invites`, ...) et leur format JSON sont strictement
   identiques.
2. Sur Render, change la commande de démarrage pour `python main.py`
   (au lieu de `python gestion_bot.py`).
3. Installe les dépendances : `pip install -r requirements.txt`.

## Ce qui n'a volontairement PAS été changé

- Le comportement de `save()` : chaque écriture réenvoie tout le dict à
  Upstash, comme avant. C'est un vrai risque de scalabilité (voir l'analyse),
  mais le corriger changerait la fenêtre de durabilité des données —
  décision à prendre consciemment, pas en cachette dans un "nettoyage de code".
- `SALON_BIENVENUE_ID == SALON_DEPART_ID` dans `config.py` : toujours signalé
  en commentaire, à vérifier de ton côté.
- Le couplage pause/XP dans un seul `on_message` (voir le commentaire dans
  `cogs/activity.py`) : les séparer casserait l'ordre garanti
  pause-avant-XP.

## Pistes d'amélioration non appliquées (changeraient le comportement)

- Stocker chaque utilisateur/serveur sous sa propre clé Upstash (`levels:{guild_id}:{user_id}`)
  au lieu d'un blob unique, pour arrêter de réécrire tout le monde à chaque message.
- Débouncer/batcher les écritures XP (ex: toutes les 10s) plutôt qu'à chaque message.
- Purger `giveaways`/`warns` terminés après un certain temps.
- Ajouter un vrai module de logging (`logging`) à la place des `print()`.
