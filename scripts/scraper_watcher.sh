#!/bin/bash
# Scraper Watcher — Scraper bitince otomatik index + restart + bildirim

HUKUK_DIR="/Users/mini/_BERRY_GAMES/_BERRY_HUKUK"
NOTIFY="/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/mini_notify.sh"
LOG="/tmp/scraper_watcher.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

log "Watcher baslatildi. Scraper bekleniyor..."

while pgrep -f "yargitay_scraper.py" > /dev/null 2>&1; do
    sleep 30
done

log "Scraper bitti!"

KARAR=$(python3 -c "
import json
d = json.load(open('$HUKUK_DIR/scraper/data/yargitay/json/yargitay_kararlar.json'))
print(len(d))
" 2>/dev/null)
log "Toplam karar: $KARAR"

log "RAG index olusturuluyor..."
cd "$HUKUK_DIR"
python3 rag/indexer.py >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    log "HATA: Index olusturulamadi"
    [ -f "$NOTIFY" ] && "$NOTIFY" "Hukuk AI index hatasi!" 2>/dev/null
    exit 1
fi
log "Index tamam"

log "Backend restart..."
launchctl stop com.berrygames.hukuk-backend
sleep 3
launchctl start com.berrygames.hukuk-backend
sleep 5

HEALTH=$(curl -s http://localhost:8100/api/health 2>/dev/null)
if echo "$HEALTH" | grep -q '"ok"'; then
    log "Backend OK"
else
    log "UYARI: Backend health check basarisiz"
fi

[ -f "$NOTIFY" ] && "$NOTIFY" "Yargitay scraper tamamlandi. $KARAR karar. RAG index guncellendi, backend restart edildi." 2>/dev/null
log "Watcher tamamlandi."
