FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (build-essential, postgres library, make)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and src so editable install can find the package
COPY pyproject.toml /app/
COPY src/ /app/src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[dev]

# Copy the rest of the code
COPY . /app

CMD ["python"]
