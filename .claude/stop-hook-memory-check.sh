#!/bin/bash
# Нагадує оновити MEMORY.md якщо є нові коміти після останнього оновлення
REPO_DIR="/home/user/Iryna_Karmazina"
cd "$REPO_DIR" || exit 0

MEMORY_LAST_COMMIT=$(git log -1 --format="%ct" -- MEMORY.md 2>/dev/null || echo "0")
LATEST_COMMIT=$(git log -1 --format="%ct" 2>/dev/null || echo "0")

if [ "$LATEST_COMMIT" -gt "$MEMORY_LAST_COMMIT" ]; then
    echo '{"systemMessage": "[Памʼять] Є нові зміни в репо після останнього оновлення MEMORY.md. Оновіть MEMORY.md з підсумком сесії і запушайте."}'
fi
