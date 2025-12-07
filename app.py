from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import sqlite3
import os
import uuid
from datetime import datetime, timedelta
import threading
import subprocess
import time
import json
import re

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
COOKIES_FILE = 'www.youtube.com_cookies.txt'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Create cookies file from environment variable if it exists
def setup_cookies():
    cookies_content = os.environ.get('YOUTUBE_COOKIES')
    if cookies_content:
        with open(COOKIES_FILE, 'w') as f:
            f.write(cookies_content)
        print("✅ YouTube cookies loaded from environment variable")
    elif os.path.exists(COOKIES_FILE):
        print("✅ YouTube cookies file found")
    else:
        print("⚠️  No YouTube cookies found - downloads may fail")

setup_cookies()

# Worker state
worker_thread = None
worker_running = False

def init_db():
    conn = sqlite3.connect('youtube_downloads.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS downloads
                 (id TEXT PRIMARY KEY,
                  url TEXT NOT NULL,
                  title TEXT,
                  filepath TEXT,
                  thumbnail TEXT,
                  duration TEXT,
                  filesize TEXT,
                  status TEXT NOT NULL,
                  error TEXT,
                  created_at TEXT NOT NULL,
                  processed_at TEXT)''')
    conn.commit()
    conn.close()

def start_worker():
    """Start the worker thread if not already running"""
    global worker_thread, worker_running
    
    if not worker_running:
        worker_running = True
        worker_thread = threading.Thread(target=worker_loop, daemon=True)
        worker_thread.start()
        print("✅ Worker thread started")

def cleanup_old_entries():
    """Delete database entries and video files older than 10 days"""
    try:
        conn = sqlite3.connect('youtube_downloads.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Calculate cutoff date (10 days ago)
        cutoff_date = (datetime.now() - timedelta(days=10)).isoformat()
        
        # First, get all old entries to delete their video files
        c.execute('''SELECT id, filepath FROM downloads 
                     WHERE created_at < ?''', (cutoff_date,))
        old_entries = c.fetchall()
        
        if old_entries:
            deleted_files = 0
            deleted_rows = 0
            
            for entry in old_entries:
                # Delete the video file if it exists
                filepath = entry['filepath']
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        deleted_files += 1
                    except Exception as e:
                        print(f"⚠️  Failed to delete old video file {filepath}: {e}")
            
            # Delete old database entries
            c.execute('''DELETE FROM downloads WHERE created_at < ?''', (cutoff_date,))
            deleted_rows = c.rowcount
            conn.commit()
            
            if deleted_rows > 0 or deleted_files > 0:
                print(f"🧹 Cleanup: Deleted {deleted_rows} old entries and {deleted_files} video files (older than 10 days)")
        
        conn.close()
    except Exception as e:
        print(f"⚠️  Cleanup error: {e}")

def extract_video_info(url):
    """Extract video info using yt-dlp without downloading"""
    try:
        command = [
            'yt-dlp',
            '--dump-json',
            '--no-download',
            '--no-warnings',
            '--cookies', 'www.youtube.com_cookies.txt',
            '--extractor-args', 'youtube:player_client=android',
            '--no-check-certificates',
            url
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration_string', info.get('duration', '')),
                'thumbnail': info.get('thumbnail', ''),
            }
        else:
            print(f"⚠️  yt-dlp info error: {result.stderr}")
    except Exception as e:
        print(f"⚠️  Failed to extract video info: {e}")
    
    return None

def worker_loop():
    """Main worker loop that downloads YouTube videos"""
    print("🤖 YouTube Downloader Worker started. Monitoring for new downloads...")
    
    POLL_INTERVAL = 3  # seconds
    
    while worker_running:
        # Run cleanup before processing each task
        cleanup_old_entries()
        try:
            # Get next unprocessed download
            conn = sqlite3.connect('youtube_downloads.db')
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute('''SELECT * FROM downloads 
                         WHERE status = 'not_started' 
                         ORDER BY created_at ASC 
                         LIMIT 1''')
            row = c.fetchone()
            conn.close()
            
            if row:
                download_id = row['id']
                url = row['url']
                
                print(f"\n{'='*60}")
                print(f"📥 Processing download: {download_id}")
                print(f"🔗 URL: {url}")
                print(f"{'='*60}")
                
                # Update status to processing
                update_status(download_id, 'processing')
                
                try:
                    # First, get video info
                    print(f"🔍 Extracting video info...")
                    info = extract_video_info(url)
                    
                    if info:
                        # Update with video info
                        conn = sqlite3.connect('youtube_downloads.db')
                        c = conn.cursor()
                        c.execute('''UPDATE downloads 
                                     SET title = ?, duration = ?, thumbnail = ?
                                     WHERE id = ?''',
                                  (info['title'], str(info['duration']), info['thumbnail'], download_id))
                        conn.commit()
                        conn.close()
                        print(f"📹 Title: {info['title']}")
                    
                    # Download video
                    output_template = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.%(ext)s")
                    
                    print(f"🔄 Downloading video...")
                    command = [
                        'yt-dlp',
                        '-f', 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
                        '-o', output_template,
                        '--no-playlist',
                        '--no-warnings',
                        '--cookies', 'www.youtube.com_cookies.txt',
                        '--extractor-args', 'youtube:player_client=android',
                        '--no-check-certificates',
                        '--retries', '3',
                        '--fragment-retries', '3',
                        url
                    ]
                    
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=3600  # 1 hour timeout
                    )
                    
                    if result.returncode != 0:
                        raise Exception(f"yt-dlp error: {result.stderr}")
                    
                    # Find the downloaded file
                    downloaded_file = None
                    for ext in ['mp4', 'webm', 'mkv', 'avi']:
                        potential_file = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.{ext}")
                        if os.path.exists(potential_file):
                            downloaded_file = potential_file
                            break
                    
                    if not downloaded_file:
                        raise Exception("Downloaded file not found")
                    
                    # Get file size
                    filesize = os.path.getsize(downloaded_file)
                    filesize_str = format_filesize(filesize)
                    
                    print(f"✅ Successfully downloaded: {downloaded_file}")
                    print(f"📦 Size: {filesize_str}")
                    
                    # Update database with success
                    conn = sqlite3.connect('youtube_downloads.db')
                    c = conn.cursor()
                    c.execute('''UPDATE downloads 
                                 SET status = ?, filepath = ?, filesize = ?, processed_at = ?
                                 WHERE id = ?''',
                              ('completed', downloaded_file, filesize_str, datetime.now().isoformat(), download_id))
                    conn.commit()
                    conn.close()
                    
                except Exception as e:
                    print(f"❌ Failed to download: {url}")
                    print(f"Error: {str(e)}")
                    update_status(download_id, 'failed', error=str(e))
                    
            else:
                # No downloads to process, sleep for a bit
                time.sleep(POLL_INTERVAL)
                
        except Exception as e:
            print(f"⚠️  Worker error: {str(e)}")
            time.sleep(POLL_INTERVAL)

def format_filesize(size_bytes):
    """Format file size in human readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def update_status(download_id, status, error=None):
    """Update the status of a download in the database"""
    conn = sqlite3.connect('youtube_downloads.db')
    c = conn.cursor()
    
    if status == 'failed':
        c.execute('''UPDATE downloads 
                     SET status = ?, error = ?, processed_at = ?
                     WHERE id = ?''',
                  (status, error, datetime.now().isoformat(), download_id))
    else:
        c.execute('UPDATE downloads SET status = ? WHERE id = ?', (status, download_id))
    
    conn.commit()
    conn.close()

def is_valid_youtube_url(url):
    """Validate YouTube URL"""
    youtube_patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/shorts/[\w-]+',
        r'(https?://)?(www\.)?youtu\.be/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/embed/[\w-]+',
    ]
    
    for pattern in youtube_patterns:
        if re.match(pattern, url):
            return True
    return False

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/download', methods=['POST'])
def submit_download():
    data = request.get_json()
    
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided'}), 400
    
    url = data['url'].strip()
    
    if not url:
        return jsonify({'error': 'URL is empty'}), 400
    
    if not is_valid_youtube_url(url):
        return jsonify({'error': 'Invalid YouTube URL'}), 400
    
    download_id = str(uuid.uuid4())
    
    conn = sqlite3.connect('youtube_downloads.db')
    c = conn.cursor()
    c.execute('''INSERT INTO downloads 
                 (id, url, status, created_at)
                 VALUES (?, ?, ?, ?)''',
              (download_id, url, 'not_started', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    # Start worker on first download
    start_worker()
    
    return jsonify({
        'id': download_id,
        'url': url,
        'status': 'not_started',
        'message': 'Download queued successfully'
    }), 201

def get_average_processing_time(cursor):
    """Calculate average processing time from completed downloads in seconds"""
    cursor.execute('''SELECT created_at, processed_at FROM downloads 
                      WHERE status = 'completed' AND processed_at IS NOT NULL
                      ORDER BY processed_at DESC LIMIT 20''')
    completed_rows = cursor.fetchall()
    
    if not completed_rows:
        return 60.0  # Default estimate: 60 seconds per download
    
    total_seconds = 0
    count = 0
    for r in completed_rows:
        try:
            created = datetime.fromisoformat(r['created_at'])
            processed = datetime.fromisoformat(r['processed_at'])
            duration = (processed - created).total_seconds()
            if duration > 0:
                total_seconds += duration
                count += 1
        except:
            continue
    
    return total_seconds / count if count > 0 else 60.0

@app.route('/api/downloads', methods=['GET'])
def get_downloads():
    conn = sqlite3.connect('youtube_downloads.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get average processing time
    avg_time = get_average_processing_time(c)
    
    # Get queue (downloads waiting to be processed, ordered by creation time)
    c.execute('''SELECT id FROM downloads 
                 WHERE status = 'not_started' 
                 ORDER BY created_at ASC''')
    queue_ids = [row['id'] for row in c.fetchall()]
    
    # Check if there's a download currently processing
    c.execute('''SELECT COUNT(*) as count FROM downloads WHERE status = 'processing' ''')
    processing_count = c.fetchone()['count']
    
    c.execute('SELECT * FROM downloads ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    
    downloads = []
    for row in rows:
        # Calculate queue position (1-based) for downloads in queue
        queue_position = None
        estimated_start_seconds = None
        
        if row['status'] == 'not_started' and row['id'] in queue_ids:
            queue_position = queue_ids.index(row['id']) + 1
            # Estimate = (downloads ahead + currently processing) * avg time
            downloads_ahead = queue_position - 1 + processing_count
            estimated_start_seconds = round(downloads_ahead * avg_time)
        
        downloads.append({
            'id': row['id'],
            'url': row['url'],
            'title': row['title'],
            'filepath': row['filepath'],
            'thumbnail': row['thumbnail'],
            'duration': row['duration'],
            'filesize': row['filesize'],
            'status': row['status'],
            'error': row['error'],
            'created_at': row['created_at'],
            'processed_at': row['processed_at'],
            'queue_position': queue_position,
            'estimated_start_seconds': estimated_start_seconds
        })
    
    return jsonify(downloads)

@app.route('/api/downloads/<download_id>', methods=['GET'])
def get_download(download_id):
    conn = sqlite3.connect('youtube_downloads.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM downloads WHERE id = ?', (download_id,))
    row = c.fetchone()
    
    if row is None:
        conn.close()
        return jsonify({'error': 'Download not found'}), 404
    
    # Calculate queue position and estimated time if download is waiting
    queue_position = None
    estimated_start_seconds = None
    
    if row['status'] == 'not_started':
        # Get average processing time
        avg_time = get_average_processing_time(c)
        
        # Count downloads ahead in queue
        c.execute('''SELECT COUNT(*) as position FROM downloads 
                     WHERE status = 'not_started' AND created_at < ?''',
                  (row['created_at'],))
        position_row = c.fetchone()
        queue_position = position_row['position'] + 1  # 1-based position
        
        # Check if there's a download currently processing
        c.execute('''SELECT COUNT(*) as count FROM downloads WHERE status = 'processing' ''')
        processing_count = c.fetchone()['count']
        
        # Estimate = (downloads ahead + currently processing) * avg time
        downloads_ahead = queue_position - 1 + processing_count
        estimated_start_seconds = round(downloads_ahead * avg_time)
    
    conn.close()
    
    return jsonify({
        'id': row['id'],
        'url': row['url'],
        'title': row['title'],
        'filepath': row['filepath'],
        'thumbnail': row['thumbnail'],
        'duration': row['duration'],
        'filesize': row['filesize'],
        'status': row['status'],
        'error': row['error'],
        'created_at': row['created_at'],
        'processed_at': row['processed_at'],
        'queue_position': queue_position,
        'estimated_start_seconds': estimated_start_seconds
    })

@app.route('/api/downloads/<download_id>/video', methods=['GET'])
def download_video(download_id):
    conn = sqlite3.connect('youtube_downloads.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM downloads WHERE id = ?', (download_id,))
    row = c.fetchone()
    conn.close()
    
    if row is None:
        return jsonify({'error': 'Download not found'}), 404
    
    if row['status'] != 'completed':
        return jsonify({'error': 'Video not ready yet'}), 400
    
    filepath = row['filepath']
    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'Video file not found'}), 404
    
    # Get filename for download
    title = row['title'] or 'video'
    # Clean filename
    safe_title = re.sub(r'[^\w\s-]', '', title).strip()
    safe_title = re.sub(r'[-\s]+', '-', safe_title)
    
    ext = os.path.splitext(filepath)[1]
    download_name = f"{safe_title}{ext}"
    
    return send_file(
        filepath,
        as_attachment=True,
        download_name=download_name
    )

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'youtube-downloader',
        'worker_running': worker_running
    })

if __name__ == '__main__':
    init_db()
    print("\n" + "="*60)
    print("🚀 YouTube Downloader API Server")
    print("="*60)
    print("📌 Worker will start automatically on first download")
    print("🗑️  Video files older than 10 days will be auto-deleted")
    print("="*60 + "\n")
    
    # Use PORT environment variable for Hugging Face compatibility
    port = int(os.environ.get('PORT', 7860))
    app.run(debug=False, host='0.0.0.0', port=port)