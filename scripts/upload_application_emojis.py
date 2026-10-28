import argparse
import asyncio
import base64
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILE = ROOT / "emojis.json"
UPLOADED_FILE = ROOT / "emojis.uploaded.json"
API_BASE = "https://discord.com/api/v10"

MIME_OVERRIDES = {".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg",
                  ".jpeg": "image/jpeg", ".webp": "image/webp"}

_EMOJI_LITERAL_RE = re.compile(r"^<(a)?:([A-Za-z0-9_]+):(\d+)>$")


def parse_emoji_literal(literal) -> dict | None:
    if not isinstance(literal, str):
        return None
    m = _EMOJI_LITERAL_RE.match(literal.strip())
    if not m:
        return None
    return {"animated": bool(m.group(1)), "name": m.group(2), "id": m.group(3)}


def load_token() -> str:
    token = os.environ.get("BOT_TOKEN") or os.environ.get("DISCORD_TOKEN")
    if token:
        return token
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("BOT_TOKEN=") or line.startswith("DISCORD_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("ERROR: no BOT_TOKEN found in the environment or .env", file=sys.stderr)
    sys.exit(1)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        print(f"WARNING: {path.name} is not valid JSON, treating as empty", file=sys.stderr)
        return {}


def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def to_data_uri(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    mime = MIME_OVERRIDES.get(ext) or mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def get_application_id(session: aiohttp.ClientSession) -> str:
    async with session.get(f"{API_BASE}/oauth2/applications/@me") as resp:
        if resp.status != 200:
            body = await resp.text()
            print(f"ERROR: could not resolve application id ({resp.status}): {body}", file=sys.stderr)
            sys.exit(1)
        data = await resp.json()
        return data["id"]


async def download_from_cdn(session: aiohttp.ClientSession, emoji_id: str, animated: bool) -> str | None:
    ext = "gif" if animated else "png"
    url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
    async with session.get(url) as resp:
        if resp.status != 200:
            print(f"  x CDN download failed for {emoji_id}: HTTP {resp.status}")
            return None
        raw = await resp.read()
        mime = "image/gif" if animated else "image/png"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"


async def upload_one(session: aiohttp.ClientSession, app_id: str, key: str,
                      name: str, animated: bool, data_uri: str) -> dict | None:
    async with session.post(
        f"{API_BASE}/applications/{app_id}/emojis",
        json={"name": name, "image": data_uri},
    ) as resp:
        if resp.status not in (200, 201):
            body = await resp.text()
            print(f"  x {key}: upload failed ({resp.status}): {body}")
            return None
        data = await resp.json()
        print(f"  + {key}: uploaded as {data['id']} ({'animated' if animated else 'static'})")
        return {"id": data["id"], "name": data["name"], "animated": animated}


async def run_sync(token: str | None = None, force: bool = False, dry_run: bool = False,
                    quiet: bool = False, timeout: float = 15.0) -> dict:
    """Core sync logic - used by the CLI and by main.py's startup hook."""
    def log(*a):
        if not quiet:
            print(*a)

    source = load_json(SOURCE_FILE)
    uploaded = load_json(UPLOADED_FILE)

    to_upload = {}
    skipped_existing = 0
    skipped_missing_asset = 0
    skipped_no_source = 0

    for key, entry in source.items():
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        if not force and key in uploaded:
            skipped_existing += 1
            continue

        parsed = parse_emoji_literal(entry.get("source"))
        if parsed:
            to_upload[key] = {**entry, "_kind": "cdn", "_parsed": parsed}
            continue

        file_field = entry.get("file")
        if file_field:
            file_path = (ROOT / file_field).resolve()
            if file_path.exists():
                to_upload[key] = {**entry, "_kind": "file", "_resolved_file": str(file_path)}
                continue
            skipped_missing_asset += 1
            continue

        skipped_no_source += 1

    summary = {
        "total_source": len(source),
        "skipped_existing": skipped_existing,
        "skipped_missing_asset": skipped_missing_asset,
        "skipped_no_source": skipped_no_source,
        "uploaded": 0,
        "failed": 0,
    }

    if not to_upload:
        log("[emoji-sync] Up to date - nothing new to upload.")
        return summary

    log(f"[emoji-sync] {len(to_upload)} new emoji(s) found, uploading...")

    if dry_run:
        for key, entry in to_upload.items():
            if entry["_kind"] == "cdn":
                log(f"[emoji-sync]  (dry-run) would upload {key} <- CDN source {entry['_parsed']['id']}")
            else:
                log(f"[emoji-sync]  (dry-run) would upload {key} <- {entry['_resolved_file']}")
        return summary

    token = token or load_token()
    headers = {"Authorization": f"Bot {token}"}
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(headers=headers, timeout=client_timeout) as session:
        app_id = await get_application_id(session)
        for key, entry in to_upload.items():
            if entry["_kind"] == "cdn":
                parsed = entry["_parsed"]
                data_uri = await download_from_cdn(session, parsed["id"], parsed["animated"])
                name, animated = entry.get("name", parsed["name"]), parsed["animated"]
            else:
                data_uri = to_data_uri(Path(entry["_resolved_file"]))
                name, animated = entry.get("name", key.lower()), bool(entry.get("animated"))

            result = await upload_one(session, app_id, key, name, animated, data_uri) if data_uri else None
            if result:
                uploaded[key] = result
                save_json(UPLOADED_FILE, uploaded)
                summary["uploaded"] += 1
            else:
                summary["failed"] += 1
            await asyncio.sleep(0.5)

    log(f"[emoji-sync] Done - {summary['uploaded']} uploaded, {summary['failed']} failed.")
    return summary


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-upload even if already cached")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without uploading")
    args = parser.parse_args()

    summary = await run_sync(force=args.force, dry_run=args.dry_run, quiet=False, timeout=120.0)
    print(f"Source entries: {summary['total_source']}")
    print(f"Already uploaded (skipped, no duplicates): {summary['skipped_existing']}")
    print(f"Local asset missing on disk: {summary['skipped_missing_asset']}")
    print(f"No source/file set (using unicode fallback): {summary['skipped_no_source']}")


if __name__ == "__main__":
    asyncio.run(main())
