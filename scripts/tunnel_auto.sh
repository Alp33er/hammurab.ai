#!/bin/bash
# ──────────────────────────────────────────────────────
# Hukuk AI — Cloudflare Tunnel + Vercel Auto-Update
#
# M.I.N.I. restart olduğunda:
# 1. Cloudflared quick tunnel başlatır
# 2. Yeni URL'i yakalar
# 3. Vercel HUKUK_API_URL env var'ını günceller
# 4. Production redeploy tetikler
# 5. Telegram'dan bildirir
# ──────────────────────────────────────────────────────

# ─── KONFİG ──────────────────────────────────────────
VERCEL_TOKEN="vcp_0eYHJbuOMqgDwmZygUNmXTVAVIPbG7FdH2rlvwz2VikLEs909x17vJpv"
VERCEL_PROJECT_ID="prj_TcVW1ZlNVeSbaTP0NjN1runSUnF1"
VERCEL_TEAM_ID="team_IEI77K71m9dedVDW85E31SHC"
BACKEND_PORT=8100
LOG_DIR="/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs"
TUNNEL_LOG="$LOG_DIR/hukuk_tunnel.log"
URL_FILE="$LOG_DIR/hukuk_tunnel_url.txt"
PID_FILE="/tmp/hukuk_tunnel.pid"
NOTIFY_SCRIPT="/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/mini_notify.sh"

mkdir -p "$LOG_DIR"

# ─── FONKSİYONLAR ────────────────────────────────────

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

notify() {
    if [ -f "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" "$1" 2>/dev/null &
    fi
}

# ─── DUPLICATE KONTROLÜ ──────────────────────────────

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        log "Zaten çalışıyor (PID $OLD_PID), çıkış"
        exit 0
    fi
fi
echo $$ > "$PID_FILE"

# Temizlik trap
cleanup() {
    log "Script sonlandırılıyor..."
    rm -f "$PID_FILE"
    kill "$TUNNEL_PID" 2>/dev/null
}
trap cleanup EXIT

# ─── ESKİ PROCESS TEMİZLİĞİ ─────────────────────────

pkill -f "cloudflared tunnel --url http://localhost:$BACKEND_PORT" 2>/dev/null || true
sleep 2

# ─── TUNNEL BAŞLAT ────────────────────────────────────

log "Cloudflared başlatılıyor..."

# stderr ve stdout'u birleştir (cloudflared URL'i stderr'e yazıyor)
/opt/homebrew/bin/cloudflared tunnel --url "http://localhost:$BACKEND_PORT" > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!
log "Cloudflared PID: $TUNNEL_PID"

# URL'in log'da görünmesini bekle (max 45 saniye)
NEW_URL=""
for i in $(seq 1 45); do
    sleep 1
    NEW_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1)
    if [ -n "$NEW_URL" ]; then
        break
    fi
done

if [ -z "$NEW_URL" ]; then
    log "HATA: Tunnel URL bulunamadı (45s timeout)"
    notify "🔴 Hukuk AI tunnel başlatılamadı — URL bulunamadı"
    # Yine de tunnel'i çalışır bırak, belki sonra URL gelir
    wait "$TUNNEL_PID"
    exit 1
fi

log "Tunnel URL: $NEW_URL"

# ─── VERCEL GÜNCELLEME ────────────────────────────────

# Önceki URL ile karşılaştır
OLD_URL=""
if [ -f "$URL_FILE" ]; then
    OLD_URL=$(cat "$URL_FILE" 2>/dev/null)
fi

if [ "$NEW_URL" = "$OLD_URL" ]; then
    log "URL değişmedi, güncelleme gerekmez"
    notify "✅ Hukuk AI tunnel başladı (URL aynı): $NEW_URL"
else
    log "URL değişti: $OLD_URL → $NEW_URL"
    echo "$NEW_URL" > "$URL_FILE"

    # Mevcut HUKUK_API_URL env var ID'sini bul
    ENV_ID=$(curl -s "https://api.vercel.com/v9/projects/$VERCEL_PROJECT_ID/env?teamId=$VERCEL_TEAM_ID" \
        -H "Authorization: Bearer $VERCEL_TOKEN" 2>/dev/null | \
        python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for env in data.get('envs', []):
        if env.get('key') == 'HUKUK_API_URL':
            print(env.get('id', ''))
            break
except: pass
" 2>/dev/null)

    # Eski env var'ı sil (varsa)
    if [ -n "$ENV_ID" ]; then
        curl -s -X DELETE \
            "https://api.vercel.com/v9/projects/$VERCEL_PROJECT_ID/env/$ENV_ID?teamId=$VERCEL_TEAM_ID" \
            -H "Authorization: Bearer $VERCEL_TOKEN" > /dev/null 2>&1
        log "Eski env var silindi (ID: $ENV_ID)"
    fi

    # Yeni env var oluştur
    curl -s -X POST \
        "https://api.vercel.com/v10/projects/$VERCEL_PROJECT_ID/env?teamId=$VERCEL_TEAM_ID" \
        -H "Authorization: Bearer $VERCEL_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"key\":\"HUKUK_API_URL\",\"value\":\"$NEW_URL\",\"type\":\"encrypted\",\"target\":[\"production\",\"preview\"]}" \
        > /dev/null 2>&1
    log "Vercel env güncellendi: HUKUK_API_URL=$NEW_URL"

    # Son production deployment ID'sini bul ve redeploy et
    DEPLOY_ID=$(curl -s "https://api.vercel.com/v6/deployments?projectId=$VERCEL_PROJECT_ID&teamId=$VERCEL_TEAM_ID&limit=1&target=production" \
        -H "Authorization: Bearer $VERCEL_TOKEN" 2>/dev/null | \
        python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    deploys = data.get('deployments', [])
    if deploys:
        print(deploys[0].get('uid', ''))
except: pass
" 2>/dev/null)

    if [ -n "$DEPLOY_ID" ]; then
        curl -s -X POST \
            "https://api.vercel.com/v13/deployments?teamId=$VERCEL_TEAM_ID&forceNew=1" \
            -H "Authorization: Bearer $VERCEL_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"name\":\"playberrygames-web\",\"deploymentId\":\"$DEPLOY_ID\",\"target\":\"production\"}" \
            > /dev/null 2>&1
        log "Vercel redeploy tetiklendi (deploy: $DEPLOY_ID)"
    fi

    notify "🔄 Hukuk AI tunnel URL değişti → Vercel güncellendi + redeploy: $NEW_URL"
fi

# ─── TUNNEL'İ ÇALIŞTIR ────────────────────────────────
log "Tunnel çalışıyor, bekleniyor..."
wait "$TUNNEL_PID"
log "Tunnel process sonlandı"
