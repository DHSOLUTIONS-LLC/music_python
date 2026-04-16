# content_base.py
# Clean rebuild — ISRC-based strict Topic search + existing progress/upload logic

import os
import re
import json
import time
import requests
from typing import Optional

from yt_dlp import YoutubeDL
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

try:
    from upload_ec2 import Uploader
except ModuleNotFoundError:
    Uploader = None

from shared_state import get_progress, set_progress
from dotenv import load_dotenv
from yt_video_multi import upload_all_stems
from concurrent.futures import ThreadPoolExecutor

#  Channel name map (maps channel keys to display names for folder structure)
CHANNEL_NAME_MAP = {
    "main_channel": "Main",
    "sgs_2": "SGS 2",
    "son_got_drums": "Drum",
    "son_got_acapellas": "Acappella",
    "sample_split": "Sample Split",
    "tiktok_channel": "Tik Tok",
    "web_library": "Web Library",
}

load_dotenv()

#  Simplified YouTube auth setup
YT_TOKEN_PATH = os.path.join("yt_tokens", "main_v2.json")
CLIENT_SECRETS_PATH = YT_TOKEN_PATH  # Same file used for both client secret and refresh token

# --- Default YouTube metadata constants ---
DEFAULT_DESCRIPTION = (
    "Access all stems and extracts https://songotsamples.com/collections/monthly-pack\n\n"
    "Follow backup channels to keep up with other stems and media.\n"
    "https://www.youtube.com/@Songotsamples2  https://www.youtube.com/@SonGotAcapellas"
)

DEFAULT_TAGS = [
    "acapella", "beatmaker", "beats", "boombap", "drums", "extractions",
    "hiphop", "instrumentals", "rap", "samples", "sampling", "soul",
    "soulsamples", "songotsamples", "stems", "stemseparation",
    "musicproduction", "beatmaking", "samplepack", "producercommunity",
    "oldschoolhiphop", "lofibeats", "vinylsamples", "soulfulbeats",
    "undergroundhiphop", "sampleflip", "remix", "drumbreaks",
    "drumloops", "melodystems", "isolatedvocals", "mixing", "mastering",
    "audioengineering", "producerlife", "beatstars", "freestems",
    "typebeat", "boombapbeats", "soulfulhiphop", "lofivibes"
]

GENRE_SLUG_MAP = {
    "hiphop": "Hip-Hop",
    "hip-hop": "Hip-Hop",
    "rnb": "R&B",
    "r&b": "R&B",
    "jazz": "Jazz",
    "soul": "Soul",
    "rock": "Rock",
    "pop": "Pop",
    "electronic": "Electronic",
    "world": "World",
    "other": "Other",
}


def normalize_genre(value: Optional[str], default: str = "Other") -> str:
    if not value:
        return default
    key = value.strip()
    if not key:
        return default
    lookup = GENRE_SLUG_MAP.get(key.lower())
    if lookup:
        return lookup
    return key.title()


