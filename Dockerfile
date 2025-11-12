# Dockerfile — Modern Python Fly.io build (Heroku yerine)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["python", "bot.py"]
