#!/bin/bash
# Flexcil 동기화 — NAS 서버(nas-server, ubuntu 계정)에서 실행. cron 10분마다, 수동은 odroid의 `flexcil-sync`
#  1) 구글 드라이브 Flexcil 동기화 폴더 → ~/flexcil/raw     (rclone, 읽기 전용 권한)
#  2) raw → ~/flexcil/out : 앱과 같은 폴더 구조의 필기 PDF   (바뀐 문서만 변환)
#  3) out → /srv/nas/Flexcil/              (앱과 완전히 동일, 지운·바뀐 파일은 백업으로)
#     raw → /srv/nas/Flexcil_백업/원본/     (.flx 원본 사본)
#     공유 폴더 주인(mknas)으로 맞춰 써서 PC(SMB)에서 기존 폴더와 똑같이 보이게 한다
#  4) 상태를 Flexcil_백업/_마지막동기화.txt 에 기록 (언제 마지막으로 성공했는지 눈으로 확인)
set -o pipefail
export LC_ALL=C.UTF-8 TZ=Asia/Seoul    # 상태·로그 시각을 한국 시간으로
H="$HOME/flexcil"; APP="$H/app"; RAW="$H/raw"; OUT="$H/out"; LOG="$H/logs/sync.log"
REMOTE="gdrive:${FLEXCIL_REMOTE_DIR:-$(cat "$H/remote_dir" 2>/dev/null)}"
SHARE="/srv/nas"; OWNER="mknas"
NAS="$SHARE/Flexcil"; BAK="$SHARE/Flexcil_백업"
TS=$(date '+%Y-%m-%d_%H%M%S')
mkdir -p "$H/logs" "$RAW" "$OUT"
exec 9>"$H/.lock"; flock -n 9 || { echo "$(date '+%F %T') 이미 실행 중 — 건너뜀" >> "$LOG"; exit 0; }

log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
status(){ printf '%s\n' "$@" | sudo -n tee "$BAK/_마지막동기화.txt" >/dev/null; sudo -n chown "$OWNER:$OWNER" "$BAK/_마지막동기화.txt"; }
put(){ sudo -n rsync -rt --chown="$OWNER:$OWNER" --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r "$@"; }
fail(){ log "실패: $*"; status "마지막 시도: $(date '+%F %T') — 실패: $*" "마지막 성공: $(cat "$H/last_ok" 2>/dev/null || echo 없음)"; exit 1; }

[ "$REMOTE" = "gdrive:" ] && fail "Flexcil 드라이브 폴더 미설정(~/flexcil/remote_dir)"
sudo -n install -d -o "$OWNER" -g "$OWNER" "$NAS" "$BAK" "$BAK/원본" || fail "공유 폴더 준비(sudo)"
log "시작 ($REMOTE)"
"$HOME/.local/bin/rclone" sync "$REMOTE" "$RAW" --backup-dir "$H/raw_history/$TS" --drive-acknowledge-abuse \
  --log-file "$LOG" --log-level NOTICE || fail "드라이브에서 가져오기"
[ -f "$RAW/documents.list" ] || fail "documents.list 없음 — 폴더 경로 확인"
RES=$("$H/venv/bin/python" "$APP/sync_export.py" "$RAW" "$OUT" 2>&1) || fail "변환: $(echo "$RES" | tail -1)"
echo "$RES" | sed 's/^/  /' >> "$LOG"
put --delete --backup --backup-dir="$BAK/지운·이전 PDF/$TS" "$OUT/" "$NAS/" >> "$LOG" 2>&1 || fail "PDF를 NAS 폴더로 쓰기"
put --delete --backup --backup-dir="$BAK/지운·이전 원본/$TS" "$RAW/" "$BAK/원본/" >> "$LOG" 2>&1 || fail "원본을 NAS 폴더로 쓰기"
date '+%F %T' > "$H/last_ok"
SUM=$(echo "$RES" | tail -1)
status "마지막 성공: $(cat "$H/last_ok")" "$SUM"
find "$H/raw_history" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null
tail -n 5000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"          # 로그 크기 제한
log "끝 — $SUM"
