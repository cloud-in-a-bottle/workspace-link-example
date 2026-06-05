FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx==0.27.2

COPY server.py /app/server.py

EXPOSE 8000
CMD ["python", "/app/server.py"]
