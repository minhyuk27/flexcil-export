#!/bin/bash
# Flexcil 동기화 (oracle1에서 실행) — 10분마다 cron, 수동은 odroid의 `flexcil-sync`
#  1) 구글 드라이브 Flexcil 동기화 폴더 → ~/flexcil/raw   (rclone, 읽기 전용 권한)
#  2) raw → ~/flexcil/out : 앱과 같은 폴더 구조의 필기 PDF   (바뀐 문서만 변환)
#  3) out → odroid:/media/nas/Flexcil/        (앱과 완전히 동일, 지운·바뀐 파일은 백업으로)
#     raw → odroid:/media/nas/Flexcil_백업/원본/  (.flx 원본 사본)
#  4) 상태를 Flexcil_백업/_마지막동기화.txt 에 기록 (언제 마지막으로 성공했는지 눈으로 확인)
set -o pipefail
H="$HOME/flexcil"; APP="$H/app"; RAW="$H/raw"; OUT="$H/out"; LOG="$H/logs/sync.log"
REMOTE="gdrive:${FLEXCIL_REMOTE_DIR:-$(cat "$H/remote_dir" 2>/dev/null)}"
NAS="/media/nas/Flexcil"; BAK="/media/nas/Flexcil_백업"
TS=$(date '+%Y-%m-%d_%H%M%S')
mkdir -p "$H/logs" "$RAW" "$OUT"
exec 9>"$H/.lock"; flock -n 9 || { echo "$(date '+%F %T') 이미 실행 중 — 건너뜀" >> "$LOG"; exit 0; }

log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
fail(){ log "실패: $*"; ssh odroid "mkdir -p '$BAK' && printf '%s\n' '마지막 시도: $(date '+%F %T') — 실패: $*' '마지막 성공: $(cat "$H/last_ok" 2>/dev/null || echo 없음)' > '$BAK/_마지막동기화.txt'" 2>/dev/null; exit 1; }

[ "$REMOTE" = "gdrive:" ] && fail "Flexcil 드라이브 폴더 미설정(~/flexcil/remote_dir)"
log "시작 ($REMOTE)"
"$HOME/.local/bin/rclone" sync "$REMOTE" "$RAW" --backup-dir "$H/raw_history/$TS" --drive-acknowledge-abuse \
  --log-file "$LOG" --log-level NOTICE || fail "드라이브에서 가져오기"
[ -f "$RAW/documents.list" ] || fail "documents.list 없음 — 폴더 경로 확인"
RES=$("$APP/../venv/bin/python" "$APP/sync_export.py" "$RAW" "$OUT" 2>&1) || fail "변환: $(echo "$RES" | tail -1)"
echo "$RES" | sed 's/^/  /' >> "$LOG"
ssh odroid "mkdir -p '$NAS' '$BAK/원본'" || fail "odroid 접속"
rsync -rt --modify-window=2 --delete --backup --backup-dir="$BAK/지운·이전 PDF/$TS" "$OUT/" "odroid:$NAS/" >> "$LOG" 2>&1 || fail "PDF를 NAS로 보내기"
rsync -rt --modify-window=2 --delete --backup --backup-dir="$BAK/지운·이전 원본/$TS" "$RAW/" "odroid:$BAK/원본/" >> "$LOG" 2>&1 || fail "원본을 NAS로 보내기"
date '+%F %T' > "$H/last_ok"
SUM=$(echo "$RES" | tail -1)
ssh odroid "printf '%s\n' '마지막 성공: $(cat "$H/last_ok")' '$SUM' > '$BAK/_마지막동기화.txt'"
find "$H/raw_history" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null
log "끝 — $SUM"
