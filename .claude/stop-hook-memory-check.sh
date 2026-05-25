#!/bin/bash

input=$(cat)
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // empty')
if [[ "$stop_hook_active" == "true" ]]; then exit 0; fi

cd /home/user/Iryna_Karmazina || exit 0

if ! git rev-parse --git-dir >/dev/null 2>&1; then exit 0; fi
if [[ -z "$(git remote)" ]]; then exit 0; fi

# Якщо є незакомічені зміни або нові файли — комітимо і пушимо мовчки
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    git add -A
    git commit -m "Автозбереження сесії $(date '+%Y-%m-%d %H:%M')" --no-gpg-sign -q
fi

branch=$(git branch --show-current)
if [[ -n "$branch" ]]; then
    unpushed=$(git rev-list "origin/$branch..HEAD" --count 2>/dev/null) || unpushed=0
    if [[ "$unpushed" -gt 0 ]]; then
        git push -u origin "$branch" -q
    fi
fi

exit 0
