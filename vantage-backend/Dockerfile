FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy source
COPY server/ ./server/
COPY sdk/vantage/ ./vantage/

# Non-root user
RUN useradd -m vantage && chown -R vantage:vantage /app
USER vantage

EXPOSE 8000
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
