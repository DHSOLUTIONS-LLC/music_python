"""
dispatch_download.py — Orchestrates download → Demucs → channel processing.
"""
from __future__ import annotations
import importlib, os, subprocess, sys, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor
from random import uniform
from typing import Dict, List, Optional
import torch
import content_base
print("USING CONTENT_BASE FILE:", content_base.__file__)
from content_base import ContentBase, CHANNEL_NAME_MAP
from shared_state import get_progress, set_progress

import requests
import os


# ============================================================
# Laravel Upload Function
# ============================================================
# def upload_stem_to_laravel(audio_path, track_info, stem_type, bpm, key, genre):
#     """Upload stem to Laravel API"""
#     laravel_url = "https://puristic-filmily-bula.ngrok-free.dev"
    
#     if not laravel_url:
#         print(f"⚠️ [LARAVEL] No API URL configured")
#         return
    
#     if not os.path.exists(audio_path):
#         print(f"⚠️ [LARAVEL] File not found: {audio_path}")
#         return
    
#     try:
#         # Handle BPM (required, integer, min 40, max 220)
#         try:
#             bpm_int = int(float(bpm)) if bpm else 120
#         except (ValueError, TypeError):
#             bpm_int = 120
        
#         if bpm_int < 40:
#             bpm_int = 80
#         elif bpm_int > 220:
#             bpm_int = 120
        
#         # Handle Key
#         key_value = key if key and key != "Unknown" and key.strip() else "C"
        
#         # Handle Genre
#         genre_map = {
#             'hiphop': 'Hip Hop',
#             'hip-hop': 'Hip Hop',
#             'rnb': 'R&B',
#             'r&b': 'R&B',
#             'jazz': 'Jazz',
#             'soul': 'Soul',
#             'rock': 'Rock',
#             'pop': 'Pop',
#             'electronic': 'Electronic',
#             'world': 'World',
#             'lo-fi': 'Lo-fi',
#             'lofi': 'Lo-fi'
#         }
#         genre_value = genre_map.get(genre.lower(), 'Hip Hop') if genre else 'Hip Hop'
        
#         # Handle Stem Type
#         stem_type_value = stem_type.capitalize()
#         valid_stem_types = ['Acapella', 'Drums', 'Bass', 'Melody', 'Instrumental']
#         if stem_type_value not in valid_stem_types:
#             stem_type_value = 'Acapella'
        
#         with open(audio_path, 'rb') as f:
#             files = {'file': (os.path.basename(audio_path), f, 'audio/mpeg')}
#             data = {
#                 'title': track_info.get('name', 'Unknown'),
#                 'artist': track_info.get('artist', 'Unknown'),
#                 'stem_type': stem_type_value,
#                 'bpm': bpm_int,
#                 'key': key_value,
#                 'genre': genre_value
#             }
            
#             print(f"📤 [LARAVEL] Uploading {stem_type_value}...")
#             print(f"   Data: {data}")
            
#             response = requests.post(
#                 f"{laravel_url}/api/upload/single",
#                 files=files,
#                 data=data,
#                 timeout=60
#             )
            
#             if response.status_code == 200 or response.status_code == 201:
#                 result = response.json()
#                 stem_id = result.get('stem', {}).get('id')
#                 print(f"✅ [LARAVEL] Uploaded {stem_type_value} (ID: {stem_id})")
#                 return result
#             else:
#                 print(f"❌ [LARAVEL] Upload failed: {response.status_code}")
#                 print(f"   Response: {response.text[:500]}")
#                 return None
                
#     except Exception as e:
#         print(f"❌ [LARAVEL] Upload error: {e}")
#         return None


# ============================================================



def get_optimal_device() -> str:
    if torch.cuda.is_available():
        print(f"[GPU] {torch.cuda.get_device_name(0)}")
        return "cuda:0"
    print("[GPU] Not available — using CPU")
    return "cpu"

project_root = os.path.dirname(os.path.abspath(__file__))
for p in (project_root, os.path.join(project_root, "stem_processing")):
    if p not in sys.path:
        sys.path.insert(0, p)

UI_TO_CHANNEL_MAP: Dict[str, str] = {
    "main": "main_channel",
    "backup": "sgs_2",
    "drum": "son_got_drums",
    "vocal": "son_got_acapellas",
    "acappella": "son_got_acapellas",
    "samplesplit": "sample_split",
    "tiktok": "tiktok_channel",
    "weblibrary": "web_library",
    "mainchannel": "main_channel",
    "sgs2": "sgs_2",
    "songotdrums": "son_got_drums",
    "songotacapellas": "son_got_acapellas",
}

