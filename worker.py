import sqlite3
import time
import os
import subprocess
import json
from datetime import datetime, timedelta

DOWNLOAD_FOLDER = 'downloads'
POLL_INTERVAL = 3  # seconds

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

def extract_video_info(url):
    """Extract video info using yt-dlp without downloading"""
    try:
        command = [
            'yt-dlp',
            '--dump-json',
            '--no-download',
            '--no-warnings',
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

def download_video(download_id, url):
    """Download video using yt-dlp and return the result"""
    try:
        print(f"🔄 Downloading video from: {url}")
        
        # Download video
        output_template = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.%(ext)s")
        
        command = [
            'yt-dlp',
            '-f', 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            '-o', output_template,
            '--no-playlist',
            '--no-warnings',
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
            return None, f"yt-dlp error: {result.stderr}"
        
        # Find the downloaded file
        downloaded_file = None
        for ext in ['mp4', 'webm', 'mkv', 'avi']:
            potential_file = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.{ext}")
            if os.path.exists(potential_file):
                downloaded_file = potential_file
                break
        
        if not downloaded_file:
            return None, "Downloaded file not found"
        
        # Get file size
        filesize = os.path.getsize(downloaded_file)
        filesize_str = format_filesize(filesize)
        
        return {
            'filepath': downloaded_file,
            'filesize': filesize_str
        }, None
        
    except subprocess.TimeoutExpired:
        return None, "Download timed out after 1 hour"
    except Exception as e:
        print(f"❌ Error downloading video: {str(e)}")
        return None, str(e)

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

def worker_loop():
    """Main worker loop that downloads YouTube videos"""
    print("🤖 YouTube Downloader Worker started. Monitoring for new downloads...")
    print("🗑️  Video files older than 10 days will be auto-deleted\n")
    
    while True:
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
                
                # Download the video
                result, error = download_video(download_id, url)
                
                if result:
                    print(f"✅ Successfully downloaded!")
                    print(f"📦 Size: {result['filesize']}")
                    
                    # Update database with success
                    conn = sqlite3.connect('youtube_downloads.db')
                    c = conn.cursor()
                    c.execute('''UPDATE downloads 
                                 SET status = ?, filepath = ?, filesize = ?, processed_at = ?
                                 WHERE id = ?''',
                              ('completed', result['filepath'], result['filesize'], datetime.now().isoformat(), download_id))
                    conn.commit()
                    conn.close()
                else:
                    print(f"❌ Failed to download: {url}")
                    print(f"Error: {error}")
                    update_status(download_id, 'failed', error=error)
            else:
                # No downloads to process, sleep for a bit
                time.sleep(POLL_INTERVAL)
                
        except Exception as e:
            print(f"⚠️  Worker error: {str(e)}")
            time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    # Create downloads folder if it doesn't exist
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    
    # Initialize database if it doesn't exist
    if not os.path.exists('youtube_downloads.db'):
        print("❌ Database not found. Please run app.py first to initialize.")
    else:
        print("\n" + "="*60)
        print("🚀 Starting YouTube Downloader Worker (Standalone Mode)")
        print("="*60)
        print("⚠️  Note: Worker is now embedded in app.py")
        print("⚠️  This standalone mode is for testing/debugging only")
        print("="*60 + "\n")
        worker_loop()