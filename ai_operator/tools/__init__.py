from . import base, browser, builtin, files, http_api, outbox, sql, vision

_loaded = False


def load_all():
    """Idempotently register every tool."""
    global _loaded
    if _loaded:
        return base.REGISTRY
    for m in (builtin, browser, files, sql, http_api, outbox, vision):
        m.register_all()
    _loaded = True
    return base.REGISTRY
