#!/bin/sh
set -e

# Deploy key (læse/skrive kun til vault-repoet) monteres som secret
mkdir -p /root/.ssh
cp /run/secrets/deploy_key /root/.ssh/id_ed25519
chmod 600 /root/.ssh/id_ed25519
ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null

if [ ! -d "$VAULT_DIR/.git" ]; then
  git clone "$VAULT_REPO" "$VAULT_DIR"
fi
git -C "$VAULT_DIR" lfs pull

exec python server.py
