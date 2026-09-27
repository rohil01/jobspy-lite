#!/usr/bin/env bash
# Deploy JobSpy Lite to an Oracle Cloud instance (or any Ubuntu server with Docker).
#
# Usage (run on your LOCAL machine, from the repo root):
#   bash deploy/deploy-oci.sh ubuntu@<PUBLIC_IP>
#
# What it does:
#   1. Packs the repo (excluding .venv, node_modules, data, .git) — .env IS included,
#      so create and fill it before deploying.
#   2. Streams it over SSH into ~/app on the server.
#   3. Builds and starts the stack with docker compose (build happens on the server,
#      so the image is always correct for the instance's architecture).
#   4. Health-checks http://<IP>:8000/health from the server itself.
#
# Requires: tar, ssh, scp. On Windows run inside Git Bash / WSL.

set -euo pipefail

TARGET="${1:?Usage: bash deploy/deploy-oci.sh ubuntu@<PUBLIC_IP>}"
REMOTE_DIR="~/app"

echo "==> Packing repo (secrets in .env are included — the target must be trusted)..."
tar czf /tmp/jobspy-lite.tgz \
  --exclude=.venv --exclude=node_modules --exclude=frontend/dist \
  --exclude=.git --exclude=data --exclude=__pycache__ --exclude=.pytest_cache \
  .

echo "==> Uploading to ${TARGET}:${REMOTE_DIR}..."
ssh "$TARGET" "mkdir -p ${REMOTE_DIR}"
scp -q /tmp/jobspy-lite.tgz "$TARGET:/tmp/jobspy-lite.tgz"
rm /tmp/jobspy-lite.tgz

echo "==> Checking Docker on the server..."
if ! ssh "$TARGET" "docker --version >/dev/null 2>&1"; then
  echo "    Docker missing — installing (equivalent to deploy/cloud-init.yaml)..."
  ssh "$TARGET" "sudo apt-get update -y \
    && (sudo apt-get install -y docker.io docker-compose-v2 \
        || sudo apt-get install -y docker.io docker-compose) \
    && sudo systemctl enable --now docker \
    && sudo usermod -aG docker ubuntu \
    && (sudo fallocate -l 2G /swapfile; sudo chmod 600 /swapfile; \
        sudo mkswap /swapfile; sudo swapon /swapfile; \
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab) \
    && (sudo iptables -I INPUT 5 -p tcp --dport 8000 -j ACCEPT; \
        sudo iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT; \
        sudo netfilter-persistent save 2>/dev/null || true)"
  echo "    NOTE: you may need to log out/in once for the docker group to apply;"
  echo "    this script uses sudo-free docker after that."
fi

# Compose v2 plugin ("docker compose") or legacy v1 ("docker-compose")?
DC=$(ssh "$TARGET" "docker compose version >/dev/null 2>&1 && echo 'docker compose' || echo 'docker-compose'")
echo "==> Using compose command: $DC"echo "==> Building + starting on the server (detached — safe on small instances)..."
ssh "$TARGET" "cd ${REMOTE_DIR} && tar xzf /tmp/jobspy-lite.tgz && rm /tmp/jobspy-lite.tgz \
  && nohup ${DC} up --build -d > build.log 2>&1 & echo build started"

echo "==> Polling the build (up to ~15 min) — press Ctrl+C to stop watching; the build continues remotely..."
for i in $(seq 1 60); do
  sleep 15
  HEALTH=$(ssh "$TARGET" "curl -s --max-time 3 http://127.0.0.1:8000/health 2>/dev/null || true")
  if [ -n "$HEALTH" ]; then
    echo "==> Stack is up: $HEALTH"
    break
  fi
  FAILED=$(ssh "$TARGET" "cd ${REMOTE_DIR} && grep -m1 -E '(^|[^a-zA-Z])(ERROR|error:|failed to solve)' build.log 2>/dev/null || true")
  if [ -n "$FAILED" ] && ! ssh "$TARGET" "pgrep -f 'compose.*up --build' >/dev/null"; then
    echo "==> BUILD FAILED: $FAILED"
    ssh "$TARGET" "cd ${REMOTE_DIR} && tail -30 build.log"
    exit 1
  fi
  echo "    ...still building (${i}/60)"
done

if [ -z "${HEALTH:-}" ]; then
  echo "==> Timed out waiting; the build continues on the server. Check later with:"
  echo "    ssh $TARGET 'cd ~/app && tail -20 build.log && curl -s http://127.0.0.1:8000/health'"
  exit 0
fi

echo
echo "==> Done. The dashboard: http://<PUBLIC_IP>:8000"
echo "    If it is unreachable from your browser, check the OCI Security List"
echo "    allows TCP 8000 (see deploy/OCI-SETUP.md step 6)."
