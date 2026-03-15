FROM python:3.11-slim

WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create temp directories (tokens/ and downloads/ will be mounted as volumes)
RUN mkdir -p downloads tokens

CMD ["python", "main.py"]
