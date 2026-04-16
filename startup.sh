#!/bin/bash
set -e

# ── Python dependencies ───────────────────────────────────────────────────────
cd /home/container
if [ -f requirements.txt ]; then
    echo "[startup] Installing Python dependencies..."
    pip3 install --no-cache-dir -q -r requirements.txt
fi

# ── Lavalink ──────────────────────────────────────────────────────────────────
if [ -f "/home/container/lavalink/Lavalink.jar" ] && [ "${LAVALINK_ENABLED:-1}" != "0" ]; then
    echo "[startup] Starting Lavalink..."
    cd /home/container/lavalink
    java \
        -Xmx${LAVALINK_MEMORY:-512}m \
        -jar Lavalink.jar \
        &
    LAVALINK_PID=$!
    echo "[startup] Lavalink PID=$LAVALINK_PID — waiting for it to become ready..."

    # Poll /version until Lavalink responds (up to 90 s)
    LAVALINK_PORT="${LAVALINK_PORT:-2333}"
    for i in $(seq 1 30); do
        if curl -sf "http://127.0.0.1:${LAVALINK_PORT}/version" > /dev/null 2>&1; then
            echo "[startup] Lavalink ready after ~$((i * 3))s"
            break
        fi
        sleep 3
    done
else
    echo "[startup] Lavalink.jar not found or LAVALINK_ENABLED=0 — skipping"
fi

# ── Python bot ────────────────────────────────────────────────────────────────
cd /home/container
echo "[startup] Starting Python bot..."
exec python main.py
