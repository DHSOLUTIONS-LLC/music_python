import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


RUN_REPORT_FILE = "run_report.json"
ERROR_LOG_FILE = "error_log.txt"
RETRY_QUEUE_FILE = "retry_queue.json"


class CentralLogger:
    def __init__(self):
        self.run_report = self._load_report()
        self.session_id = None

    def _load_report(self) -> Dict:
        if os.path.exists(RUN_REPORT_FILE):
            try:
                with open(RUN_REPORT_FILE, "r") as f:
                    return json.load(f)
            except:
                return {"sessions": []}
        return {"sessions": []}

    def _save_report(self):
        with open(RUN_REPORT_FILE, "w") as f:
            json.dump(self.run_report, f, indent=2)

    def start_session(self, session_id: str, metadata: Dict[str, Any]):
        self.session_id = session_id
        session = {
            "session_id": session_id,
            "start_time": datetime.now().isoformat(),
            "metadata": metadata,
            "tracks": [],
            "status": "in_progress"
        }
        self.run_report["sessions"].append(session)
        self._save_report()
        print(f" Session started: {session_id}")

    def log_track_start(self, track_id: str, title: str, artist: str):
        if self.session_id:
            sessions = self.run_report.get("sessions", [])
            for s in sessions:
                if s.get("session_id") == self.session_id:
                    s["tracks"].append({
                        "track_id": track_id,
                        "title": title,
                        "artist": artist,
                        "start_time": datetime.now().isoformat(),
                        "stems": [],
                        "uploads": [],
                        "status": "processing"
                    })
                    self._save_report()
                    break

    def log_stem_success(self, track_id: str, stem_type: str, file_path: str):
        if self.session_id:
            sessions = self.run_report.get("sessions", [])
            for s in sessions:
                if s.get("session_id") == self.session_id:
                    for track in s.get("tracks", []):
                        if track.get("track_id") == track_id:
                            track["stems"].append({
                                "type": stem_type,
                                "path": file_path,
                                "timestamp": datetime.now().isoformat(),
                                "status": "success"
                            })
                            self._save_report()
                            return

    def log_upload_success(self, track_id: str, stem_type: str, channel: str, video_id: str):
        if self.session_id:
            sessions = self.run_report.get("sessions", [])
            for s in sessions:
                if s.get("session_id") == self.session_id:
                    for track in s.get("tracks", []):
                        if track.get("track_id") == track_id:
                            track["uploads"].append({
                                "stem_type": stem_type,
                                "channel": channel,
                                "video_id": video_id,
                                "timestamp": datetime.now().isoformat(),
                                "status": "success"
                            })
                            self._save_report()
                            return

    def log_error(self, error_type: str, message: str, context: Dict[str, Any] = None):
        timestamp = datetime.now().isoformat()
        error_entry = f"[{timestamp}] {error_type}: {message}\n"
        if context:
            error_entry += f"Context: {json.dumps(context, indent=2)}\n"
        error_entry += "-" * 80 + "\n"
        
        with open(ERROR_LOG_FILE, "a") as f:
            f.write(error_entry)
        
        print(f" Error logged: {error_type}")

    def end_session(self, status: str = "completed"):
        if self.session_id:
            sessions = self.run_report.get("sessions", [])
            for s in sessions:
                if s.get("session_id") == self.session_id:
                    s["end_time"] = datetime.now().isoformat()
                    s["status"] = status
                    self._save_report()
                    print(f" Session ended: {self.session_id} ({status})")
                    break

    def get_session_summary(self, session_id: str) -> Optional[Dict]:
        sessions = self.run_report.get("sessions", [])
        for s in sessions:
            if s.get("session_id") == session_id:
                return s
        return None

    def get_all_sessions(self) -> list:
        return self.run_report.get("sessions", [])

    def export_report(self, output_file: str = "export_report.json"):
        with open(output_file, "w") as f:
            json.dump(self.run_report, f, indent=2)
        print(f" Report exported to {output_file}")


logger = CentralLogger()
