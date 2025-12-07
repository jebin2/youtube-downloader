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

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Update yt-dlp to latest version
RUN pip install --upgrade yt-dlp

# Copy application files
COPY . .

# Create necessary directories
RUN mkdir -p downloads

# Expose port
EXPOSE 7860

# Run only the Flask app (worker starts automatically on first download)
CMD ["python", "app.py"]