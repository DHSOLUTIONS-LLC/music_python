"""
models.py
SQLAlchemy ORM models — uses Integer (compatible with both SQLite and MySQL).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    spotify_input: Mapped[str] = mapped_column(String(500))
    input_type: Mapped[str] = mapped_column(String(50), default="track")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    total_tracks: Mapped[int] = mapped_column(Integer, default=0)
    channels: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    privacy: Mapped[str] = mapped_column(String(50), default="public")
    yt_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tiktok_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    tracks: Mapped[List["Track"]] = relationship("Track", back_populates="job", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(255), index=True)
    spotify_track_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    artist: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    album: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bpm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    isrc: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    job: Mapped["Job"] = relationship("Job", back_populates="tracks")
    stems: Mapped[List["Stem"]] = relationship("Stem", back_populates="track", cascade="all, delete-orphan")


class Stem(Base):
    __tablename__ = "stems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    stem_type: Mapped[str] = mapped_column(String(100))
    audio_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    video_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    track: Mapped["Track"] = relationship("Track", back_populates="stems")
    uploads: Mapped[List["Upload"]] = relationship("Upload", back_populates="stem", cascade="all, delete-orphan")


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stem_id: Mapped[int] = mapped_column(Integer, ForeignKey("stems.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(50))
    channel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    channel_display: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    video_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    privacy: Mapped[str] = mapped_column(String(50), default="public")
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    stem: Mapped["Stem"] = relationship("Stem", back_populates="uploads")
