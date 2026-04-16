# File: yt_video_multi.py
"""
Multi-channel YouTube uploader/orchestrator with new token scheme (v2).
- Tokens live under ./yt_tokens/
- Unified client secret lives under ./yt_tokens/<client_secret_*.json>
- No legacy abc_* prefixes anywhere.
- Prints  for each successful channel auth.
- Keeps playlists, scheduling, comments, uploads orchestration.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import functools
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import logging
log = logging.getLogger(__name__)
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Any

# --- Third-party (preinstalled per user notes) ---
# google-api-python-client, google-auth-oauthlib, pytz
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore
from googleapiclient.http import MediaFileUpload  # type: ignore

from google.oauth2.credentials import Credentials  # type: ignore
from google.auth.transport.requests import Request  # type: ignore

import pytz
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# ----------------------------
# Configuration & Constants
# ----------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
TOKENS_DIR = PROJECT_ROOT / "yt_tokens"

# Unified client secret inside yt_tokens/ (exact filename per user instruction)
UNIFIED_CLIENT_SECRET = TOKENS_DIR / "client_secret_2_126444884849-ko04quapq11fjdqk82c1i76ai9f7r3u9.apps.googleusercontent.com.json"

# New token filenames (no abc_ prefixes)
TOKEN_MAIN = "main_v2.json"
TOKEN_ACAPELLA = "acapella_v2.json"
TOKEN_DRUMS = "drums_v2.json"
TOKEN_SPLIT = "split_v2.json"
TOKEN_BACKUP = "backup_v2.json"

# Back-compat: this constant is sometimes referenced
MAIN_PLAYLIST_TOKEN = TOKEN_MAIN  # required by user: set to "main_v2.json"

# Channel display names (shown in  prints)
CHANNEL_DISPLAY_BY_TOKEN: Dict[str, str] = {
    TOKEN_ACAPELLA: "Son Got Acapellas",
    TOKEN_DRUMS: "Son Got Drums",
    TOKEN_MAIN: "Main Channel",
    TOKEN_BACKUP: "SGS 2",
    TOKEN_SPLIT: "Sample Split",
}

# Accept channel identifiers used across the pipeline (front-end keys, legacy
# shorthands, and common typos) so callers can override routing without
# remembering the exact token filename or display label.
CHANNEL_KEY_TO_TOKEN: Dict[str, str] = {
    "main_channel": TOKEN_MAIN,
    "main": TOKEN_MAIN,
    "main_chanel": TOKEN_MAIN,  # tolerate legacy typo from previous scripts
    "son_got_acapellas": TOKEN_ACAPELLA,
    "son_got_acappellas": TOKEN_ACAPELLA,
    "acapella_channel": TOKEN_ACAPELLA,
    "son_got_drums": TOKEN_DRUMS,
    "drum_channel": TOKEN_DRUMS,
    "sgs_2": TOKEN_BACKUP,
    "backup_channel": TOKEN_BACKUP,
    "sample_split": TOKEN_SPLIT,
    "split_channel": TOKEN_SPLIT,
    "vocal": TOKEN_MAIN,
}

# Upload map: stem/role -> token filename
UPLOAD_MAP: Dict[str, str] = {
    # TEST: route acapella, instrumental, drums -> MAIN
    "acapella": TOKEN_MAIN,
    "acapellas": TOKEN_MAIN,
    "acappella": TOKEN_MAIN,
    "acappellas": TOKEN_MAIN,
    "vocal": TOKEN_MAIN,
    "vocals": TOKEN_MAIN,

    "instrumental": TOKEN_MAIN,
    "instrumentals": TOKEN_MAIN,

    "drums": TOKEN_MAIN,
    "drum": TOKEN_MAIN,

    # others unchanged
    "main": TOKEN_MAIN,
    "backup": TOKEN_BACKUP,
    "split": TOKEN_SPLIT,
    "melody": TOKEN_SPLIT,
    "sample": TOKEN_SPLIT,
    "samples": TOKEN_SPLIT,
}

# Default metadata fallbacks
DEFAULT_DESCRIPTION = """Access all stems and extracts:
https://songotsamples.com/collections/monthly-pack

Follow backup channels to keep up with other stems and media:
https://www.youtube.com/@Songotsamples2
https://www.youtube.com/@SonGotAcapellas"""

# YouTube limits each individual tag to 30 characters and the combined tag
# string to 500 characters. Enforce both so uploads never fail client-side.
MAX_TAG_LENGTH = 30
MAX_TAGS_TOTAL_LENGTH = 500

