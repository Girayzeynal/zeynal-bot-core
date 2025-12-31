# Base image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy project
COPY . /app

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TELEGRAM_BOT_TOKEN=""
ENV API_SPORTS_KEY=""
ENV API_SPORTS_BASE="https://v1.basketball.api-sports.io"
ENV BALLDONTLIE_API_KEY=""
ENV ODDS_API_KEY=""
ENV ODDS_API_BASE="https://api.the-odds-api.com"

# Expose port for health checks if needed
EXPOSE 8080

# Run the bot
CMD ["python3", "main.py"]
