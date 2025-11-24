FROM python:3.11-slim

WORKDIR /app

# Upgrade pip first
RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment vars FIRST
ENV PYTHONUNBUFFERED=1

# Expose port (optional but recommended)
EXPOSE 8000

# Render-compatible startup command
CMD gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 300
