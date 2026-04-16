import os
import json
import time
import requests
from typing import Optional, Dict, Any
from pathlib import Path


TIKTOK_TOKENS_DIR = Path("yt_tokens")
TIKTOK_CONFIG_FILE = TIKTOK_TOKENS_DIR / "tiktok_config.json"
TIKTOK_API_RETRY_LIMIT = 5
TIKTOK_BACKOFF_BASE = 1.5


class TikTokUploader:
    def __init__(self):
        self.config = self._load_config()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def _load_config(self) -> Dict:
        if os.path.exists(TIKTOK_CONFIG_FILE):
            try:
                with open(TIKTOK_CONFIG_FILE, "r") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_config(self):
        TIKTOK_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        with open(TIKTOK_CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)

    def _exponential_backoff(self, attempt: int) -> float:
        return min(TIKTOK_BACKOFF_BASE ** attempt, 60)

    def authenticate(self, access_token: str, user_id: str) -> bool:
        try:
            self.config["access_token"] = access_token
            self.config["user_id"] = user_id
            self.config["authenticated"] = True
            self.config["auth_timestamp"] = time.time()
            self._save_config()
            print(" TikTok authentication configured")
            return True
        except Exception as e:
            print(f" TikTok authentication failed: {e}")
            return False

    def is_authenticated(self) -> bool:
        return self.config.get("authenticated", False)

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list,
        thumbnail_path: Optional[str] = None,
        allow_download: bool = True,
        allow_duet: bool = True,
        allow_stitch: bool = True
    ) -> Optional[str]:
        if not os.path.exists(video_path):
            print(f" Video file not found: {video_path}")
            return None

        if not self.is_authenticated():
            print(" TikTok not authenticated")
            return None

        file_size = os.path.getsize(video_path)
        max_size = 287661056

        if file_size > max_size:
            print(f" Video file too large: {file_size} bytes (max: {max_size})")
            return None

        for attempt in range(TIKTOK_API_RETRY_LIMIT):
            try:
                print(f" Uploading to TikTok (attempt {attempt + 1}/{TIKTOK_API_RETRY_LIMIT})...")

                caption = f"{title}\n{description}\n" + " ".join([f"#{tag}" for tag in tags[:20]])
                caption = caption[:2048]

                with open(video_path, "rb") as f:
                    files = {
                        "video": (os.path.basename(video_path), f, "video/mp4")
                    }
                    data = {
                        "caption": caption,
                        "allow_download": "true" if allow_download else "false",
                        "allow_duet": "true" if allow_duet else "false",
                        "allow_stitch": "true" if allow_stitch else "false"
                    }

                    headers = {
                        "Authorization": f"Bearer {self.config.get('access_token')}"
                    }

                    response = self.session.post(
                        f"https://open.tiktok.com/oauth/video/publish/",
                        files=files,
                        data=data,
                        headers=headers,
                        timeout=300
                    )

                    if response.status_code == 200:
                        result = response.json()
                        video_id = result.get("data", {}).get("video_id")
                        print(f" TikTok upload successful: {video_id}")
                        return video_id
                    elif response.status_code in [429, 500, 502, 503, 504]:
                        wait_time = self._exponential_backoff(attempt)
                        print(f" Rate limited/Server error, waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f" TikTok upload failed: {response.status_code} - {response.text}")
                        return None

            except Exception as e:
                print(f" TikTok upload attempt {attempt + 1} error: {e}")
                if attempt < TIKTOK_API_RETRY_LIMIT - 1:
                    wait_time = self._exponential_backoff(attempt)
                    print(f" Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)

        print(f" Failed to upload to TikTok after {TIKTOK_API_RETRY_LIMIT} attempts")
        return None

    def post_comment(self, video_id: str, comment_text: str) -> bool:
        if not self.is_authenticated():
            print(" TikTok not authenticated")
            return False

        try:
            headers = {
                "Authorization": f"Bearer {self.config.get('access_token')}"
            }
            data = {
                "text": comment_text[:150]
            }

            response = self.session.post(
                f"https://open.tiktok.com/v1/video/{video_id}/comment/create/",
                json=data,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                print(f" TikTok comment posted successfully")
                return True
            else:
                print(f" TikTok comment posting failed: {response.status_code}")
                return False

        except Exception as e:
            print(f" Error posting TikTok comment: {e}")
            return False

    def get_video_analytics(self, video_id: str) -> Optional[Dict]:
        if not self.is_authenticated():
            print(" TikTok not authenticated")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.config.get('access_token')}"
            }

            response = self.session.get(
                f"https://open.tiktok.com/v1/video/{video_id}/query/",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                return response.json().get("data", {})
            else:
                print(f" Failed to get analytics: {response.status_code}")
                return None

        except Exception as e:
            print(f" Error fetching analytics: {e}")
            return None


_uploader = TikTokUploader()


def upload_to_tiktok(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    thumbnail_path: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    return _uploader.upload_video(
        video_path,
        title,
        description,
        tags,
        thumbnail_path,
        **kwargs
    )


def tiktok_is_ready() -> bool:
    return _uploader.is_authenticated()
