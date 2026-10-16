#!/usr/bin/env bash
# Home host pulls only completed MyCard evidence through a restricted SSH key.
set -euo pipefail
export PATH="/usr/bin:/bin:$PATH"
archive_root="${MYCARD_HOME_DIR:-/d/file/mycard_archive}"
key="${MYCARD_HOME_KEY:-/c/ProgramData/KamiMan/MyCardOffload/id_ed25519}"
known="${MYCARD_HOME_KNOWN_HOSTS:-/c/ProgramData/KamiMan/MyCardOffload/known_hosts}"
ssh_bin="/usr/bin/ssh"
server="${MYCARD_SERVER:-ubuntu@150.109.237.67}"
mkdir -p "$archive_root/batches"
log="$archive_root/offload.log"
if [[ -f "$log" ]] && (( $(stat -c %s "$log") > 10485760 )); then
  mv -f -- "$log" "$log.1"
fi
exec >>"$log" 2>&1
trap 'printf "%s transfer failed; server originals retained\n" "$(date -Iseconds)"' ERR
ssh_args=(-T -i "$key" -o IdentitiesOnly=yes -o BatchMode=yes
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$known"
  -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 "$server")
for (( attempt=0; attempt<4; attempt++ )); do
  job=$("$ssh_bin" "${ssh_args[@]}" "mycard-offload prepare")
  [[ "$job" == NONE ]] && exit 0
  IFS=$'\t' read -r batch checksum bytes count <<<"$job"
  [[ "$batch" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$ ]]
  [[ "$checksum" =~ ^[0-9a-f]{64}$ && "$bytes" =~ ^[0-9]+$ && "$count" =~ ^[0-9]+$ ]]
  final="$archive_root/batches/$batch.tar"
  part="$final.part"
  if [[ -f "$final" ]]; then
    actual=$(sha256sum "$final"); actual="${actual%% *}"
    [[ "$actual" == "$checksum" ]]
  else
    actual=""
    if [[ -f "$part" && "$(stat -c %s "$part")" == "$bytes" ]]; then
      actual=$(sha256sum "$part"); actual="${actual%% *}"
    fi
    if [[ "$actual" != "$checksum" ]]; then
      : >"$part"
      free_kib=$(df -Pk "$archive_root" | awk 'NR==2 {print $4}')
      (( free_kib * 1024 > bytes + 1073741824 ))
      printf '%s downloading %s bytes=%s matches=%s\n' "$(date -Iseconds)" "$batch" "$bytes" "$count"
      "$ssh_bin" "${ssh_args[@]}" "mycard-offload fetch $batch" >"$part"
      [[ "$(stat -c %s "$part")" == "$bytes" ]]
      actual=$(sha256sum "$part"); actual="${actual%% *}"
      [[ "$actual" == "$checksum" ]]
    fi
    MYCARD_FLUSH_PATH="$(cygpath -w "$part")" /c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -Command '$ErrorActionPreference="Stop"; $stream=[IO.File]::Open($env:MYCARD_FLUSH_PATH,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read); try {$stream.Flush($true)} finally {$stream.Dispose()}'
    mv -- "$part" "$final"
  fi
  printf '%s *%s.tar\n' "$checksum" "$batch" >"$final.sha256"
  removed=$("$ssh_bin" "${ssh_args[@]}" "mycard-offload commit $batch $checksum")
  printf '%s verified %s; released_server_bytes=%s\n' "$(date -Iseconds)" "$batch" "$removed"
done
