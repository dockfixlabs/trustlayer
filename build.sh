#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# TrustLayer — Render build script
# ═══════════════════════════════════════════════════════════════
set -e

echo "==> Installing Python dependencies..."
pip install -r requirements-api.txt

echo "==> Creating /var/data directory (if not exists)..."
mkdir -p /var/data

echo "==> Initialising database..."
python -c "
import os
os.environ.setdefault('TRUSTLAYER_DB_PATH', '/var/data/trustlayer.db')
from core.database import init_db
init_db()
print('Database ready at', os.environ['TRUSTLAYER_DB_PATH'])
"

echo "==> Build complete ✓"
