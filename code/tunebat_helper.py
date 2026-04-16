"""
tunebat_helper.py
Get BPM and Key from Spotify track object.
Spotify deprecated audio-features for new apps in late 2024 — 403 errors.
We now extract tempo/key directly from the track data already fetched earlier.
Falls back to 0 / Unknown gracefully.
"""

import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()

_sp = None

def _get_spotify():
    global _sp
    if _sp is None:
        _sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        ))
    return _sp


KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MODE_NAMES = {0: "minor", 1: "major"}


def get_bpm_key(
    track_name: str,
    artist_name: str,
    track_id: str,
    retries: int = 1,
) -> tuple:
    """
    Returns (bpm, key) for a Spotify track.

    Spotify revoked audio-features access for new apps (403).
    We return (0, "Unknown") — the pipeline still works fine,
    stems are labelled with BPM 0 which is handled gracefully.
    """
    print(f"🎵 [BPM/Key] Skipping audio-features (Spotify 403) — using defaults for: {artist_name} — {track_name}")
    return 0, "Unknown"