def format_bpm_label(bpm) -> str:
    """
    Half-time rule (only if BPM ≥ 140):
      - if even → bpm / 2  (e.g. 160 → 80)
      - if odd  → bpm / 2 with .5 (e.g. 163 → 81.5)
      - if bpm < 140 → keep original value
    """
    try:
        n = int(round(float(bpm)))
        if n >= 140:
            if n % 2:     # odd BPM
                return f"{n/2:.1f}"
            return str(n // 2)
        return str(n)
    except Exception:
        return str(bpm)


class ContentBase:
    def __init__(self, args: dict, track_info: dict = None):
        self.args = args or {}
        self.session_id = self.args.get("session_id", "default")
        self.track_info = track_info or self.args.get("track_info") or {}
        self.channel_key = self.args.get("channel")
        self.channel_label = CHANNEL_NAME_MAP.get(self.channel_key, self.channel_key)
        self.trim_track = self.args.get("trim_track", False)
        self.trim_length = self.args.get("trim_length", 72)

        self.universal_id = self.args.get("universal_id")
        # Use htdemucs_ft (high-quality) as default stem path
        self.stem_base_path = self.args.get("stem_base_path") or (
            os.path.join("Separated", "htdemucs_ft", self.universal_id) if self.universal_id else ""
        )

        self.selected_genre = normalize_genre(self.args.get("genre"))
        self.genre_folder = self._sanitize_folder_name(self.selected_genre)
        self.video_paths = {}

        print(f"\n ContentBase initialized with session_id: {self.session_id}")
        print(f" Received BPM: {self.args.get('bpm')} | Key: {self.args.get('key')}")
        print(f" Track info present: {'Yes' if self.track_info else 'No'}\n")

        self.CLIENT_ID = self.args.get("client_id") or os.getenv("SPOTIFY_CLIENT_ID")
        self.CLIENT_SECRET = self.args.get("client_secret") or os.getenv("SPOTIFY_CLIENT_SECRET")

        if not self.CLIENT_ID or not self.CLIENT_SECRET:
            raise ValueError("Spotify credentials missing: provide client_id and client_secret")

        self.sp = Spotify(auth_manager=SpotifyClientCredentials(
            client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET
        ))

    # -----------------------------------------------------------
    # Basic helpers
    # -----------------------------------------------------------
    def get_stem_path(self, stem_name: str) -> str:
        return os.path.join(self.stem_base_path, f"{stem_name}.mp3") if self.stem_base_path else ""

    def _sanitize_folder_name(self, value: Optional[str], fallback: str = "General") -> str:
        cleaned = self.sanitize_name(value or "")
        return cleaned if cleaned else fallback

    def sanitize_name(self, name: str) -> str:
        cleaned = re.sub(r"[\\/:*?\"<>|]+", " ", name or "")
        cleaned = re.sub(r"[_-]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        return cleaned or "Untitled"

    # -----------------------------------------------------------
    # Progress helpers (unchanged)
    # -----------------------------------------------------------
    def build_meta(self, stem_type: str, channel: str, track: dict) -> dict:
        return {
            "track_id": track.get("id"),
            "stem": stem_type.lower() if stem_type else None,
            "channel": channel,
            "artist": track.get("artist"),
            "title": track.get("name"),
            "bpm": int(track.get("tempo", 0)),
            "key": track.get("key"),
        }

    def update_progress(self, message: str, metadata: dict = None, step_percent: float = None):
        current = get_progress(self.session_id)
        meta = current.get("meta", {}) if current else {}
        percent = current.get("percent", 0) if current else 0

        if step_percent is not None:
            percent = max(percent, min(100, step_percent))

        enriched_meta = {
            "stem": meta.get("stem"),
            "channel": meta.get("channel"),
            "artist": meta.get("artist"),
            "track": meta.get("track"),
            "bpm": meta.get("bpm"),
            "key": meta.get("key"),
            "title": meta.get("title"),
            **(metadata or {})
        }

        set_progress(self.session_id, {
            "message": message,
            "percent": percent,
            "meta": enriched_meta
        })
        print(f"[UPDATE] {self.session_id} → {message} ({percent}%)")

    def mark_step_complete(self, message: str, extra_meta: dict = None):
        progress = get_progress(self.session_id)
        if not progress:
            return

        meta = progress.get("meta", {})
        completed = meta.get("completed", 0) + 1
        total = meta.get("total", 1)
        percent = int((completed / total) * 100)

        enriched_meta = {
            "completed": completed,
            "total": total,
            "stem": meta.get("stem"),
            "channel": meta.get("channel"),
            "artist": meta.get("artist"),
            "track": meta.get("track"),
            "bpm": meta.get("bpm"),
            "key": meta.get("key"),
            "title": meta.get("title"),
            **(extra_meta or {})
        }

        set_progress(self.session_id, {
            "message": message,
            "percent": percent,
            "meta": enriched_meta
        })
        print(f"[DONE] {self.session_id}: {percent}% ({completed}/{total}) → {message}")

    def progress_with_meta(self, message: str, step: int, total: int, stem: str, channel: str, track: dict):
        meta = self.build_meta(stem, channel, track)
        percent = int(step / total * 100)
        self.update_progress(message, meta, percent)

    def fail_progress_with_meta(self, message: str, stem: str, channel: str, track: dict):
        meta = self.build_meta(stem, channel, track)
        self.update_progress(message, meta)

    def mark_complete_with_meta(self, message: str, stem: str, channel: str, track: dict):
        meta = self.build_meta(stem, channel, track)
        self.mark_step_complete(message, meta)

    # -----------------------------------------------------------
    # Upload helpers (unchanged)
    # -----------------------------------------------------------
    def upload_batch_to_youtube(self, track):
        try:
            artist = track.get("artist")
            title = track.get("name")
            key = track.get("key")
            bpm = track.get("tempo")
            bpm_str = format_bpm_label(bpm)

            # Build titles for each stem type
            title_map = {}
            key_text = str(key).strip() if key else ""
            for stem_type in self.video_paths.keys():
                display_stem = stem_type.replace("_", " ").title()
                bracket_parts = [f"{bpm_str} BPM"]
                if stem_type.lower() != "drums" and key_text:
                    bracket_parts.append(key_text)
                bracket = f"[{' '.join(part for part in bracket_parts if part)}]"
                title_parts = [artist, title, display_stem, bracket]
                yt_title = " ".join(part for part in title_parts if part)
                title_map[stem_type] = yt_title

            self.update_progress("📤 Uploading all stems to YouTube...", {"artist": artist})

            upload_all_stems(
                stem_files=self.video_paths,         # stem_type -> mp4 path
                title_map=title_map,                 # custom titles
                description=DEFAULT_DESCRIPTION,     # your constant
                tags=DEFAULT_TAGS,                   # your constant
                category_id="10",
                playlist=None,
                privacy=self.args.get("privacy", "private"),
                publish_at=self.args.get("publish_at"),
                tz=self.args.get("tz", "America/Chicago"),
                made_for_kids=False,
                lang="en",
                thumbnail_map=None,
                comment=None,
                dry_run=self.args.get("dry_run", False),
                channel_override=None,
                artist_file_map=None
            )

            self.update_progress(" All stem videos uploaded", {"artist": artist})

        except Exception as e:
            self.update_progress(f" Batch upload failed: {e}", {"artist": track.get("artist")})

    def upload_to_youtube(self, stem_type, video_path, title, track):
        try:
            if stem_type and video_path:
                self.video_paths[stem_type] = video_path
        except Exception as e:
            self.update_progress(f"load tracking failed: {e}", {"stem": stem_type})

    def upload_to_ec2_if_needed(self, local_path):
        if self.args.get("ec2"):
            try:
                self.update_progress(" Uploading to EC2...", {"path": local_path})
                uploader = Uploader()
                uploader.upload_to_ec2(local_path)
                self.update_progress(" Upload to EC2 complete", {"path": local_path})
            except Exception as e:
                self.update_progress(f" EC2 upload failed: {e}", {"path": local_path})

    # -----------------------------------------------------------
    # TRACK INFO (adds ISRC, prefers Tunebat BPM/key if provided)
    # -----------------------------------------------------------
    def get_track_info(self, track_id: str):
        """
        Pull full metadata + ISRC from Spotify.
        Prefer BPM/key from args (Tunebat) if present.
        """
        if self.track_info and self.track_info.get("id") == track_id:
            return self.track_info

        try:
            track = self.sp.track(track_id)
            artist = track["artists"][0]["name"]
            title = track["name"]

            # ISRC
            isrc = track.get("external_ids", {}).get("isrc", None)

            album_images = track["album"]["images"]
            img_url = album_images[0]["url"] if album_images else ""

            # Prefer BPM / key from args (Tunebat)
            bpm = self.args.get("bpm") or 0
            key_name = self.args.get("key") or "Unknown"

            # Note: Spotify removed audio_features access for new apps (403 error).
            # BPM/Key will be 0/Unknown — pipeline handles this gracefully.
            if not bpm:
                bpm = 0
            if not key_name:
                key_name = "Unknown"

            duration_seconds = track.get("duration_ms", 0) / 1000.0

            final = {
                "id": track_id,
                "name": title,
                "artist": artist,
                "album": track["album"]["name"],
                "img": img_url,
                "tempo": bpm,
                "key": key_name,
                "duration_seconds": duration_seconds,
                "isrc": isrc,
            }

            self.track_info = final
            print(f"[Track Info] Artist={artist} | Title={title} | BPM={bpm} | Key={key_name} | ISRC={isrc}")
            return final

        except Exception as e:
            print(f" Track info error: {e}")
            return None

    # -----------------------------------------------------------
    # STRICT ISRC → TOPIC MATCHER
    # -----------------------------------------------------------
    def find_topic_by_isrc(self, isrc: str):
        """
        Search YouTube using ISRC only.
        Return the Topic or official audio upload.
        """
        if not isrc:
            print("No ISRC — cannot strict match.")
            return None

        query = f"ytsearch15:{isrc}"  # Reducido de 50 a 15 para velocidad
        opts = {"quiet": True, "skip_download": True}

        print(f"[ISRC Search] Query: {query}")

        try:
            with YoutubeDL(opts) as ydl:
                results = ydl.extract_info(query, download=False)
        except Exception as e:
            print(f"[ISRC Search] yt-dlp error: {e}")
            return None

        if not results or "entries" not in results:
            print("No entries from ISRC search.")
            return None

        # yt-dlp can yield None placeholders; drop them to avoid IndexError.
        entries = [e for e in (results.get("entries") or []) if e]

        if not entries:
            print("No valid entries from ISRC search.")
            return None

        # 1. Prefer REAL Topic channels
        for e in entries:
            uploader = (e.get("uploader") or "").lower()
            if "topic" in uploader:
                print(f"[Match] Topic channel: {uploader}")
                return e

        # 2. Else, match ISRC inside description
        for e in entries:
            desc = (e.get("description") or "").lower()
            if isrc.lower() in desc:
                print("[Match] ISRC found in description")
                return e

        # 3. Final fallback: first result
        print("[Fallback] Using first ISRC result")
        return entries[0]

    def search_audio_by_metadata(self, title: str, artist: str):
        """
        Fallback search using artist + title when strict ISRC lookup fails.
        Returns the first available YoutubeDL entry.
        """
        query = f"ytsearch5:{artist} {title}"  # Reducido de 10 a 5 para velocidad
        opts = {"quiet": True, "skip_download": True}

        print(f"[Fallback Search] Query: {query}")
        try:
            with YoutubeDL(opts) as ydl:
                results = ydl.extract_info(query, download=False)
        except Exception as e:
            print(f"[Fallback Search] yt-dlp error: {e}")
            return None

        entries = [e for e in (results.get("entries") or []) if e] if results else []
        if not entries:
            print("[Fallback Search] No results found.")
            return None

        return entries[0]

    # -----------------------------------------------------------
    # STRICT AUDIO DOWNLOAD (Topic-Only via ISRC)
    # -----------------------------------------------------------
    def download_audio(self, title: str, artist: str):
        """
        Download MP3 from official Topic channel or ISRC-verified upload.
        No fuzzy logic. No duration checking.
        """
        print("\n============================")
        print("   STRICT TOPIC DOWNLOAD")
        print("============================\n")

        isrc = None
        if self.track_info:
            isrc = self.track_info.get("isrc")

        if not isrc:
            print("❌ Cannot download: missing ISRC in track_info.")
            return None, None

        info = self.find_topic_by_isrc(isrc)
        if not info:
            print("❌ No Topic/ISRC match found. Trying fallback search…")
            info = self.search_audio_by_metadata(title, artist)

        if not info:
            print("❌ No audio source found after fallback.")
            return None, None

        video_id = info.get("id")
        uploader = info.get("uploader", "Unknown")
        video_title = info.get("title", "Unknown")
        print(f"[Download] {uploader} — {video_title}")

        os.makedirs("Audio", exist_ok=True)

        uid = f"{uploader} - {video_id}"
        # OPTIMIZADO: Usar formato nativo M4A (no conversión)
        final_audio = f"Audio/{uid}.m4a"

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio[ext=m4a]/bestaudio/best",  # Priorizar audio M4A
            "outtmpl": f"{uid}.%(ext)s",
            "extractor_args": {"youtube": {"player_client": ["android"]}},
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                'preferredquality': '128',
            }],
            "format_sort": ["acodec:m4a", "abr"],  # Priorizar M4A y bitrate de audio
            "prefer_free_formats": False,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
        }

        print("[Downloading audio (M4A native)...]")
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_id])

        # Buscar archivo descargado (puede ser m4a, webm, etc)
        temp_audio = None
        for ext in ['m4a', 'webm', 'opus']:
            test_path = f"{uid}.{ext}"
            if os.path.exists(test_path):
                temp_audio = test_path
                break
        
        if not temp_audio:
            print("✗ Audio not produced.")
            return None, None

        # Make sure the Audio folder exists
        os.makedirs(os.path.dirname(final_audio), exist_ok=True)

        if os.path.exists(final_audio):
            # Audio already exists from a previous run – reuse it
            print(f"ℹ Audio already exists, reusing: {final_audio}")
            # Clean up temp file if yt-dlp produced one
            if os.path.exists(temp_audio):
                try:
                    os.remove(temp_audio)
                except OSError:
                    pass
        else:
            # First time for this track – move temp file into Audio folder
            os.replace(temp_audio, final_audio)

        print(f"✅ Saved Audio: {final_audio}")
        return uid, final_audio

    # -----------------------------------------------------------
    # THUMBNAIL DOWNLOAD
    # -----------------------------------------------------------
    def download_thumbnail(self, url: str, artist=None, title=None, bpm=None, key=None):
        try:
            if not url:
                print(" Thumbnail URL empty.")
                return None

            artist = artist or self.track_info.get("artist", "Unknown")
            title = title or self.track_info.get("name", "Unknown")
            bpm = bpm or self.track_info.get("tempo", 0)
            key = key or self.track_info.get("key", "Unknown")

            folder_title = self.sanitize_name(f"{artist} {title} [{bpm} BPM {key}]")
            out_dir = os.path.join("Thumbnails", folder_title)
            os.makedirs(out_dir, exist_ok=True)

            out_path = os.path.join(out_dir, "cover.png")
            if os.path.exists(out_path):
                return out_path

            r = requests.get(url, timeout=10)
            r.raise_for_status()

            with open(out_path, "wb") as f:
                f.write(r.content)

            return out_path

        except Exception as e:
            print(f" Thumbnail failure: {e}")
            return None

    # -----------------------------------------------------------
    # STEMS EXIST CHECK
    # -----------------------------------------------------------
    def stems_already_exist(self):
        if not self.stem_base_path:
            return False
        try:
            files = os.listdir(self.stem_base_path)
            count = len([f for f in files if f.endswith(".mp3")])
            return count >= 4
        except Exception:
            return False
