FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (sqlite3, tar, unzip)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    tar \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app

# Ensure scripts have execute permissions
RUN chmod +x *.sh *.py

# Generate sample data
RUN ./create_sample_targz_zips.sh

EXPOSE 8080

CMD ["python3", "server.py", "8080"]
