import json
import os
from typing import Dict, Any, Optional
from datetime import datetime


CHECKPOINT_FILE = "checkpoint.json"
RECOVERY_CACHE_FILE = "recovery_cache.json"


class CheckpointRecovery:
    def __init__(self):
        self.checkpoint = self._load_checkpoint()
        self.recovery_cache = self._load_recovery_cache()

    def _load_checkpoint(self) -> Dict:
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, "r") as f:
                    return json.load(f)
            except:
                return {"playlists": {}, "tracks": {}, "stems": {}}
        return {"playlists": {}, "tracks": {}, "stems": {}}

    def _save_checkpoint(self):
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(self.checkpoint, f, indent=2)

    def _load_recovery_cache(self) -> Dict:
        if os.path.exists(RECOVERY_CACHE_FILE):
            try:
                with open(RECOVERY_CACHE_FILE, "r") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_recovery_cache(self):
        with open(RECOVERY_CACHE_FILE, "w") as f:
            json.dump(self.recovery_cache, f, indent=2)

    def save_playlist_checkpoint(self, playlist_id: str, status: str, metadata: Dict[str, Any]):
        self.checkpoint["playlists"][playlist_id] = {
            "status": status,
            "metadata": metadata,
            "timestamp": datetime.now().isoformat(),
            "total_tracks": metadata.get("total_tracks", 0),
            "processed_tracks": metadata.get("processed_tracks", 0)
        }
        self._save_checkpoint()
        print(f" Playlist checkpoint saved: {playlist_id} ({status})")

    def save_track_checkpoint(self, track_id: str, playlist_id: str, status: str, metadata: Dict[str, Any]):
        if track_id not in self.checkpoint["tracks"]:
            self.checkpoint["tracks"][track_id] = {}
        
        self.checkpoint["tracks"][track_id] = {
            "playlist_id": playlist_id,
            "status": status,
            "metadata": metadata,
            "timestamp": datetime.now().isoformat(),
            "stem_types": metadata.get("stem_types", []),
            "processed_stems": metadata.get("processed_stems", [])
        }
        self._save_checkpoint()
        print(f" Track checkpoint saved: {track_id} ({status})")

    def save_stem_checkpoint(self, stem_key: str, track_id: str, stem_type: str, file_path: str, status: str):
        if stem_key not in self.checkpoint["stems"]:
            self.checkpoint["stems"][stem_key] = {}
        
        self.checkpoint["stems"][stem_key] = {
            "track_id": track_id,
            "stem_type": stem_type,
            "file_path": file_path,
            "status": status,
            "timestamp": datetime.now().isoformat()
        }
        self._save_checkpoint()
        print(f" Stem checkpoint saved: {stem_key} ({status})")

    def get_playlist_checkpoint(self, playlist_id: str) -> Optional[Dict]:
        return self.checkpoint.get("playlists", {}).get(playlist_id)

    def get_track_checkpoint(self, track_id: str) -> Optional[Dict]:
        return self.checkpoint.get("tracks", {}).get(track_id)

    def get_incomplete_playlists(self) -> list:
        incomplete = []
        for playlist_id, data in self.checkpoint.get("playlists", {}).items():
            if data.get("status") != "completed":
                incomplete.append({
                    "playlist_id": playlist_id,
                    "status": data.get("status"),
                    "timestamp": data.get("timestamp"),
                    "metadata": data.get("metadata")
                })
        return incomplete

    def get_incomplete_tracks(self, playlist_id: str) -> list:
        incomplete = []
        for track_id, data in self.checkpoint.get("tracks", {}).items():
            if data.get("playlist_id") == playlist_id and data.get("status") != "completed":
                incomplete.append({
                    "track_id": track_id,
                    "status": data.get("status"),
                    "timestamp": data.get("timestamp"),
                    "metadata": data.get("metadata")
                })
        return incomplete

    def cache_stem_file(self, stem_key: str, file_path: str):
        self.recovery_cache[stem_key] = {
            "file_path": file_path,
            "cached_at": datetime.now().isoformat(),
            "file_exists": os.path.exists(file_path)
        }
        self._save_recovery_cache()
        print(f" Stem file cached: {stem_key}")

    def get_cached_stem_file(self, stem_key: str) -> Optional[str]:
        cached = self.recovery_cache.get(stem_key)
        if cached:
            file_path = cached.get("file_path")
            if os.path.exists(file_path):
                print(f" Retrieved cached stem file: {stem_key}")
                return file_path
        return None

    def clear_recovery_cache(self):
        self.recovery_cache = {}
        if os.path.exists(RECOVERY_CACHE_FILE):
            os.remove(RECOVERY_CACHE_FILE)
        print(" Recovery cache cleared")

    def clear_checkpoint(self):
        self.checkpoint = {"playlists": {}, "tracks": {}, "stems": {}}
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
        print(" Checkpoint cleared")

    def export_checkpoint(self, output_file: str = "checkpoint_export.json"):
        with open(output_file, "w") as f:
            json.dump(self.checkpoint, f, indent=2)
        print(f"Checkpoint exported to {output_file}")

    def get_recovery_stats(self) -> Dict[str, int]:
        return {
            "incomplete_playlists": len(self.get_incomplete_playlists()),
            "total_cached_items": len(self.recovery_cache),
            "checkpoint_entries": sum([
                len(self.checkpoint.get("playlists", {})),
                len(self.checkpoint.get("tracks", {})),
                len(self.checkpoint.get("stems", {}))
            ])
        }


_recovery = CheckpointRecovery()
