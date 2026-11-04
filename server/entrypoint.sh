#!/bin/sh
set -e

# Deploy key (læse/skrive kun til vault-repoet).
# Foretrukket: DEPLOY_KEY_B64 som miljøvariabel i Portainer (base64 af den private nøgle).
# Alternativ: monteret fil i /run/secrets/deploy_key.
mkdir -p /root/.ssh
if [ -n "$DEPLOY_KEY_B64" ]; then
  echo "$DEPLOY_KEY_B64" | base64 -d > /root/.ssh/id_ed25519
elif [ -f /run/secrets/deploy_key ]; then
  cp /run/secrets/deploy_key /root/.ssh/id_ed25519
else
  echo "Mangler deploy key: sæt DEPLOY_KEY_B64" >&2
  exit 1
fi
chmod 600 /root/.ssh/id_ed25519
ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null

if [ ! -d "$VAULT_DIR/.git" ]; then
  git clone "$VAULT_REPO" "$VAULT_DIR"
fi
git -C "$VAULT_DIR" lfs pull

exec python server.py
