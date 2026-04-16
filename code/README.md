# 🎼 Stem Splitter & YouTube Scheduler — v2.0

Splits music tracks into stems (vocals, drums, bass, melody) using **Demucs**,
renders MP4 videos, and uploads them to YouTube channels with scheduling.

---

## 📁 Project Structure

```
Music Backend/
├── tk.py                    # FastAPI entry point  ← START HERE
├── dispatch_download.py     # Orchestration (download → demucs → channels)
├── content_base.py          # Base class for all processors
├── content_download_main.py # Stem processor for all channels
├── shared_state.py          # In-memory progress store
├── yt_video_multi.py        # YouTube upload (multi-channel)
├── tunebat_helper.py        # BPM / Key scraper via Playwright
├── stem_processor.py        # Audio mixing utilities
├── config_manager.py        # Config loader
├── logger_central.py        # Run report logger
├── branding_utils.py        # Video watermarking
├── tiktok_uploader.py       # TikTok upload (optional)
├── requirements.txt
├── .env.example             # ← copy to .env and fill in
└── yt_tokens/               # YouTube OAuth tokens (add your own)
    ├── main_v2.json
    ├── acapella_v2.json
    ├── drums_v2.json
    ├── split_v2.json
    ├── backup_v2.json
    └── client_secret_2_*.json
```

---

## ⚙️ Setup (Windows / Linux / Mac)

### 1. Prerequisites
- **Python 3.10+**
- **ffmpeg** — install and add to PATH
  - Windows: https://ffmpeg.org/download.html
  - Linux: `sudo apt install ffmpeg`
- **ImageMagick** (optional, for branding): https://imagemagick.org

### 2. Create virtual environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / Mac
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt

# Install Playwright browser for BPM scraping
playwright install chromium
```

### 4. GPU support (optional but recommended)
```bash
# CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### 5. Configure environment
```bash
cp .env.example .env
# Edit .env and fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
```

### 6. Add YouTube tokens
Place your authorized token files inside `yt_tokens/`:
- `main_v2.json`, `acapella_v2.json`, `drums_v2.json`, `split_v2.json`, `backup_v2.json`
- `client_secret_2_*.json` (unified OAuth client secret)

To authorize a token, run:
```bash
python auth_multi_init.py
```

---

## ▶️ Run the server

```bash
uvicorn tk:app --reload --host 0.0.0.0 --port 8000
```

API available at: **http://localhost:8000**
Swagger docs at: **http://localhost:8000/docs**

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/` | Serves HTML UI |
| `GET`  | `/health` | Health check |
| `POST` | `/split` | Start stem processing pipeline |
| `GET`  | `/progress/{session_id}` | SSE stream (closes when done) |
| `GET`  | `/progress-poll/{session_id}` | JSON poll (for Laravel) |
| `GET`  | `/sessions` | List active sessions |
| `POST` | `/reset-progress/{session_id}` | Clear a session |
| `POST` | `/cleanup` | Delete temp folders |

---

## 📡 Laravel Integration

### Step 1 — Call `/split`

```php
// app/Services/StemService.php
use Illuminate\Support\Facades\Http;

class StemService
{
    protected string $baseUrl;

    public function __construct()
    {
        $this->baseUrl = config('services.stem_api.url', 'http://localhost:8000');
    }

    public function startProcessing(array $params): array
    {
        $response = Http::timeout(30)->post("{$this->baseUrl}/split", [
            'track_id'   => $params['track_id'],   // Spotify URL or ID
            'channels'   => $params['channels'],   // e.g. ["mainchannel","songotdrums"]
            'yt'         => $params['yt'] ?? true,
            'privacy'    => $params['privacy'] ?? 'public',
            'genre'      => $params['genre'] ?? 'Hip-Hop',
            'startTime'  => $params['start_time'] ?? null,
            'interval'   => $params['interval'] ?? 'Every Hour',
            'tz'         => $params['tz'] ?? 'America/Chicago',
        ]);

        return $response->json();
        // Returns: { session_ids: [...], tracks_processed: N, ... }
    }

    public function pollProgress(string $sessionId): array
    {
        $response = Http::get("{$this->baseUrl}/progress-poll/{$sessionId}");

        if ($response->status() === 404) {
            return ['message' => 'Session not found', 'percent' => 0];
        }

        return $response->json();
        // Returns: { message, percent, done, meta: { title, artist, ... } }
    }

    public function cleanup(): void
    {
        Http::post("{$this->baseUrl}/cleanup");
    }
}
```

### Step 2 — Controller example

```php
// app/Http/Controllers/StemController.php
class StemController extends Controller
{
    public function process(Request $request, StemService $stemService)
    {
        $result = $stemService->startProcessing($request->validated());

        return response()->json([
            'session_ids' => $result['session_ids'],
            'message'     => $result['message'],
        ]);
    }

    public function progress(Request $request, string $sessionId, StemService $stemService)
    {
        $data = $stemService->pollProgress($sessionId);
        return response()->json($data);
    }
}
```

### Step 3 — Frontend polling (JavaScript)

```javascript
async function pollUntilDone(sessionId) {
    while (true) {
        const res = await fetch(`/api/stem/progress/${sessionId}`);
        const data = await res.json();

        updateProgressBar(data.percent);
        updateMessage(data.message);

        if (data.done || data.percent >= 100) break;
        await new Promise(r => setTimeout(r, 2000)); // poll every 2s
    }
}
```

Or use the SSE endpoint for real-time push:

```javascript
const es = new EventSource(`http://localhost:8000/progress/${sessionId}`);
es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    console.log(data.percent + '%', data.message);
    if (data.done) es.close();
};
```

### Step 4 — config/services.php

```php
'stem_api' => [
    'url' => env('STEM_API_URL', 'http://localhost:8000'),
],
```

### Step 5 — .env (Laravel)

```
STEM_API_URL=http://localhost:8000
```

---

## 🔑 Channel Keys Reference

| UI key | Display name |
|--------|-------------|
| `mainchannel` | Main |
| `sgs2` | SGS 2 |
| `songotdrums` | Drum |
| `songotacapellas` | Acappella |
| `samplesplit` | Sample Split |
| `tiktok` | Tik Tok |

---

## ⚠️ Notes

- `yt_tokens/` must be populated with valid OAuth tokens before YouTube uploads work
- `ffmpeg` must be in your system PATH
- For GPU: install the CUDA version of PyTorch (see Step 4 above)
- TikTok upload is optional; set `tiktok: false` in the request to skip
- Celery is **not required** — the server uses threading for concurrency
