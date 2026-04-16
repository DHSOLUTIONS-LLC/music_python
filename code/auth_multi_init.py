"""
auth_multi_init.py
---------------------------------
Permanent authentication for all YouTube channels (with confirmation).

Each channel token is saved in ./yt_tokens:
  - main_v2.json
  - backup_v2.json
  - drums_v2.json
  - acapella_v2.json
  - split_v2.json

 Tokens refresh automatically forever.
 Confirmation prompt after every login ensures no channel mix-ups.
 Automatically finds any client_secret*.json file inside yt_tokens.
 Compatible with latest google-auth-oauthlib (uses run_local_server).
"""

import os, glob
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ================================================================
# SETTINGS
# ================================================================
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtubepartner",
    # Required to insert comment threads
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# Always resolve relative to this file
TOKEN_DIR = Path(__file__).parent / "yt_tokens"
os.makedirs(TOKEN_DIR, exist_ok=True)

CHANNELS = [
    ("Main Channel", "main_v2.json"),
    ("Backup Channel", "backup_v2.json"),
    ("Drums Channel", "drums_v2.json"),
    ("Acapella Channel", "acapella_v2.json"),
    ("Split Channel", "split_v2.json"),
]

# ================================================================
# AUTO-DETECT CLIENT SECRET JSON
# ================================================================
client_secret_files = list(TOKEN_DIR.glob("client_secret*.json"))
if not client_secret_files:
    raise FileNotFoundError(f" No client_secret JSON found in {TOKEN_DIR.resolve()}")

CLIENT_SECRET_PATH = client_secret_files[0]
print(f" Using client secret file: {CLIENT_SECRET_PATH.name}")

# ================================================================
# AUTH FUNCTION
# ================================================================
def authenticate_channel(label, filename):
    print(f"\n {label} — checking authentication...")
    token_path = TOKEN_DIR / filename
    creds = None

    # Load existing credentials if present
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.valid:
            print(f" {label} already authenticated and valid.")
            return creds
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
                print(f" Auto-refreshed {label} token — permanent access maintained.")
                return creds
            except Exception as e:
                print(f" Refresh failed for {label}: {e}")

    # New login if no valid token
    print(f" Starting new permanent auth for {label}. A browser window will open...")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)

    # Launch browser and authenticate
    creds = flow.run_local_server(port=0, prompt='consent')

    # Save credentials (includes refresh_token)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    # Verify actual YouTube channel name
    youtube = build("youtube", "v3", credentials=creds)
    me = youtube.channels().list(part="snippet", mine=True).execute()
    title = me["items"][0]["snippet"]["title"] if me.get("items") else "Unknown Channel"
    print(f" Authorized YouTube Channel: {title}")

    # Confirmation step
    confirm = input(f"Is this correct for {label}? (y/n): ").strip().lower()
    if confirm != "y":
        print(f" Removing {filename}. Please re-authenticate the correct account.")
        os.remove(token_path)
        return authenticate_channel(label, filename)

    print(f" Confirmed: {label} linked to '{title}' → Saved as {filename}")
    return creds

# ================================================================
# MAIN
# ================================================================
def main():
    print("\n Multi-Channel YouTube OAuth (Permanent + Confirmation)")
    print("----------------------------------------------------------")
    for label, filename in CHANNELS:
        try:
            authenticate_channel(label, filename)
        except Exception as e:
            print(f" Failed for {label}: {e}")

    print("\n\ All channels authenticated permanently and confirmed!")
    print(f"Tokens stored in: {TOKEN_DIR.resolve()}\n")

if __name__ == "__main__":
    main()
