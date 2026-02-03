#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
metadata_dir="$repo_root/METADATA"
backup_dir="$metadata_dir/backups"

mkdir -p "$backup_dir"

ts=$(date -u +"%Y%m%dT%H%M%SZ")

for name in metadata.csv collections.json; do
  src="$metadata_dir/$name"
  if [ -f "$src" ]; then
    base="${name%.*}"
    ext="${name##*.}"
    cp "$src" "$backup_dir/${base}-${ts}.${ext}"
  fi
done

echo "Backup complete: $backup_dir"
