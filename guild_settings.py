"""
Overrides de configuration par-guild.

Charge guild_settings.json (facultatif) et expose get_id(guild_id, key),
qui renvoie la valeur spécifique à une guild si guild_settings.json en
définit une, et retombe sinon sur la valeur globale de config.py.
"""
import json
import os

import config

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guild_settings.json")


def _load() -> dict:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ guild_settings.json invalide (ignoré, fallback sur config.py) : {e}")
        return {}


_SETTINGS = _load()


def _guild_conf(guild_id: int) -> dict:
    return _SETTINGS.get(str(guild_id), {})


def get_id(guild_id: int, key: str) -> int:
    conf = _guild_conf(guild_id)
    if key in conf:
        return conf[key]
    return getattr(config, key)


def get_allowed_admins(guild_id: int) -> set:
    return set(_guild_conf(guild_id).get("ALLOWED_ADMINS", []))


def get_allowed_staff(guild_id: int) -> set:
    return set(_guild_conf(guild_id).get("ALLOWED_STAFF", []))
