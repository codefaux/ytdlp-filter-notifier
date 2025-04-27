FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Install essential tools
RUN apt-get update && apt-get install -y curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install yt-dlp requests

# Set working directory
WORKDIR /app

# Copy application code
COPY . /app/

# Create mount point for data
VOLUME ["/data"]

# Default command
CMD ["python", "ytdlp-filter-notify.py", "run", "--data-dir", "/data"]
