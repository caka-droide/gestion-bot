"""
Couche de persistance.

Comportement identique à l'original (une écriture Upstash = tout le dict
réécrit en JSON à chaque `save`), mais encapsulé dans une classe au lieu de
9 variables globales éparpillées. Ça ne corrige pas le problème de scalabilité
(voir note en bas de fichier) mais ça rend l'état testable et injectable.
"""
import json
import aiohttp

import config


class UpstashClient:
    """Petit wrapper autour de l'API REST Upstash Redis."""

    def __init__(self, url: str, token: str):
        if not url or not token:
            raise SystemExit(
                "❌ Il manque UPSTASH_REDIS_REST_URL ou UPSTASH_REDIS_REST_TOKEN "
                "dans les variables d'environnement"
            )
        self._url = url
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _command(self, *args):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._url, headers=self._headers, json=list(args), timeout=10
            ) as resp:
                payload = await resp.json()
        return payload.get("result")

    async def get_json(self, key: str) -> dict:
        try:
            valeur = await self._command("GET", key)
            return json.loads(valeur) if valeur else {}
        except Exception as e:
            print(f"❌ Erreur chargement '{key}' depuis Upstash : {e}")
            return {}

    async def set_json(self, key: str, data: dict) -> None:
        try:
            await self._command("SET", key, json.dumps(data))
        except Exception as e:
            print(f"❌ Erreur sauvegarde '{key}' vers Upstash : {e}")


class DataStore:
    """
    Regroupe toutes les données persistantes du bot au même endroit,
    au lieu des 9 globales (levels_data, warns_data, mutes_data, ...) qui
    étaient importées/mutées un peu partout dans le fichier d'origine.

    Chaque attribut correspond exactement à une clé Upstash existante :
    renommer/déplacer quoi que ce soit ici ne change pas le format des
    données stockées, donc pas de migration nécessaire.
    """

    KEYS = (
        "levels", "warns", "mutes", "invites", "giveaways",
        "salon_pauses", "reglement", "role_menus", "avis",
    )

    def __init__(self, client: UpstashClient):
        self._client = client
        self.levels: dict = {}
        self.warns: dict = {}
        self.mutes: dict = {}
        self.invites: dict = {}
        self.giveaways: dict = {}
        self.salon_pauses: dict = {}
        self.reglement: dict = {}
        self.role_menus: dict = {}
        self.avis: dict = {}

    async def load_all(self) -> None:
        for key in self.KEYS:
            setattr(self, key, await self._client.get_json(key))
        print("✅ Données chargées depuis Upstash Redis")

    async def save(self, key: str) -> None:
        """Sauvegarde la table `key` (ex: 'levels') dans Upstash.

        ⚠️ Note perf/scalabilité (voir analyse) : ceci réécrit l'intégralité
        du dictionnaire en JSON à chaque appel, comme dans le code d'origine.
        C'est volontairement laissé identique pour ne pas changer le
        comportement de durabilité des données ; à surveiller si le nombre
        de membres/serveurs grossit beaucoup (cf. recommandations).
        """
        await self._client.set_json(key, getattr(self, key))