DEFAULT_TAGS = [
    "acapella",
    "beatmaker",
    "beats",
    "boombap",
    "drums",
    "extractions",
    "hiphop",
    "instrumentals",
    "rap",
    "samples",
    "sampling",
    "soul",
    "soulsamples",
    "SONGOTSAMPLES",
    "stems",
    "stemseparation",
    "musicproduction",
    "beatmaking",
    "beatmakersamplepack",
    "freestemdownload",
    "freebeats",
    "beatstars",
    "typebeat",
    "oldschoolhiphop",
    "lofi",
    "lofibeats",
    "chopsamples",
]

# YouTube Data API v3 scopes
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtubepartner"]

# Logging
LOG = logging.getLogger("yt_multi")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)

# ----------------------------
# Data Models
# ----------------------------

@dataclass
class VideoJob:
    file: Path
    title: str
    description: str
    tags: List[str]
    category_id: str
    playlist: Optional[str]
    thumbnail: Optional[Path]
    comment: Optional[str]
    privacy_status: str  # "public"|"private"|"unlisted"
    publish_at_rfc3339: Optional[str]  # RFC3339 UTC timestamp
    made_for_kids: bool
    default_language: Optional[str]
    channel_token: str  # token filename (new scheme)
    channel_name: str   # display name


def _post_upload_actions(youtube: Any, job: VideoJob, video_id: str) -> None:
    """Apply thumbnail/playlist/comment side-effects after an upload."""
    if job.thumbnail:
        try:
            set_thumbnail(youtube, video_id, job.thumbnail)
            LOG.info("Thumbnail set.")
        except HttpError as e:
            LOG.warning(f"Unable to set thumbnail: {e}")

    if job.playlist:
        try:
            pid = ensure_playlist(youtube, job.playlist)
            add_to_playlist(youtube, video_id, pid)
            LOG.info(f"Added to playlist '{job.playlist}'.")
        except HttpError as e:
            LOG.warning(f"Unable to add to playlist '{job.playlist}': {e}")

    if job.comment:
        try:
            post_comment(youtube, video_id, job.comment)
            LOG.info("Comment posted.")
        except HttpError as e:
            LOG.warning(f"Unable to post comment: {e}")


# ----------------------------
# Helpers
# ----------------------------

def sanitize_tags(raw_tags):
    """
    Ensure tags are safe for YouTube:
    - all strings
    - no empties
    - each tag max ~60 chars
    - total length safely under 500 chars
    """
    if not raw_tags:
        return None

    cleaned = []
    for t in raw_tags:
        # 1) force string
        t = "" if t is None else str(t)

        # 2) strip whitespace
        t = t.strip()
        if not t:
            continue

        # 3) cap individual tag length (YouTube allows longer, but this is safe)
        t = t[:60]
        cleaned.append(t)

    if not cleaned:
        return None

    # 4) enforce global ~500-char limit (including commas & quotes)
    # YouTube counts commas and "virtual quotes" around tags, so we stay well under.
    final = []
    total = 0
    for tag in cleaned:
        # approximate cost: tag length + 3 (comma + 2 quotes)
        cost = len(tag) + 3
        if total + cost > 460:  # stay comfortably under 500
            break
        final.append(tag)
        total += cost

    return final or None


def _fail(msg: str, code: int = 2) -> None:
    LOG.error(msg)
    sys.exit(code)