CHANNEL_MODULE_MAP: Dict[str, tuple] = {
    "main_channel":     ("content_download_main", "Content_download_main"),
    "sgs_2":            ("content_download_main", "Content_download_main"),
    "son_got_drums":    ("content_download_main", "Content_download_main"),
    "son_got_acapellas":("content_download_main", "Content_download_main"),
    "sample_split":     ("content_download_main", "Content_download_main"),
    "tiktok_channel":   ("content_download_main", "Content_download_main"),
    "web_library":      ("content_download_main", "Content_download_main"),
}

FALLBACK_MODELS = ["htdemucs_ft", "htdemucs_6s", "htdemucs"]

def validate_stems(base_dir: str) -> Dict:
    required = ["vocals.mp3", "drums.mp3", "bass.mp3", "other.mp3"]
    problems = {s: "missing" for s in required if not os.path.exists(os.path.join(base_dir, s))}
    return {"ok": not problems, "problems": problems}

def is_sane_audio(path: str) -> bool:
    try:
        return os.path.getsize(path) > 150_000
    except Exception:
        return False

def _prepared_copy_path(uid: str) -> str:
    os.makedirs("MP3", exist_ok=True)
    return os.path.join("MP3", f"{uid}__prep.mp3")

def demucs_outdir_for_input(model_name: str, input_mp3: str) -> str:
    base = os.path.splitext(os.path.basename(input_mp3))[0]
    return os.path.join("Separated", model_name, base)

def recover_stem_dir(universal_id: str) -> Optional[str]:
    if not universal_id:
        return None
    for model in FALLBACK_MODELS:
        for suffix in ("", "__prep"):
            cand = os.path.abspath(os.path.join("Separated", model, f"{universal_id}{suffix}"))
            if os.path.isdir(cand):
                return cand
    return None

