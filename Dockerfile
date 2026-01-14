FROM python:3.11-slim

# System deps (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install python deps
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . /app/

# Ensure bookings.db is created on first run when needed (avoid anonymous volume that masks /app)
CMD ["python", "src/bot.py"]
