# Use Python 3.12 (stable and compatible with pydantic-core)
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install pip and dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py database.py fraud_client.py ./
COPY static/ ./static/

# Expose port (Railway will set PORT env var)
EXPOSE 8000
