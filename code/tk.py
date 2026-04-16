"""
tk.py — FastAPI v4
- Client's updated backend merged in
- SQLite (local) / MySQL (production) via SQLAlchemy
- CORS enabled for Laravel
- Web Library channel added
- Spotify-based BPM/Key (no browser)
- All DB endpoints: jobs, tracks, stems, uploads, stats
"""
from __future__ import annotations
import copy, json, os, shutil, threading, traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import asyncio
import spotipy
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from spotipy.oauth2 import SpotifyClientCredentials
from sqlalchemy.orm import Session

from database import SessionLocal, get_db, init_db
from db_service import (
    create_job, create_stem, create_track, create_upload,
    delete_job, get_job, get_stats, get_stems_by_track,
    get_track, get_tracks_by_job, get_uploads_by_stem,
    list_jobs, list_uploads, update_job_status, update_track_status,
)
from dispatch_download import UI_TO_CHANNEL_MAP, process_all_tracks
from schemas import JobListOut, JobOut, StatsOut, StemOut, TrackOut, UploadOut
from shared_state import cleanup_stale, delete_progress, get_progress, set_progress
from tunebat_helper import get_bpm_key

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "683468379f7a468dab2368c8f8f51486")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "9a56d7bf3f45458d89bb5a3476cc3c0b")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UI_CHANNEL_DISPLAY_MAP = {
    "mainchannel": "Main",
    "sgs2": "SGS 2",
    "songotdrums": "Drum",
    "songotacapellas": "Acappella",
    "samplesplit": "Sample Split",
    "tiktok": "Tik Tok",
    "weblibrary": "Web Library",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    removed = cleanup_stale()
    if removed:
        print(f"[STARTUP] Cleaned {removed} stale session(s)")
    yield

app = FastAPI(title="Stem Splitter & YouTube Scheduler", version="4.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
templates = Jinja2Templates(directory="templates")

class StemRequest(BaseModel):
    track_id: str
    channels: List[str]
    selected_stems: Optional[Dict[str, List[str]]] = None
    yt: bool = True
    tiktok: bool = False
    render_videos: bool = False
    ec2: bool = False
    trim: bool = False
    dry_run: bool = False
    genre: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    privacy: str = "public"
    made_for_kids: bool = False
    monetize: bool = False
    comments: Optional[Dict[str, str]] = None
    startTime: Optional[str] = None
    interval: Optional[str] = "Every Hour"
    tz: Optional[str] = "America/Chicago"
    schedule_start_time: Optional[str] = None
    schedule_interval_minutes: Optional[int] = None
    timezone: Optional[str] = None

def _sp():
    return spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

def extract_spotify_id(raw: str) -> str:
    return raw.split("/")[-1].split("?")[0] if "spotify.com" in raw else raw

def get_all_track_ids(playlist_id: str) -> List[str]:
    sp = _sp()
    ids, offset = [], 0
    while True:
        items = sp.playlist_tracks(playlist_id, limit=100, offset=offset).get("items", [])
        if not items:
            break
        for item in items:
            t = item.get("track")
            if t and t.get("id"):
                ids.append(t["id"])
        offset += 100
    return ids

def _resolve_interval(req: StemRequest):
    label_map = {60: "Every Hour", 120: "Every 2 Hours", 240: "Every 4 Hours", 1440: "Daily"}
    label_raw = (req.interval or "").lower()
    raw = req.schedule_interval_minutes
    if raw in (None, 0, 60):
        raw = None
    if raw is None:
        if "day" in label_raw or "24" in label_raw:
            raw = 1440
        elif "4" in label_raw:
            raw = 240
        elif "2" in label_raw:
            raw = 120
        else:
            raw = 60
    if "day" in label_raw and raw < 1440:
        raw = 1440
    return raw, label_map.get(raw, f"Every {raw} Minutes")

def _save_track_to_db(job_id, session_id, spotify_track_id, track_info, stem_paths, upload_results):
    db = SessionLocal()
    try:
        track = create_track(db=db, job_id=job_id, session_id=session_id, spotify_track_id=spotify_track_id,
            title=track_info.get("name"), artist=track_info.get("artist"), album=track_info.get("album"),
            bpm=track_info.get("tempo"), key=track_info.get("key"),
            duration_seconds=track_info.get("duration_seconds"), isrc=track_info.get("isrc"),
            thumbnail_url=track_info.get("img"))
        for stem_type, paths in stem_paths.items():
            stem = create_stem(db=db, track_id=track.id, stem_type=stem_type,
                audio_path=paths.get("audio"), video_path=paths.get("video"), thumbnail_path=paths.get("thumbnail"))
            ud = upload_results.get(stem_type, {})
            if ud.get("video_id"):
                create_upload(db=db, stem_id=stem.id, platform=ud.get("platform", "youtube"),
                    channel=ud.get("channel"), channel_display=ud.get("channel_display"),
                    video_id=ud.get("video_id"), video_url=f"https://youtu.be/{ud['video_id']}",
                    title=ud.get("title"), privacy=ud.get("privacy", "public"), scheduled_at=ud.get("scheduled_at"))
        update_track_status(db, session_id, "done")
        print(f"[DB] Saved: {track_info.get('artist')} — {track_info.get('name')}")
    except Exception as e:
        print(f"[DB ERROR] {e}")
        traceback.print_exc()
        update_track_status(db, session_id, "failed", str(e))
    finally:
        db.close()

# ── UI ──
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Error: index.html not found in templates folder</h1>")

@app.get("/health")
def health():
    return {"status": "ok", "version": "4.0.0"}

# ── Progress ──
@app.get("/sessions")
def list_sessions():
    from shared_state import _store, _lock
    with _lock:
        return {"sessions": list(_store.keys())}

@app.get("/progress/{session_id}")
async def progress_stream(session_id: str):
    async def gen():
        idle = 0
        while True:
            data = get_progress(session_id) or {"message": "Waiting…", "percent": 0}
            yield f"data: {json.dumps(data)}\n\n"
            if data.get("done") or data.get("percent") == 100:
                break
            idle += 1
            if idle > 600:
                break
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/progress-poll/{session_id}")
def progress_poll(session_id: str):
    data = get_progress(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data

@app.post("/reset-progress/{session_id}")
def reset_progress(session_id: str):
    delete_progress(session_id)
    return {"message": f"Progress reset for {session_id}"}

@app.post("/cleanup")
async def cleanup_files():
    try:
        for folder in ["MP3", "Audio", "Separated", "Thumbnails", "tunebat_debug", "MP4"]:
            path = os.path.join(BASE_DIR, folder)
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
        cache = os.path.join(BASE_DIR, ".cache")
        if os.path.exists(cache):
            os.remove(cache)
        return {"status": "success", "message": "Cleaned up!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── Split ──
@app.post("/split")
def split_and_schedule(request: StemRequest, db: Session = Depends(get_db)):
    try:
        input_id = extract_spotify_id(request.track_id)
        converted_stems = {UI_TO_CHANNEL_MAP.get(k, k): v for k, v in (request.selected_stems or {}).items()}
        converted_comments = {UI_TO_CHANNEL_MAP.get(k, k): v for k, v in (request.comments or {}).items()}
        interval_minutes, interval_label = _resolve_interval(request)
        start_raw = request.schedule_start_time or request.startTime or ""
        normalised_start = start_raw.strip().replace("T", " ")[:16] if start_raw else ""
        shared_args = {
            "yt": request.yt, "tiktok": request.tiktok, "render_videos": request.render_videos,
            "ec2": request.ec2, "trim": request.trim, "dry_run": request.dry_run,
            "client_id": SPOTIFY_CLIENT_ID, "client_secret": SPOTIFY_CLIENT_SECRET,
            "privacy": request.privacy or "public", "made_for_kids": request.made_for_kids,
            "tags": request.tags or [], "description": request.description or "",
            "monetize": request.monetize, "genre": request.genre or "Hip-Hop",
            "trim_track": False, "trim_length": 72, "comments": converted_comments,
            "selected_stems": converted_stems, "base_start_local": normalised_start,
            "interval_minutes": interval_minutes, "schedule_mode": interval_label,
            "tz": request.tz or "America/Chicago",
            "fast_mode": not request.yt and not request.tiktok and not request.render_videos,
        }
        if shared_args["fast_mode"]:
            shared_args["start_jitter_sec"] = (0, 0)
            shared_args["per_track_cooldown_sec"] = 0

        sp = _sp()
        track_ids, input_type = [], "track"
        try:
            pl = sp.playlist(input_id)
            track_ids = get_all_track_ids(input_id)
            input_type = "playlist"
            print(f"[SPOTIFY] Playlist: {pl.get('name')} ({len(track_ids)} tracks)")
        except Exception:
            try:
                ar = sp.artist(input_id)
                top = sp.artist_top_tracks(input_id, country="US")
                track_ids = [t["id"] for t in (top.get("tracks") or []) if t.get("id")]
                input_type = "artist"
                print(f"[SPOTIFY] Artist: {ar.get('name')} ({len(track_ids)} tracks)")
            except Exception:
                track_ids = [input_id]
                input_type = "track"

        if not track_ids:
            raise HTTPException(status_code=400, detail="No tracks found.")

        job = create_job(db=db, session_id=input_id, spotify_input=request.track_id,
            input_type=input_type, total_tracks=len(track_ids), channels=request.channels,
            genre=request.genre, privacy=request.privacy, yt_enabled=request.yt, tiktok_enabled=request.tiktok)

        sessions, batch = [], []
        for idx, tid in enumerate(track_ids):
            sid = f"{input_id}__{tid}"
            sessions.append(sid)
            info = sp.track(tid)
            artist_name = info["artists"][0]["name"]
            title_name = info["name"]
            batch.append((title_name, artist_name, tid))
            set_progress(sid, {"message": "Preparing…", "percent": 0,
                "meta": {"track_id": tid, "title": title_name, "artist": artist_name,
                         "channels": [UI_CHANNEL_DISPLAY_MAP.get(c, c) for c in request.channels],
                         "index": idx + 1, "total_tracks": len(track_ids)}})

        job_id = job.id

        def run_pipeline():
            per_track_args = {}
            bpm_key_map = {}
            for title_name, artist_name, tid in batch:
                bpm, key = get_bpm_key(title_name, artist_name, tid)
                bpm_key_map[tid] = (bpm, key)
            for idx, (title_name, artist_name, tid) in enumerate(batch):
                bpm, key = bpm_key_map.get(tid, (0, "Unknown"))
                args = copy.deepcopy(shared_args)
                args.update({"bpm": bpm, "key": key, "global_artist_index": idx})
                start_local = args.get("base_start_local", "")
                if start_local:
                    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
                        try:
                            parsed = datetime.strptime(start_local, fmt)
                            args["publish_at"] = (parsed + timedelta(minutes=interval_minutes * idx)).strftime("%Y-%m-%d %H:%M")
                            break
                        except ValueError:
                            pass
                args["db_job_id"] = job_id
                args["db_save_callback"] = _save_track_to_db
                per_track_args[tid] = args
            max_concurrent = 2 if shared_args.get("fast_mode") else 1
            process_all_tracks(track_ids, request.channels, args=shared_args,
                per_track_args=per_track_args, session_id=input_id, max_concurrent=max_concurrent)
            db2 = SessionLocal()
            try:
                update_job_status(db2, input_id, "done")
            finally:
                db2.close()

        threading.Thread(target=run_pipeline, daemon=True).start()

        return {"message": "Processing started", "job_id": job.id, "tracks_processed": len(track_ids),
                "channels": [UI_CHANNEL_DISPLAY_MAP.get(c, c) for c in request.channels], "session_ids": sessions}

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] /split: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

# ── DB API ──
@app.get("/api/jobs", response_model=List[JobListOut])
def api_list_jobs(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return list_jobs(db, skip=skip, limit=limit)

@app.get("/api/jobs/{job_id}", response_model=JobOut)
def api_get_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: int, db: Session = Depends(get_db)):
    if not delete_job(db, job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"message": "Job deleted"}

@app.get("/api/jobs/{job_id}/tracks", response_model=List[TrackOut])
def api_get_job_tracks(job_id: int, db: Session = Depends(get_db)):
    if not get_job(db, job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return get_tracks_by_job(db, job_id)

@app.get("/api/tracks/{track_id}", response_model=TrackOut)
def api_get_track(track_id: int, db: Session = Depends(get_db)):
    t = get_track(db, track_id)
    if not t:
        raise HTTPException(status_code=404, detail="Track not found")
    return t

@app.get("/api/tracks/{track_id}/stems", response_model=List[StemOut])
def api_get_track_stems(track_id: int, db: Session = Depends(get_db)):
    if not get_track(db, track_id):
        raise HTTPException(status_code=404, detail="Track not found")
    return get_stems_by_track(db, track_id)

@app.get("/api/stems/{stem_id}", response_model=StemOut)
def api_get_stem(stem_id: int, db: Session = Depends(get_db)):
    from db_service import get_stem
    s = get_stem(db, stem_id)
    if not s:
        raise HTTPException(status_code=404, detail="Stem not found")
    return s

@app.get("/api/uploads", response_model=List[UploadOut])
def api_list_uploads(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return list_uploads(db, skip=skip, limit=limit)

@app.get("/api/stems/{stem_id}/uploads", response_model=List[UploadOut])
def api_get_stem_uploads(stem_id: int, db: Session = Depends(get_db)):
    return get_uploads_by_stem(db, stem_id)

@app.get("/api/stats", response_model=StatsOut)
def api_stats(db: Session = Depends(get_db)):
    return get_stats(db)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tk:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8000)), reload=True)
