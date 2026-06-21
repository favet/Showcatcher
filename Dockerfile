FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (build-essential, postgres library, make)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    make \
    && rm -rf /var/lib/apt/lists/*

# Pre-install dependencies for caching
COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[dev]

# Copy the rest of the code
COPY . /app

CMD ["python"]
