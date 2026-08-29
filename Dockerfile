FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Node.js for yt-dlp JS runtime
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Download yt-dlp standalone binary (latest release: 2026.08.19)
RUN curl -L -o /usr/local/bin/yt-dlp https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp_linux \
    && chmod +x /usr/local/bin/yt-dlp

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create necessary directories
RUN mkdir -p downloads

# Expose port
EXPOSE 7860

# Run only the Flask app (worker starts automatically on first download)
CMD ["python", "app.py"]