import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_FILE = ROOT / "emojis.json"
UPLOADED_FILE = ROOT / "emojis.uploaded.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _literal(name: str, emoji_id: str, animated: bool) -> str:
    return f"<{'a' if animated else ''}:{name}:{emoji_id}>"


def _resolve() -> dict:
    source = _load_json(SOURCE_FILE)
    uploaded = _load_json(UPLOADED_FILE)
    resolved = {}
    for key, entry in source.items():
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        if key in uploaded:
            own = uploaded[key]
            resolved[key] = _literal(own["name"], own["id"], bool(own.get("animated")))
        elif entry.get("source"):
            resolved[key] = entry["source"]
        else:
            resolved[key] = entry.get("fallback", "❓")
    return resolved


class Emojis:

    @classmethod
    def reload(cls) -> None:
        for key, value in _resolve().items():
            setattr(cls, key, value)


Emojis.reload()
