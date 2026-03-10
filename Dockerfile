# Use a slim official Python image for small footprint
FROM python:3.11-slim

# Prevent Python from writing .pyc files to disc and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies necessary for psycopg2
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first so we can leverage Docker cache when only app code changes
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# ensure the non-root user we'll switch to owns the files (otherwise they
# are root-owned and un-readable, causing PermissionError at runtime)
RUN useradd --create-home appuser \
    && chown -R appuser:appuser /app

# switch to the non-root user
USER appuser

# Expose the port the app listens on
EXPOSE 8000

# Default command; PORT will be provided by Render automatically.  Use
# shell form so we can leverage shell variable expansion for the default.
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
