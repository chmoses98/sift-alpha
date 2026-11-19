"""One adapter per sport. Each module defines

    SPORT, MAX_AGE_HOURS, SOURCES = {key: (repo, branch)}
    build(sources: {key: Source}, now: datetime) -> result dict:
        status/reason   only when the adapter itself decides (offseason / unavailable)
        artifact        {"repo","ref","commit","committed_at","path"} of the production artifact
        model_version, projected_at, bet_authority, authority_note
        declaration     the artifact's own authority/status fields, verbatim (source_class derives from it)
        source_class    only when the adapter itself decides (CFB: research only)
        games           operating-forecast game records (schema.make_game); the builder keeps upcoming ones
        research        optional list of research records (source_class "research", never in games[])
"""
from importlib import import_module

SPORTS = ("NBA", "NHL", "CBB", "CFB", "NFL", "MLB")


def load(sport):
    return import_module(f"{__name__}.{sport.lower()}")


def artifact(src, path):
    return {**src.meta(), "path": path}


def ref_string(art, path=None):
    return f"{art['repo']}@{art['commit'][:12]}:{path or art['path']}"