def rfc3339_from_local(ts: str, tz_name: str = "America/Chicago") -> str:
    """
    Convert 'YYYY-MM-DD HH:MM' (local) to RFC3339 UTC.
    If ts already RFC3339, return as-is.
    """
    ts = ts.strip()
    if "T" in ts and ts.endswith("Z"):
        return ts
    local = pytz.timezone(tz_name)
    naive = dt.datetime.strptime(ts, "%Y-%m-%d %H:%M")
    localized = local.localize(naive)
    utc_dt = localized.astimezone(pytz.UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_title(s: str, limit: int = 100) -> str:
    return s.strip()[:limit]

def format_bpm_label(bpm):
    """
    Converts BPM to half-time (BPM ÷ 2).
    Odd BPMs → .5; even BPMs stay whole.
    Example: 161 → 80.5 | 162 → 81
    """
    half = bpm / 2
    if half.is_integer():
        return str(int(half))
    else:
        return f"{half:.1f}".rstrip("0").rstrip(".")


def safe_description(s: str, limit: int = 5000) -> str:
    return s.strip()[:limit]


def parse_tags(tags_raw: Optional[str]) -> List[str]:
    if not tags_raw:
        return []
    # Accept comma or semicolon separated
    parts = [t.strip() for t in tags_raw.replace(";", ",").split(",")]
    return [p for p in parts if p]

import re
import unicodedata

def clean_tag(t: str) -> str:
    """Return a fully YouTube-safe ASCII keyword tag."""
    if not t:
        return ""

    # Always treat as string and strip
    t = str(t).strip()

    # Normalize text so accents/emojis become ASCII or vanish
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()

    # Replace music symbols with ASCII-safe versions
    t = t.replace("♯", "#").replace("♭", "b")

    # Remove illegal characters (keep letters, numbers, spaces, and #)
    t = re.sub(r"[^A-Za-z0-9 #]", " ", t)

    # Collapse extra whitespace
    t = re.sub(r"\s+", " ", t).strip()

    # 🔒 Hard cap per-tag length so artist+title tags can't be insane
    if len(t) > MAX_TAG_LENGTH:
        t = t[:MAX_TAG_LENGTH].rstrip()

        t = t.strip()

    # Enforce YouTube's 30 character per-tag limit to avoid client-side errors
    if len(t) > MAX_TAG_LENGTH:
        t = t[:MAX_TAG_LENGTH].strip()

    return t


def _trim_tags_to_limit(values: Iterable[str], limit: int = MAX_TAGS_TOTAL_LENGTH) -> List[str]:
    total = 0
    trimmed: List[str] = []
    for tag in values:
        if not tag:
            continue
        prospective = total + (1 if trimmed else 0) + len(tag)
        if prospective > limit:
            break
        trimmed.append(tag)
        total = prospective
    return trimmed

def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result

def normalize_tags(tags: Optional[Iterable[str] | str]) -> List[str]:
    """Return a cleaned list of tags that respect YouTube's 500 char limit."""
    if tags is None:
        cleaned = list(DEFAULT_TAGS)
    elif isinstance(tags, str):
        cleaned = parse_tags(tags)
    else:
        cleaned = [str(t).strip() for t in tags if str(t).strip()]

    # NEW: sanitize every tag using clean_tag()
    cleaned = [clean_tag(t) for t in cleaned]
    cleaned = [t for t in cleaned if t]   # remove empty results

    cleaned = _dedupe_preserve_order(cleaned)

    trimmed = _trim_tags_to_limit(cleaned)
    if not trimmed and cleaned:
        # Always return at least one tag if provided but all were over limit individually
        trimmed = [cleaned[0][:MAX_TAGS_TOTAL_LENGTH]]

    if len(trimmed) < len(cleaned):
        log.debug("Tags trimmed to satisfy length limit (%s chars)", MAX_TAGS_TOTAL_LENGTH)

    return trimmed


def read_text(path_or_none: Optional[str]) -> str:
    if not path_or_none:
        return ""
    p = Path(path_or_none)
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        _fail(f"Cannot read description file '{p}': {e}")
    return ""


def sha1_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def resolve_description(
    *,
    description: str,
    description_file: Optional[str],
    fallback_file: Path,
) -> str:
    """Pick the best description, honouring optional file overrides."""
    chosen = description.strip()
    if description_file and not chosen:
        chosen = read_text(description_file).strip()
    if not chosen and fallback_file.exists():
        stem_text = fallback_file.stem.replace("_", " ")
        stem_text = re.sub(r"\s+", " ", stem_text).strip()
        chosen = f"{stem_text}\n\n#sha1:{sha1_file(fallback_file)}"
    if not chosen:
        chosen = DEFAULT_DESCRIPTION
    return safe_description(chosen)


def backoff(retries: int = 6, base: float = 1.2, cap: float = 30.0):
    """
    Decorator: exponential backoff on HttpError/quota/rate errors.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = 1.0
            for attempt in range(retries):
                try:
                    return fn(*args, **kwargs)
                except HttpError as e:
                    status = getattr(e, "status_code", None) or getattr(e, "resp", {}).status if hasattr(e, "resp") else None
                    reason = ""
                    try:
                        reason = json.loads(e.content.decode("utf-8")).get("error", {}).get("errors", [{}])[0].get("reason", "")
                    except Exception:
                        pass
                    transient = status in (429, 500, 502, 503, 504) or reason in (
                        "quotaExceeded",
                        "userRateLimitExceeded",
                        "rateLimitExceeded",
                        "backendError",
                        "internalError",
                    )
                    if not transient or attempt == retries - 1:
                        raise
                    LOG.warning(f"Transient API error ({status} {reason}). Retrying in {delay:.1f}s...")
                    time.sleep(min(delay, cap))
                    delay *= base
        return wrapper
    return deco


# ----------------------------
# Auth
# ----------------------------

def _token_path(filename: str) -> Path:
    return TOKENS_DIR / filename


def _assert_paths() -> None:
    if not TOKENS_DIR.exists():
        _fail(f"Tokens directory not found: {TOKENS_DIR}")
    if not UNIFIED_CLIENT_SECRET.exists():
        _fail(f"Unified client secret not found: {UNIFIED_CLIENT_SECRET}")


def _load_credentials(token_file: str) -> Credentials:
    """
    Load authorized-user credentials JSON from yt_tokens/.
    Refresh if expired and refresh_token available.
    """
    token_path = _token_path(token_file)
    if not token_path.exists():
        _fail(f"Token JSON not found: {token_path}")
    creds = Credentials.from_authorized_user_file(str(token_path), scopes=SCOPES)
    # Refresh if needed
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Persist refreshed creds back to file
            token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception as e:
            _fail(f"Failed to refresh credentials for {token_file}: {e}")
    return creds


def get_youtube_client(token_file: str) -> Any:
    """
    Build youtube client for given token file.
    """
    creds = _load_credentials(token_file)
    try:
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        _fail(f"Failed to build YouTube client for {token_file}: {e}")
    # Print confirmation per user requirement
    channel_name = CHANNEL_DISPLAY_BY_TOKEN.get(token_file, token_file)
    print(f" Authenticated YouTube client for {channel_name}")
    return yt


# ----------------------------
# YouTube Operations
# ----------------------------

@backoff()
def ensure_playlist(youtube: Any, title: str) -> str:
    # Try to find existing
    req = youtube.playlists().list(part="id,snippet", mine=True, maxResults=50)
    while req is not None:
        resp = req.execute()
        for item in resp.get("items", []):
            if item["snippet"]["title"].strip().lower() == title.strip().lower():
                return item["id"]
        req = youtube.playlists().list_next(req, resp)
    # Create new
    create = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": f"Auto-created playlist: {title}"},
            "status": {"privacyStatus": "public"},
        },
    )
    result = create.execute()
    return result["id"]


@backoff()
def add_to_playlist(youtube: Any, video_id: str, playlist_id: str) -> str:
    resp = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()
    return resp["id"]


@backoff()
def post_comment(youtube: Any, video_id: str, text: str) -> str:
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {"snippet": {"textOriginal": text}},
        }
    }
    resp = youtube.commentThreads().insert(part="snippet", body=body).execute()
    return resp["id"]


@backoff()
def set_thumbnail(youtube: Any, video_id: str, thumbnail_path: Path) -> dict:
    media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
    return youtube.thumbnails().set(videoId=video_id, media_body=media).execute()


@backoff()
def upload_video(
    youtube: Any,
    file_path: Path,
    title: str,
    description: str,
    tags: List[str],
    category_id: str,
    privacy_status: str,
    publish_at_rfc3339: Optional[str],
    made_for_kids: bool,
    default_language: Optional[str],
) -> Tuple[str, dict]:
    """
    Uploads a video and returns (video_id, response).
    If publish_at_rfc3339 is provided with privacy=private, YouTube will schedule publish time.
    """
    body: Dict[str, Any] = {
        "snippet": {
            "title": safe_title(title),
            "description": safe_description(description),
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    if default_language:
        body["snippet"]["defaultLanguage"] = default_language

    # tags (normalize first if you still want that logic)
    safe_tags = sanitize_tags(tags)  # or sanitize_tags(normalize_tags(tags))

    if safe_tags:
        body["snippet"]["tags"] = safe_tags


    if publish_at_rfc3339:
        # YouTube requires privacyStatus=private for scheduling
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at_rfc3339

    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    attempt = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            attempt += 1
            if status:
                LOG.info(f"Upload progress: {int(status.progress() * 100)}%")
        except HttpError as e:
            # backoff decorator will handle transients; re-raise
            raise
        except Exception as e:
            if attempt > 5:
                raise
            LOG.warning(f"Resumable upload hiccup ({e}); retrying chunk...")
            time.sleep(2.0)

    video_id = response["id"]
    return video_id, response


_UPLOAD_VIDEO_FN = upload_video


# ----------------------------
# Orchestration
# ----------------------------

def resolve_channel(stem: Optional[str], explicit_channel: Optional[str]) -> Tuple[str, str]:
    """
    Returns (token_filename, channel_display_name).
    """
    if explicit_channel:
        normalized = explicit_channel.strip().lower()

        # Allow passing the canonical display name
        for token, name in CHANNEL_DISPLAY_BY_TOKEN.items():
            if normalized == name.strip().lower():
                return token, name

        # Allow direct token filenames
        if explicit_channel in CHANNEL_DISPLAY_BY_TOKEN:
            return explicit_channel, CHANNEL_DISPLAY_BY_TOKEN[explicit_channel]

        # Accept pipeline channel keys and common aliases/typos
        token = CHANNEL_KEY_TO_TOKEN.get(normalized)
        if token:
            return token, CHANNEL_DISPLAY_BY_TOKEN[token]

        valid = sorted({
            *CHANNEL_DISPLAY_BY_TOKEN.values(),
            *CHANNEL_KEY_TO_TOKEN.keys(),
            *CHANNEL_DISPLAY_BY_TOKEN.keys(),
        })
        _fail(f"Unknown channel '{explicit_channel}'. Valid options: {valid}")
    if not stem:
        # Default to main
        token = TOKEN_MAIN
        return token, CHANNEL_DISPLAY_BY_TOKEN[token]
    key = stem.strip().lower()
    token = UPLOAD_MAP.get(key)
    if not token:
        _fail(f"Unknown stem '{stem}'. Valid stems: {sorted(set(UPLOAD_MAP.keys()))}")
    return token, CHANNEL_DISPLAY_BY_TOKEN[token]


def build_job_from_args(args: argparse.Namespace) -> VideoJob:
    """Construct a :class:`VideoJob` from parsed CLI/namespace arguments."""

    file_path = Path(args.file).expanduser()
    token, channel_name = resolve_channel(args.stem, args.channel)
    publish_at = rfc3339_from_local(args.publish_at, tz_name=args.tz) if args.publish_at else None

    description = resolve_description(
        description=args.description or "",
        description_file=getattr(args, "description_file", None),
        fallback_file=file_path,
    )

    tags = normalize_tags(getattr(args, "tags", None))

    title = safe_title(args.title or file_path.stem)

    return VideoJob(
        file=file_path,
        title=title,
        description=description,
        tags=tags,
        category_id=args.category_id,
        playlist=args.playlist,
        thumbnail=args.thumbnail,
        comment=args.comment,
        privacy_status=args.privacy,
        publish_at_rfc3339=publish_at,
        made_for_kids=args.made_for_kids,
        default_language=args.lang,
        channel_token=token,
        channel_name=channel_name,
    )



def run_single(job: VideoJob, dry_run: bool = False) -> str:
    yt = get_youtube_client(job.channel_token)
    if dry_run:
        LOG.info(f"[DRY-RUN] Would upload to {job.channel_name}: {job.file.name}")
        if job.playlist:
            LOG.info(f"[DRY-RUN] Would ensure playlist: {job.playlist}")
        return "DRY_RUN"

    video_id, _resp = upload_video(
        youtube=yt,
        file_path=job.file,
        title=job.title,
        description=job.description,
        tags=job.tags,
        category_id=job.category_id,
        privacy_status=job.privacy_status,
        publish_at_rfc3339=job.publish_at_rfc3339,
        made_for_kids=job.made_for_kids,
        default_language=job.default_language,
    )
    LOG.info(f"Uploaded video: https://youtu.be/{video_id}")
    _post_upload_actions(yt, job, video_id)
    return video_id


class YouTubeUploader:
    """Small wrapper for legacy callers that only need single-channel uploads."""

    def __init__(
        self,
        *,
        default_stem: Optional[str] = "main",
        default_channel: Optional[str] = None,
    ) -> None:
        self._default_stem = default_stem
        self._default_channel = default_channel
        self._cached_token: Optional[str] = None
        self._cached_channel_name: Optional[str] = None
        self._client: Optional[Any] = None

    def _resolve(self, stem: Optional[str], channel: Optional[str]) -> Tuple[str, str]:
        effective_stem = stem if stem is not None else self._default_stem
        effective_channel = channel if channel is not None else self._default_channel
        return resolve_channel(effective_stem, effective_channel)

    def upload_video(
        self,
        *,
        file_path: str | Path,
        title: str,
        description: str = "",
        tags: Optional[Iterable[str] | str] = None,
        category_id: str = "10",
        playlist: Optional[str] = None,
        privacy_status: str = "private",
        publish_at: Optional[str] = None,
        tz: str = "America/Chicago",
        made_for_kids: bool = False,
        lang: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        comment: Optional[str] = None,
        dry_run: bool = False,
        stem: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> str:
        token, channel_name = self._resolve(stem, channel)

        file = Path(file_path).expanduser()
        if not file.exists():
            raise FileNotFoundError(f"Video file not found: {file}")

        publish_rfc3339 = rfc3339_from_local(publish_at, tz) if publish_at else None
        resolved_description = resolve_description(
            description=description or "",
            description_file=None,
            fallback_file=file,
        )
        resolved_tags = normalize_tags(tags)

        thumb: Optional[Path] = None
        if thumbnail_path:
            candidate = Path(thumbnail_path).expanduser()
            if candidate.exists():
                thumb = candidate

        job = VideoJob(
            file=file,
            title=safe_title(title or file.stem),
            description=resolved_description,
            tags=resolved_tags,
            category_id=category_id,
            playlist=playlist,
            thumbnail=thumb,
            comment=comment,
            privacy_status=privacy_status,
            publish_at_rfc3339=publish_rfc3339,
            made_for_kids=made_for_kids,
            default_language=lang,
            channel_token=token,
            channel_name=channel_name,
        )

        if dry_run:
            get_youtube_client(token)
            LOG.info(f"[DRY-RUN] Would upload to {channel_name}: {file.name}")
            if playlist:
                LOG.info(f"[DRY-RUN] Would ensure playlist: {playlist}")
            return "DRY_RUN"

        if self._client is None or self._cached_token != token:
            self._client = get_youtube_client(token)
            self._cached_token = token
            self._cached_channel_name = channel_name

        video_id, _ = _UPLOAD_VIDEO_FN(
            youtube=self._client,
            file_path=job.file,
            title=job.title,
            description=job.description,
            tags=job.tags,
            category_id=job.category_id,
            privacy_status=job.privacy_status,
            publish_at_rfc3339=job.publish_at_rfc3339,
            made_for_kids=job.made_for_kids,
            default_language=job.default_language,
        )
        LOG.info(f"Uploaded video: https://youtu.be/{video_id}")
        _post_upload_actions(self._client, job, video_id)
        return video_id


def read_batch(path: Path) -> List[VideoJob]:
    """
    Accept CSV or JSONL with columns/fields:
    file, title, description, tags, category_id, playlist, thumbnail, comment,
    privacy, publish_at, made_for_kids, lang, stem, channel
    """
    jobs: List[VideoJob] = []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                ns = argparse.Namespace(
                    file=Path(row["file"]).expanduser(),
                    title=row.get("title") or "",
                    description=row.get("description") or "",
                    description_file=None,
                    tags=row.get("tags") or "",
                    category_id=row.get("category_id") or "10",
                    playlist=row.get("playlist") or None,
                    thumbnail=Path(row["thumbnail"]).expanduser() if row.get("thumbnail") else None,
                    comment=row.get("comment") or None,
                    privacy=row.get("privacy") or "private",
                    publish_at=row.get("publish_at") or None,
                    tz=row.get("tz") or "America/Chicago",
                    made_for_kids=(row.get("made_for_kids") or "").strip().lower() in ("1", "true", "yes"),
                    lang=row.get("lang") or None,
                    stem=row.get("stem") or None,
                    channel=row.get("channel") or None,
                )
                jobs.append(build_job_from_args(ns))
    else:
        # JSONL
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                ns = argparse.Namespace(
                    file=Path(obj["file"]).expanduser(),
                    title=obj.get("title") or "",
                    description=obj.get("description") or "",
                    description_file=None,
                    tags=obj.get("tags") or "",
                    category_id=obj.get("category_id") or "10",
                    playlist=obj.get("playlist"),
                    thumbnail=Path(obj["thumbnail"]).expanduser() if obj.get("thumbnail") else None,
                    comment=obj.get("comment"),
                    privacy=obj.get("privacy") or "private",
                    publish_at=obj.get("publish_at"),
                    tz=obj.get("tz") or "America/Chicago",
                    made_for_kids=bool(obj.get("made_for_kids", False)),
                    lang=obj.get("lang"),
                    stem=obj.get("stem"),
                    channel=obj.get("channel"),
                )
                jobs.append(build_job_from_args(ns))
    return jobs


def run_batch(jobs: List[VideoJob], dry_run: bool = False) -> List[str]:
    """
    Greedy per-channel execution to reuse clients.
    """
    # Group by token
    by_token: Dict[str, List[VideoJob]] = {}
    for j in jobs:
        by_token.setdefault(j.channel_token, []).append(j)

    results: List[str] = []
    for token, group in by_token.items():
        yt = get_youtube_client(token)
        for job in group:
            if dry_run:
                LOG.info(f"[DRY-RUN] Would upload to {job.channel_name}: {job.file.name}")
                if job.playlist:
                    LOG.info(f"[DRY-RUN] Would ensure playlist: {job.playlist}")
                results.append("DRY_RUN")
                continue
            vid, _ = upload_video(
                youtube=yt,
                file_path=job.file,
                title=job.title,
                description=job.description,
                tags=job.tags,
                category_id=job.category_id,
                privacy_status=job.privacy_status,
                publish_at_rfc3339=job.publish_at_rfc3339,
                made_for_kids=job.made_for_kids,
                default_language=job.default_language,
            )
            LOG.info(f"Uploaded: https://youtu.be/{vid} ({job.channel_name})")
            _post_upload_actions(yt, job, vid)
            results.append(vid)

    return results


# ----------------------------
# CLI
# ----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Multi-channel YouTube uploader (new v2 tokens + unified client secret)."
    )
    p.add_argument("--file", type=Path, help="Video file to upload")
    p.add_argument("--title", type=str, default="")
    p.add_argument("--description", type=str, default="")
    p.add_argument("--description-file", type=str, help="Path to description .txt", default=None)
    p.add_argument("--tags", type=str, default="", help="Comma/semicolon-separated tags")
    p.add_argument("--category-id", type=str, default="10", help="YouTube category ID (default Music=10)")
    p.add_argument("--playlist", type=str, default=None, help="Ensure+attach to playlist title")
    p.add_argument("--thumbnail", type=Path, default=None)
    p.add_argument("--comment", type=str, default=None)

    p.add_argument("--privacy", type=str, default="private", choices=["public", "private", "unlisted"])
    p.add_argument("--publish-at", type=str, default=None, help="Local 'YYYY-MM-DD HH:MM' or RFC3339Z")
    p.add_argument("--tz", type=str, default="America/Chicago", help="Local timezone for --publish-at")

    p.add_argument("--made-for-kids", action="store_true", help="Mark as made for kids")
    p.add_argument("--lang", type=str, default=None, help="Default language code, e.g., en")

    # Channel routing
    p.add_argument("--stem", type=str, default=None, help="acapella, drums, split, backup, main, etc.")
    p.add_argument("--channel", type=str, default=None, help="Override: channel display name or token filename")

    # Batch
    p.add_argument("--batch-file", type=Path, default=None, help="CSV or JSONL for batch uploads")

    # Modes
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--preflight", action="store_true", help="Print channel↔token mapping and exit")

    return p


def preflight() -> None:
    _assert_paths()
    print("Detected tokens and channel mapping:")
    for token, name in CHANNEL_DISPLAY_BY_TOKEN.items():
        path = _token_path(token)
        print(f" - {name:20s} -> {token}  {'OK' if path.exists() else 'MISSING'}")
    print(f"Unified client secret: {UNIFIED_CLIENT_SECRET.name}  {'OK' if UNIFIED_CLIENT_SECRET.exists() else 'MISSING'}")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    _assert_paths()

    if args.preflight:
        preflight()
        return 0

    if args.batch_file:
        jobs = read_batch(args.batch_file)
        if not jobs:
            _fail("Batch file parsed but produced 0 jobs.")
        LOG.info(f"Prepared {len(jobs)} jobs from {args.batch_file.name}")
        run_batch(jobs, dry_run=args.dry_run)
        return 0

    if not args.file:
        _fail("--file is required (or use --batch-file).")
    if not args.file.exists():
        _fail(f"Video file not found: {args.file}")

    job = build_job_from_args(args)
    run_single(job, dry_run=args.dry_run)
    return 0
# ----------------------------
# Back-compat wrappers expected by pipeline
# ----------------------------

# --- replace the upload_one signature with this (adds **_unused) ---
def upload_one(
    file_path: str,
    *,
    stem: str,
    title: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    category_id: str = "10",
    playlist: Optional[str] = None,
    privacy: str = "private",
    publish_at: Optional[str] = None,
    tz: str = "America/Chicago",
    made_for_kids: bool = False,
    lang: Optional[str] = None,
    thumbnail: Optional[str] = None,
    comment: Optional[str] = None,
    dry_run: bool = False,
    channel: Optional[str] = None,
    **_unused,  # absorb unknown extras passed by pipeline
) -> str:
    """Minimal wrapper for single upload used by some pipelines."""
    args = argparse.Namespace(
        file=Path(file_path).expanduser(),
        title=title,
        description=description,
        description_file=None,
        tags=",".join(tags or []) if isinstance(tags, list) else (tags or ""),
        category_id=category_id,
        playlist=playlist,
        thumbnail=Path(thumbnail).expanduser() if thumbnail else None,
        comment=comment,
        privacy=privacy,
        publish_at=publish_at,
        tz=tz,
        made_for_kids=made_for_kids,
        lang=lang,
        stem=stem,
        channel=channel,
    )
    job = build_job_from_args(args)
    return run_single(job, dry_run=dry_run)


# --- fix the typo: change `ddef` to `def` exactly here ---
def upload_all_stems(
    stem_files: Dict[str, str],
    *,
    title_map: Optional[Dict[str, str]] = None,
    description: str = "",
    tags: Optional[List[str]] = None,
    category_id: str = "10",
    playlist: Optional[str] = None,
    privacy: str = "private",
    publish_at: Optional[str] = None,
    tz: str = "America/Chicago",
    made_for_kids: bool = False,
    lang: Optional[str] = None,
    thumbnail_map: Optional[Dict[str, str]] = None,
    comment: Optional[str] = None,
    dry_run: bool = False,
    channel_override: Optional[str] = None,
    artist_file_map: Optional[Dict[str, str]] = None,  # accepted, ignored
    **_unused,  # absorb any future extras without breaking
) -> Dict[str, str]:
    """Back-compat batch API expected by content_base/dispatch_download.

    Args:
        stem_files: {"acapella": "/path/a.mp4", "drums": "/path/b.mp4", ...}
        title_map: Optional titles per stem.
        thumbnail_map: Optional thumbnails per stem.
        channel_override: Force all stems to that channel/display-name or token filename.
        artist_file_map: Present in caller; ignored here.

    Returns:
        {stem: video_id or "DRY_RUN"}.
    """
    _assert_paths()

    # build jobs
    jobs: List[VideoJob] = []
    for stem, fpath in stem_files.items():
        f = Path(fpath).expanduser()
        if not f.exists():
            raise FileNotFoundError(f"Video file not found for stem '{stem}': {f}")

        # choose channel: explicit override or routing via UPLOAD_MAP
        token, channel_name = resolve_channel(stem, channel_override)

        title = safe_title((title_map or {}).get(stem) or f.stem)

        thumb = None
        if thumbnail_map and stem in thumbnail_map and thumbnail_map[stem]:
            thumb_candidate = Path(thumbnail_map[stem]).expanduser()
            thumb = thumb_candidate if thumb_candidate.exists() else None

        publish_rfc3339 = rfc3339_from_local(publish_at, tz) if publish_at else None

        job_description = resolve_description(
            description=description or "",
            description_file=None,
            fallback_file=f,
        )
        job_tags = normalize_tags(tags)

        # Auto-generate comment if not provided
        # Comment template based on stem title and type
        auto_comment = None
        if not comment:
            # Extract stem type from title (e.g., "Acapella", "Drums", etc.)
            stem_type_match = None
            for stem_type in ["Acapella", "Drums", "Bass", "Melody", "Instrumental"]:
                if stem_type in title:
                    stem_type_match = stem_type
                    break
            
            if stem_type_match:
                # Generate comment template
                auto_comment = f"""🎧 New {title} just dropped — like, comment your remix, and subscribe!

Access all stems & extracts:

https://songotsamples.com/collections/monthly-pack

Follow all our channels to keep up with new uploads:

Main: https://www.youtube.com/@songotsamples

Backup: https://www.youtube.com/@Songotsamples2

Acapellas: https://www.youtube.com/@SonGotAcapellas

Drums: https://www.youtube.com/@SonGotDrums

Sample Split: https://www.youtube.com/@samplesplit"""
        
        job = VideoJob(
            file=f,
            title=title,
            description=job_description,
            tags=job_tags,
            category_id=category_id,
            playlist=playlist,
            thumbnail=thumb,
            comment=comment or auto_comment,  # Use provided comment or auto-generated
            privacy_status=privacy,
            publish_at_rfc3339=publish_rfc3339,
            made_for_kids=made_for_kids,
            default_language=lang,
            channel_token=token,
            channel_name=channel_name,
        )
        jobs.append(job)

    # execute grouped by channel (reuses clients)
    results: Dict[str, str] = {}
    if dry_run:
        for j in jobs:
            get_youtube_client(j.channel_token)  # prints  per-channel even in dry-run
            LOG.info(f"[DRY-RUN] Would upload to {j.channel_name}: {j.file.name}")
            if j.playlist:
                LOG.info(f"[DRY-RUN] Would ensure playlist: {j.playlist}")
            results[[k for k, v in stem_files.items() if Path(v).resolve() == j.file.resolve()][0]] = "DRY_RUN"
        return results

    by_token: Dict[str, List[VideoJob]] = {}
    for j in jobs:
        by_token.setdefault(j.channel_token, []).append(j)

    for token, group in by_token.items():
        yt = get_youtube_client(token)
        for j in group:
            vid, _ = upload_video(
                youtube=yt,
                file_path=j.file,
                title=j.title,
                description=j.description,
                tags=j.tags,
                category_id=j.category_id,
                privacy_status=j.privacy_status,
                publish_at_rfc3339=j.publish_at_rfc3339,
                made_for_kids=j.made_for_kids,
                default_language=j.default_language,
            )
            LOG.info(f"Uploaded: https://youtu.be/{vid} ({j.channel_name})")
            _post_upload_actions(yt, j, vid)

            stem_key = next((k for k, v in stem_files.items() if Path(v).resolve() == j.file.resolve()), None)
            if stem_key:
                results[stem_key] = vid

    return results


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)