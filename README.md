# YouTube Downloader

A Python-based YouTube video downloader with a neobrutalist web interface. Submit YouTube URLs via API or web UI, download videos with yt-dlp, and manage downloads in a queue.

## Features

- 📥 YouTube video download via REST API or Web UI
- 🤖 Automatic processing using yt-dlp
- 💾 SQLite database for queue management
- 🎨 Neobrutalist UI with smooth animations
- 🔄 Real-time status updates with auto-refresh
- 📱 Fully responsive design
- 🗑️ Auto-cleanup of old downloads (10 days)

## Project Structure

```
youtube-downloader/
├── app.py              # Flask API server with embedded worker
├── worker.py           # Background download service (standalone)
├── index.html          # Frontend UI
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker configuration
├── youtube_downloads.db # SQLite database (auto-created)
└── downloads/          # Downloaded video files (auto-created)
```

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the API Server

```bash
python app.py
```

The server will start on `http://localhost:7860`

### 3. Access the Web Interface

Open your browser and navigate to:
```
http://localhost:7860
```

## Docker Deployment

```bash
# Build the image
docker build -t youtube-downloader .

# Run the container
docker run -p 7860:7860 youtube-downloader
```

## Usage

### Via Web Interface

1. Paste a YouTube URL in the input field
2. Click "Download"
3. Watch the status update in real-time
4. Click "Save" to download the video once processing completes

### Via API

**Submit Download:**
```bash
curl -X POST http://localhost:7860/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

**Get All Downloads:**
```bash
curl http://localhost:7860/api/downloads
```

**Get Specific Download:**
```bash
curl http://localhost:7860/api/downloads/<download_id>
```

**Download Video File:**
```bash
curl http://localhost:7860/api/downloads/<download_id>/video --output video.mp4
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/download` | POST | Submit YouTube URL for download |
| `/api/downloads` | GET | Get all downloads |
| `/api/downloads/<id>` | GET | Get specific download |
| `/api/downloads/<id>/video` | GET | Download the video file |
| `/health` | GET | Health check |

---

### `POST /api/download`

Submit a YouTube URL for download.

**Request:**
- **Content-Type:** `application/json`
- **Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | String | Yes | YouTube video URL |

**Supported URL formats:**
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "status": "not_started",
  "message": "Download queued successfully"
}
```

**Error Responses:**

| Status | Response |
|--------|----------|
| 400 | `{"error": "No URL provided"}` |
| 400 | `{"error": "URL is empty"}` |
| 400 | `{"error": "Invalid YouTube URL"}` |

---

### `GET /api/downloads`

Retrieve all downloads with their status and metadata.

**Request:** No parameters required.

**Response (200 OK):**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "filepath": "downloads/550e8400-e29b-41d4-a716-446655440000.mp4",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "duration": "3:33",
    "filesize": "45.2 MB",
    "status": "completed",
    "error": null,
    "created_at": "2024-01-15T10:30:00.000000",
    "processed_at": "2024-01-15T10:31:45.000000",
    "queue_position": null,
    "estimated_start_seconds": null
  },
  {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "url": "https://www.youtube.com/watch?v=example",
    "title": "Example Video",
    "filepath": null,
    "thumbnail": "https://i.ytimg.com/vi/example/maxresdefault.jpg",
    "duration": "5:20",
    "filesize": null,
    "status": "processing",
    "error": null,
    "created_at": "2024-01-15T10:35:00.000000",
    "processed_at": null,
    "queue_position": null,
    "estimated_start_seconds": null
  },
  {
    "id": "770e8400-e29b-41d4-a716-446655440002",
    "url": "https://www.youtube.com/watch?v=queued",
    "title": null,
    "filepath": null,
    "thumbnail": null,
    "duration": null,
    "filesize": null,
    "status": "not_started",
    "error": null,
    "created_at": "2024-01-15T10:40:00.000000",
    "processed_at": null,
    "queue_position": 1,
    "estimated_start_seconds": 45
  }
]
```

---

### `GET /api/downloads/<download_id>`

Retrieve a specific download by its ID.

**Request:**

| Parameter | Type | Location | Description |
|-----------|------|----------|-------------|
| `download_id` | string | URL path | UUID of the download |

**Response (200 OK):**

*Example: Completed download*
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "filepath": "downloads/550e8400-e29b-41d4-a716-446655440000.mp4",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
  "duration": "3:33",
  "filesize": "45.2 MB",
  "status": "completed",
  "error": null,
  "created_at": "2024-01-15T10:30:00.000000",
  "processed_at": "2024-01-15T10:31:45.000000",
  "queue_position": null,
  "estimated_start_seconds": null
}
```

**Error Responses:**

| Status | Response |
|--------|----------|
| 404 | `{"error": "Download not found"}` |

---

### `GET /api/downloads/<download_id>/video`

Download the video file for a completed download.

**Request:**

| Parameter | Type | Location | Description |
|-----------|------|----------|-------------|
| `download_id` | string | URL path | UUID of the download |

**Response (200 OK):**
- Content-Type: `video/mp4` (or appropriate video type)
- Content-Disposition: `attachment; filename="Video Title.mp4"`

**Error Responses:**

| Status | Response |
|--------|----------|
| 404 | `{"error": "Download not found"}` |
| 400 | `{"error": "Video not ready yet"}` |
| 404 | `{"error": "Video file not found"}` |

---

### `GET /health`

Check the health status of the service.

**Request:** No parameters required.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "youtube-downloader",
  "worker_running": true
}
```

## Database Schema

```sql
CREATE TABLE downloads (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    filepath TEXT,
    thumbnail TEXT,
    duration TEXT,
    filesize TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT
);
```

## Status Values

| Status | Description | `queue_position` | `estimated_start_seconds` |
|--------|-------------|------------------|---------------------------|
| `not_started` | URL submitted, waiting in queue for processing | **Integer (1-based)** - Position in queue (1 = next to be processed) | **Integer** - Estimated seconds until download starts |
| `processing` | Currently being downloaded by the worker | `null` | `null` |
| `completed` | Successfully downloaded | `null` | `null` |
| `failed` | Error occurred during download | `null` | `null` |

> **Note:** 
> - `queue_position`: Indicates the download's position in the processing queue. A value of `1` means this download is next to be processed.
> - `estimated_start_seconds`: Calculated based on the average processing time of the last 20 completed downloads. If no downloads have been completed yet, defaults to 60 seconds per download.

## Tech Stack

- **Backend:** Flask (Python)
- **Database:** SQLite
- **Frontend:** Vanilla HTML/CSS/JavaScript
- **Download Engine:** yt-dlp
- **Design:** Neobrutalism with neon accents

## Troubleshooting

**Worker not processing downloads:**
- Ensure yt-dlp is properly installed (`pip install yt-dlp`)
- Check that ffmpeg is installed for video processing
- Verify the YouTube URL is valid and accessible

**Download fails with age restriction:**
- Some videos require authentication
- Try with a different video

**CORS errors:**
- Make sure flask-cors is installed
- Check that the API server is running

**Database errors:**
- Delete `youtube_downloads.db` and restart the API server to recreate it

## Auto-Cleanup

- Downloaded video files and database entries older than **10 days** are automatically deleted
- Cleanup runs before each download processing cycle

## License

MIT