import json
import os
from typing import Dict, Any, Optional, TYPE_CHECKING
from pathlib import Path
from dotenv import load_dotenv

if TYPE_CHECKING:
    from demucs.pretrained import get_model


CONFIG_FILE = "config.json"
ENV_FILE = ".env"


class ConfigManager:
    def __init__(self):
        self.config = self._load_config()
        self._load_env()

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
            except:
                return self._default_config()
        return self._default_config()

    def _load_env(self):
        if os.path.exists(ENV_FILE):
            load_dotenv(ENV_FILE)

    def _default_config(self) -> Dict[str, Any]:
        return {
            "spotify": {
                "client_id": os.getenv("SPOTIFY_CLIENT_ID", ""),
                "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET", "")
            },
            "youtube": {
                "tokens_dir": "yt_tokens",
                "channels": {
                    "main": "main_v2.json",
                    "acapellas": "acapella_v2.json",
                    "drums": "drums_v2.json",
                    "split": "split_v2.json",
                    "backup": "backup_v2.json"
                }
            },
            "tiktok": {
                "enabled": False,
                "config_file": "yt_tokens/tiktok_config.json",
                "access_token": os.getenv("TIKTOK_ACCESS_TOKEN", ""),
                "user_id": os.getenv("TIKTOK_USER_ID", "")
            },
            "demucs": {
                "models": ["htdemucs_ft", "htdemucs_6s", "htdemucs"],
                "primary_model": "htdemucs_ft",
                "device": "cuda:0",
                "shifts": 0
            },
            "audio": {
                "sample_rate": 44100,
                "channels": 2,
                "loudness_target": -1.0,
                "fade_duration": 500,
                "min_file_size": 102400
            },
            "processing": {
                "max_concurrent": 1,
                "trim_track": False,
                "trim_length": 72,
                "privacy_default": "public",
                "made_for_kids": False,
                "monetize": False
            },
            "directories": {
                "mp3": "MP3",
                "separated": "Separated",
                "mp4": "MP4",
                "thumbnails": "Thumbnails",
                "logs": "logs",
                "debug": "tunebat_debug"
            },
            "logging": {
                "enabled": True,
                "level": "INFO",
                "run_report": "run_report.json",
                "error_log": "error_log.txt",
                "retry_queue": "retry_queue.json"
            },
            "recovery": {
                "enabled": True,
                "checkpoint_file": "checkpoint.json",
                "recovery_cache": "recovery_cache.json",
                "auto_resume": True
            },
            "timeouts": {
                "demucs": 300,
                "youtube_upload": 600,
                "tiktok_upload": 300,
                "tunebat": 120
            }
        }

    def _save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)
        print(f" Configuration saved to {CONFIG_FILE}")

    def get(self, section: str, key: Optional[str] = None) -> Any:
        if key:
            return self.config.get(section, {}).get(key)
        return self.config.get(section, {})

    def set(self, section: str, key: str, value: Any):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
        self._save_config()
        print(f" Configuration updated: {section}.{key}")

    def set_section(self, section: str, data: Dict[str, Any]):
        self.config[section] = data
        self._save_config()
        print(f" Section updated: {section}")

    def setup_directories(self):
        dirs = self.config.get("directories", {})
        for dir_key, dir_path in dirs.items():
            os.makedirs(dir_path, exist_ok=True)
        print(" All directories created/verified")

    def validate_spotify_config(self) -> bool:
        spotify_config = self.config.get("spotify", {})
        client_id = spotify_config.get("client_id")
        client_secret = spotify_config.get("client_secret")
        
        if not client_id or not client_secret:
            print(" Spotify credentials missing in config")
            return False
        print(" Spotify credentials valid")
        return True

    def validate_youtube_config(self) -> bool:
        youtube_config = self.config.get("youtube", {})
        tokens_dir = youtube_config.get("tokens_dir", "yt_tokens")
        
        if not os.path.exists(tokens_dir):
            print(f" YouTube tokens directory not found: {tokens_dir}")
            return False
        print(" YouTube tokens directory exists")
        return True

    def validate_demucs_config(self) -> bool:
        try:
            from demucs.pretrained import get_model
            model = self.config["demucs"].get("primary_model", "htdemucs_ft")
            get_model(model)
            print(f" Demucs model available: {model}")
            return True
        except Exception as e:
            print(f" Demucs model error: {e}")
            return False

    def export_config(self, output_file: str = "config_export.json"):
        with open(output_file, "w") as f:
            json.dump(self.config, f, indent=2)
        print(f" Configuration exported to {output_file}")

    def generate_setup_report(self) -> Dict[str, Any]:
        return {
            "spotify": self.validate_spotify_config(),
            "youtube": self.validate_youtube_config(),
            "demucs": self.validate_demucs_config(),
            "directories": all(os.path.exists(d) for d in self.config.get("directories", {}).values()),
            "config_file_exists": os.path.exists(CONFIG_FILE),
            "env_file_exists": os.path.exists(ENV_FILE)
        }


_manager = ConfigManager()


def get_config() -> ConfigManager:
    return _manager
