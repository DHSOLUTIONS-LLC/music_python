"""
db_service.py
All database read/write operations.
Called from tk.py (API routes) and from the processing pipeline.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from models import Job, Stem, Track, Upload


# ── Jobs ──────────────────────────────────────────────────────────────────────

def create_job(
    db: Session,
    session_id: str,
    spotify_input: str,
    input_type: str,
    total_tracks: int,
    channels: list,
    genre: Optional[str],
    privacy: str,
    yt_enabled: bool,
    tiktok_enabled: bool,
) -> Job:
    job = Job(
        session_id=session_id,
        spotify_input=spotify_input,
        input_type=input_type,
        status="processing",
        total_tracks=total_tracks,
        channels=json.dumps(channels),
        genre=genre,
        privacy=privacy,
        yt_enabled=yt_enabled,
        tiktok_enabled=tiktok_enabled,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Optional[Job]:
    return db.query(Job).filter(Job.id == job_id).first()


def get_job_by_session(db: Session, session_id: str) -> Optional[Job]:
    return db.query(Job).filter(Job.session_id == session_id).first()


def list_jobs(db: Session, skip: int = 0, limit: int = 50) -> List[Job]:
    return db.query(Job).order_by(Job.created_at.desc()).offset(skip).limit(limit).all()


def update_job_status(db: Session, session_id: str, status: str):
    job = get_job_by_session(db, session_id)
    if job:
        job.status = status
        db.commit()


def delete_job(db: Session, job_id: int) -> bool:
    job = get_job(db, job_id)
    if not job:
        return False
    db.delete(job)
    db.commit()
    return True


# ── Tracks ────────────────────────────────────────────────────────────────────

def create_track(
    db: Session,
    job_id: int,
    session_id: str,
    spotify_track_id: str,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    bpm: Optional[float] = None,
    key: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    isrc: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
) -> Track:
    track = Track(
        job_id=job_id,
        session_id=session_id,
        spotify_track_id=spotify_track_id,
        title=title,
        artist=artist,
        album=album,
        bpm=bpm,
        key=key,
        duration_seconds=duration_seconds,
        isrc=isrc,
        thumbnail_url=thumbnail_url,
        status="processing",
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def get_track(db: Session, track_id: int) -> Optional[Track]:
    return db.query(Track).filter(Track.id == track_id).first()


def get_tracks_by_job(db: Session, job_id: int) -> List[Track]:
    return db.query(Track).filter(Track.job_id == job_id).all()


def update_track(db: Session, track_id: int, **kwargs):
    track = get_track(db, track_id)
    if track:
        for k, v in kwargs.items():
            if hasattr(track, k):
                setattr(track, k, v)
        db.commit()


def update_track_status(db: Session, session_id: str, status: str, error_message: Optional[str] = None):
    track = db.query(Track).filter(Track.session_id == session_id).first()
    if track:
        track.status = status
        if error_message:
            track.error_message = error_message
        db.commit()


# ── Stems ─────────────────────────────────────────────────────────────────────

def create_stem(
    db: Session,
    track_id: int,
    stem_type: str,
    audio_path: Optional[str] = None,
    video_path: Optional[str] = None,
    thumbnail_path: Optional[str] = None,
) -> Stem:
    file_size = None
    path = video_path or audio_path
    if path and os.path.exists(path):
        file_size = os.path.getsize(path)

    stem = Stem(
        track_id=track_id,
        stem_type=stem_type,
        audio_path=audio_path,
        video_path=video_path,
        thumbnail_path=thumbnail_path,
        file_size_bytes=file_size,
        status="ready",
    )
    db.add(stem)
    db.commit()
    db.refresh(stem)
    return stem


def get_stem(db: Session, stem_id: int) -> Optional[Stem]:
    return db.query(Stem).filter(Stem.id == stem_id).first()


def get_stems_by_track(db: Session, track_id: int) -> List[Stem]:
    return db.query(Stem).filter(Stem.track_id == track_id).all()


# ── Uploads ───────────────────────────────────────────────────────────────────

def create_upload(
    db: Session,
    stem_id: int,
    platform: str,
    channel: Optional[str] = None,
    channel_display: Optional[str] = None,
    video_id: Optional[str] = None,
    video_url: Optional[str] = None,
    title: Optional[str] = None,
    privacy: str = "public",
    scheduled_at: Optional[datetime] = None,
) -> Upload:
    upload = Upload(
        stem_id=stem_id,
        platform=platform,
        channel=channel,
        channel_display=channel_display,
        video_id=video_id,
        video_url=video_url,
        title=title,
        privacy=privacy,
        scheduled_at=scheduled_at,
        uploaded_at=datetime.utcnow() if video_id else None,
        status="uploaded" if video_id else "pending",
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def get_uploads_by_stem(db: Session, stem_id: int) -> List[Upload]:
    return db.query(Upload).filter(Upload.stem_id == stem_id).all()


def list_uploads(db: Session, skip: int = 0, limit: int = 100) -> List[Upload]:
    return db.query(Upload).order_by(Upload.created_at.desc()).offset(skip).limit(limit).all()


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(db: Session) -> dict:
    total_jobs = db.query(Job).count()
    total_tracks = db.query(Track).count()
    total_stems = db.query(Stem).count()
    total_uploads = db.query(Upload).count()
    done_jobs = db.query(Job).filter(Job.status == "done").count()
    failed_jobs = db.query(Job).filter(Job.status == "failed").count()
    youtube_uploads = db.query(Upload).filter(Upload.platform == "youtube").count()
    tiktok_uploads = db.query(Upload).filter(Upload.platform == "tiktok").count()

    return {
        "total_jobs": total_jobs,
        "done_jobs": done_jobs,
        "failed_jobs": failed_jobs,
        "total_tracks": total_tracks,
        "total_stems": total_stems,
        "total_uploads": total_uploads,
        "youtube_uploads": youtube_uploads,
        "tiktok_uploads": tiktok_uploads,
    }