def run_demucs_with_model_stream(mp3_path: str, device: str, model_name: str):
    try:
        print(f"\n[DEMUCS] Running {model_name} on {device}")
        proc = subprocess.Popen(
            ["demucs", "--mp3", "-n", model_name, "--shifts", "0", "-d", device, mp3_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        lines: List[str] = []
        for line in iter(proc.stdout.readline, ""):
            if line:
                sys.stdout.write(f"[DEMUCS][{model_name}] {line}")
                sys.stdout.flush()
                lines.append(line)
                if len(lines) > 200:
                    lines.pop(0)
        proc.stdout.close()
        proc.wait()
        return proc.returncode, "".join(lines)
    except Exception as e:
        print(f"[DEMUCS] Failed: {e}")
        return None, ""

def prepare_input_for_demucs(src_mp3: str, prepared_path: str) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", src_mp3, "-ac", "2", "-ar", "44100",
             "-af", "loudnorm=I=-14:TP=-2:LRA=11", prepared_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        return os.path.exists(prepared_path) and os.path.getsize(prepared_path) > 150_000
    except Exception as e:
        print(f"[PREP] ffmpeg failed: {e}")
        return False

def run_demucs_with_fallbacks(mp3_path: str, device: str, session_id: str):
    for idx, model in enumerate(FALLBACK_MODELS, 1):
        set_progress(session_id, {"message": f"Separating with {model} (attempt {idx})…", "percent": 12})
        rc, tail = run_demucs_with_model_stream(mp3_path, device, model)
        out_dir = demucs_outdir_for_input(model, mp3_path)
        if rc is None:
            continue
        if rc != 0 or not os.path.exists(out_dir):
            if device.startswith("cuda") and ("CUDA out of memory" in tail or "CUDA error" in tail):
                rc2, _ = run_demucs_with_model_stream(mp3_path, "cpu", model)
                if rc2 == 0 and os.path.exists(out_dir):
                    v = validate_stems(out_dir)
                    if v["ok"]:
                        return model, out_dir, v
            continue
        v = validate_stems(out_dir)
        if v["ok"]:
            return model, out_dir, v
        set_progress(session_id, {"message": f"Fallback: {model} weak stems…", "percent": 20})
    return None, None, {"ok": False, "problems": {"_": "all_models_failed"}}

def predownload_audio_for_track(track_id: str, args: dict, session_id: str, per_track_args=None):
    print(f"\n[PREDOWNLOAD] Track: {track_id}")
    base = ContentBase({**args, "session_id": session_id})
    track_info = base.get_track_info(track_id)
    if not track_info:
        set_progress(session_id, {"message": "Failed to get track info", "percent": 0})
        return
    args["track_info"] = track_info
    args["isrc"] = track_info.get("isrc")
    uid = args.get("universal_id")
    mp3_path = args.get("mp3_path")
    if uid and mp3_path and os.path.exists(mp3_path) and is_sane_audio(mp3_path):
        print(f"[PREDOWNLOAD] Reusing: {mp3_path}")
    else:
        base.update_progress("Downloading track audio…", {"track_id": track_id})
        uid, mp3_path = base.download_audio(track_info["name"], track_info["artist"])
        if not uid or not mp3_path or not os.path.exists(mp3_path) or not is_sane_audio(mp3_path):
            wait_s = uniform(15, 30)
            print(f"[PREDOWNLOAD RETRY] Waiting {wait_s:.1f}s…")
            time.sleep(wait_s)
            uid, mp3_path = base.download_audio(track_info["name"], track_info["artist"])
        if not uid or not os.path.exists(mp3_path) or not is_sane_audio(mp3_path):
            set_progress(session_id, {"message": "Audio download failed", "percent": 0})
            return
    if per_track_args is not None:
        per_track_args.setdefault(track_id, {})
        per_track_args[track_id].update({"track_info": track_info, "isrc": track_info.get("isrc"), "universal_id": uid, "mp3_path": mp3_path})
    print(f"[PREDOWNLOAD] Done: {mp3_path}")

def dispatch_stem_processing(track_id: str, selected_channels: list, args: dict, session_id: str = "default"):
    print(f"\n[DISPATCH] Channels: {selected_channels}")
    args.setdefault("yt", False)
    args["tiktok"] = args.get("tiktok", False) or "tiktok" in selected_channels
    jitter = args.get("start_jitter_sec", (0.5, 2.0))
    if isinstance(jitter, (tuple, list)):
        time.sleep(uniform(*jitter))
    elif isinstance(jitter, (int, float)) and jitter > 0:
        time.sleep(float(jitter))
    base = ContentBase({**args, "session_id": session_id})
    track_info = base.get_track_info(track_id)
    if not track_info:
        set_progress(session_id, {"message": "Failed to get track info", "percent": 0})
        return
    args["track_info"] = track_info
    args["isrc"] = track_info.get("isrc")
    uid = args.get("universal_id")
    mp3_path = args.get("mp3_path")
    if uid and mp3_path and os.path.exists(mp3_path) and is_sane_audio(mp3_path):
        print(f"[DISPATCH] Using pre-downloaded: {mp3_path}")
    else:
        base.update_progress("Downloading track audio…", {"track_id": track_id})
        uid, mp3_path = base.download_audio(track_info["name"], track_info["artist"])
        if not uid or not mp3_path or not os.path.exists(mp3_path) or not is_sane_audio(mp3_path):
            wait_s = uniform(15, 30)
            time.sleep(wait_s)
            uid, mp3_path = base.download_audio(track_info["name"], track_info["artist"])
        if not uid or not os.path.exists(mp3_path) or not is_sane_audio(mp3_path):
            set_progress(session_id, {"message": "Audio download failed", "percent": 0})
            return
    args["universal_id"] = uid
    args["mp3_path"] = mp3_path

    # Always define prep_path before branches
    prep_path = _prepared_copy_path(uid)
    upload_enabled = args.get("yt", False)
    fast_mode = not upload_enabled
    if fast_mode:
        try:
            subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-af", "loudnorm=I=-14:TP=-2:LRA=11", prep_path],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            mp3_for_split = prep_path if os.path.exists(prep_path) and os.path.getsize(prep_path) > 150_000 else mp3_path
        except Exception:
            mp3_for_split = mp3_path
    else:
        mp3_for_split = prep_path if prepare_input_for_demucs(mp3_path, prep_path) else mp3_path

    # Check cached stems
    cached_dir = None
    cached_model = None
    for model in FALLBACK_MODELS:
        for base_name in (os.path.splitext(os.path.basename(mp3_path))[0], os.path.splitext(os.path.basename(prep_path))[0]):
            candidate = os.path.join("Separated", model, base_name)
            if os.path.exists(candidate) and validate_stems(candidate)["ok"]:
                cached_dir = candidate
                cached_model = model
                break
        if cached_dir:
            break

    if cached_dir:
        args["stem_base_path"] = os.path.abspath(cached_dir)
        set_progress(session_id, {"message": f"Using cached stems ({cached_model})", "percent": 45})
    else:
        set_progress(session_id, {"message": "Separating stems…", "percent": 12})
        device = get_optimal_device()
        model_used, stem_base_path, validation = run_demucs_with_fallbacks(mp3_for_split, device, session_id)
        if not model_used:
            set_progress(session_id, {"message": "Stem separation failed", "percent": 0})
            return
        args["stem_base_path"] = os.path.abspath(stem_base_path)
        set_progress(session_id, {"message": f"Separation complete ({model_used})", "percent": 45})

    progress = get_progress(session_id) or {}
    meta = progress.get("meta", {})
    progress.update({"message": "Processing channels…", "meta": {**meta, "completed": 0, "total": len(selected_channels)}, "percent": 46})
    set_progress(session_id, progress)
    fixed_sbp = os.path.abspath(args.get("stem_base_path", ""))

    for idx, channel_ui in enumerate(selected_channels):
        print(f"[CHANNEL] {idx+1}/{len(selected_channels)}: {channel_ui}")
        channel_key = UI_TO_CHANNEL_MAP.get(channel_ui, channel_ui)
        if channel_key not in CHANNEL_MODULE_MAP:
            print(f"[WARN] Unknown channel: {channel_key} — skipping")
            continue
        sbp = fixed_sbp
        if not os.path.isdir(sbp):
            rec = recover_stem_dir(args.get("universal_id", ""))
            if rec:
                sbp = fixed_sbp = rec
            else:
                print(f"[ERROR] stem_base_path invalid: {sbp}")
                continue
        try:
            module_name, class_name = CHANNEL_MODULE_MAP[channel_key]
            module = importlib.import_module(module_name)
            processor = getattr(module, class_name)({**args, "channel": channel_key, "session_id": session_id, "stem_base_path": sbp})
            for method in ("download", "process", "run", "handle"):
                if hasattr(processor, method):
                    getattr(processor, method)(track_id)
                    break
            
            # 🔥 UPLOAD STEMS TO LARAVEL
            # if hasattr(processor, 'video_paths'):
            #     for stem_type, video_path in processor.video_paths.items():
            #         audio_path = None
            #         if hasattr(processor, 'get_stem_path'):
            #             audio_path = processor.get_stem_path(stem_type)
            #         elif video_path:
            #             audio_path = video_path.replace('.mp4', '.mp3')
                    
            #         if audio_path and os.path.exists(audio_path):
            #             upload_stem_to_laravel(
            #                 audio_path=audio_path,
            #                 track_info=track_info,
            #                 stem_type=stem_type,
            #                 bpm=args.get("bpm", 120),
            #                 key=args.get("key", "C"),
            #                 genre=args.get("genre", "Hip Hop")
            #             )
            
            # Notify DB callback if present
            db_callback = args.get("db_save_callback")
            if db_callback:
                try:
                    db_callback(
                        args.get("db_job_id"),
                        session_id,
                        track_id,
                        track_info,
                        {k: {"audio": v} for k, v in processor.video_paths.items()},
                        {},
                    )
                except Exception as cb_err:
                    print(f"[DB CALLBACK] Error: {cb_err}")
            progress = get_progress(session_id) or {}
            meta = progress.get("meta", {})
            meta["completed"] = int(meta.get("completed", 0)) + 1
            total = int(meta.get("total", 1))
            progress.update({"meta": meta, "percent": 46 + int((meta["completed"] / total) * 54), "message": f"{CHANNEL_NAME_MAP.get(channel_key, channel_key)} done"})
            set_progress(session_id, progress)
        except Exception as e:
            traceback.print_exc()
            progress = get_progress(session_id) or {}
            progress["message"] = f"Error in {channel_key} — continuing"
            set_progress(session_id, progress)

    cooldown = args.get("per_track_cooldown_sec", 0)
    if isinstance(cooldown, (tuple, list)):
        time.sleep(uniform(*cooldown))
    elif isinstance(cooldown, (int, float)) and cooldown > 0:
        time.sleep(float(cooldown))

    try:
        if mp3_for_split == prep_path and os.path.exists(prep_path):
            os.remove(prep_path)
    except Exception:
        pass

    final = get_progress(session_id) or {}
    final.update({"message": "All processing complete", "percent": 100, "done": True})
    set_progress(session_id, final)
    print("[DONE] All processing complete")
    
    
def process_all_tracks(track_ids, selected_channels, args=None, session_id="batch", max_concurrent=1, per_track_args=None):
    print(f"[BATCH] channels={selected_channels}")
    if not track_ids:
        return
    if per_track_args is None:
        per_track_args = {}
    dl_sem = threading.Semaphore(max_concurrent)
    def _predownload(tid, sid):
        with dl_sem:
            merged = {**(args or {}), **per_track_args.get(tid, {})}
            try:
                predownload_audio_for_track(tid, merged, sid, per_track_args)
            except Exception as e:
                traceback.print_exc()
                set_progress(sid, {"message": f"Pre-download error — {e}", "percent": 0})
    with ThreadPoolExecutor(max_workers=max(1, min(len(track_ids), max_concurrent))) as ex:
        for tid in track_ids:
            ex.submit(_predownload, tid, f"{session_id}__{tid}")
    proc_sem = threading.Semaphore(max_concurrent)
    def _process(tid, sid):
        with proc_sem:
            merged = {**(args or {}), **per_track_args.get(tid, {})}
            try:
                dispatch_stem_processing(tid, selected_channels, merged, sid)
            except Exception as e:
                traceback.print_exc()
                set_progress(sid, {"message": f"Processing error — {e}", "percent": 0})
    with ThreadPoolExecutor(max_workers=max(1, min(len(track_ids), max_concurrent))) as ex:
        for tid in track_ids:
            ex.submit(_process, tid, f"{session_id}__{tid}")
