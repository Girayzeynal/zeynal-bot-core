# Minimal Python slim base
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app/

# Entrypoint
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "main:app"]
