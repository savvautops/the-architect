FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/*
ENV CHROME_BIN=/usr/bin/chromium
WORKDIR /app
COPY browserd.py .
COPY ui ./ui
EXPOSE 8901
CMD ["python3", "browserd.py"]
