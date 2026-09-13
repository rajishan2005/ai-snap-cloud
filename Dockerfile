FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir "qrcode[pil]"

ENV PYTHONUNBUFFERED=1

CMD ["python", "server/server.py"]
