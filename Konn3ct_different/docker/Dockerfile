# Use official Python base image
FROM python:3.10-slim

# Install system dependencies, Node.js, and LibreOffice Writer
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    libreoffice-writer \
    --no-install-recommends \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy python requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Additional packages for web app
RUN pip install --no-cache-dir gunicorn flask-socketio eventlet PyJWT

# Copy package.json and install node dependencies
COPY package.json .
RUN npm install

# Copy application source code
COPY . .

# Initialize DB tables (creates konn3ct.db if not present)
RUN python scripts/seed_db.py

# Expose port 8000 (Gunicorn)
EXPOSE 8000

# Command to run application via Gunicorn with Eventlet websocket support
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "-b", "0.0.0.0:8000", "run:app"]
