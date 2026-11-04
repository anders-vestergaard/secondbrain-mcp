FROM python:3.14-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git git-lfs ripgrep openssh-client ca-certificates \
 && git lfs install --system \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV VAULT_DIR=/vault PORT=8000
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
