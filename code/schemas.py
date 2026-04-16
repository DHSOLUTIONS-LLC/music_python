"""
schemas.py
Pydantic schemas for API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


# ── Upload ────────────────────────────────────────────────────────────────────

class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stem_id: int
    platform: str
    channel: Optional[str]
    channel_display: Optional[str]
    video_id: Optional[str]
    video_url: Optional[str]
    title: Optional[str]
    privacy: str
    scheduled_at: Optional[datetime]
    uploaded_at: Optional[datetime]
    status: str
    created_at: datetime


# ── Stem ──────────────────────────────────────────────────────────────────────

class StemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    track_id: int
    stem_type: str
    audio_path: Optional[str]
    video_path: Optional[str]
    thumbnail_path: Optional[str]
    file_size_bytes: Optional[int]
    status: str
    created_at: datetime
    uploads: List[UploadOut] = []


# ── Track ─────────────────────────────────────────────────────────────────────

class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    session_id: str
    spotify_track_id: str
    title: Optional[str]
    artist: Optional[str]
    album: Optional[str]
    bpm: Optional[float]
    key: Optional[str]
    duration_seconds: Optional[float]
    isrc: Optional[str]
    thumbnail_url: Optional[str]
    status: str
    error_message: Optional[str]
    created_at: datetime
    stems: List[StemOut] = []


# ── Job ───────────────────────────────────────────────────────────────────────

class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    spotify_input: str
    input_type: str
    status: str
    total_tracks: int
    channels: Optional[str]
    genre: Optional[str]
    privacy: str
    yt_enabled: bool
    tiktok_enabled: bool
    created_at: datetime
    updated_at: datetime
    tracks: List[TrackOut] = []


class JobListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    spotify_input: str
    input_type: str
    status: str
    total_tracks: int
    genre: Optional[str]
    privacy: str
    created_at: datetime
    updated_at: datetime


# ── Stats ─────────────────────────────────────────────────────────────────────

class StatsOut(BaseModel):
    total_jobs: int
    done_jobs: int
    failed_jobs: int
    total_tracks: int
    total_stems: int
    total_uploads: int
    youtube_uploads: int
    tiktok_uploads: int
