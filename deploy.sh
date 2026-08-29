#!/usr/bin/env bash
set -euo pipefail

APP_NAME="youtube-downloader"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-7860}"                 # matches the Cloudflare Tunnel route
DOMAIN="yt.voidall.com"
VENV_DIR="$APP_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
YTDLP_DIR="$APP_DIR/bin"
YTDLP_BIN="$YTDLP_DIR/yt-dlp"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}──${NC} $*"; }

echo ""
echo "  YouTube Downloader — VPS deploy (Flask + embedded worker, single origin, Cloudflare Tunnel)"
echo "  ─────────────────────────────────────────────────────────────────────────────"

# ── Port and route safety ─────────────────────────────────────────────────────
# Ports on this VPS. Keep this list in step across all three deploy scripts —
# every one of them refuses to start on a port another app already holds.
#
#   3000  FundsFlee          (fundsflee.voidall.com)
#   7860  youtube-downloader (yt.voidall.com)
#   7861  TTT hf_backend     (ttt.voidall.com)
#
# 7860 is the Hugging Face default, which is why two of these wanted it.

port_holder() {
  ss -ltnp 2>/dev/null | awk -v p=":$1\$" '$4 ~ p {print $NF; exit}'
}

# Refuse to take a port that belongs to something else. pm2 delete + pm2 start
# would otherwise "succeed" and leave this app crash-looping on EADDRINUSE.
assert_port_available() {
  local port="$1" me="$2" holder mypid other
  holder=$(port_holder "$port")
  [ -z "$holder" ] && { info "Port $port is free"; return 0; }

  mypid=$(pm2 pid "$me" 2>/dev/null || true)
  if [ -n "$mypid" ] && printf '%s' "$holder" | grep -q "pid=$mypid"; then
    info "Port $port held by this app's current process — it will be replaced"
    return 0
  fi

  other=$(pm2 jlist 2>/dev/null | python3 -c "
import json, sys
try: procs = json.load(sys.stdin)
except Exception: procs = []
print(' '.join(p['name'] for p in procs if p.get('name') != '$me'
                and p.get('pm2_env', {}).get('status') == 'online'))
" 2>/dev/null || true)

  error "Port $port is already in use by: $holder
  Starting '$me' here would crash-loop on EADDRINUSE, so this stops now.
  Other PM2 apps online: ${other:-none}
  Free the port, or pick another:  PORT=<free-port> bash deploy.sh"
}

# The tunnel rule must say exactly what we think it says. A bare
# `grep -q "$DOMAIN"` passes even when the hostname points at a DIFFERENT port,
# which is the silent failure: the deploy reports success and the tunnel keeps
# serving whatever used to own that port.
check_tunnel_route() {
  python3 - "$1" "$2" "$3" <<'PYEOF'
import re, sys
config, domain, port = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(config).read()
rules = re.findall(r"-\s*hostname:\s*(\S+)\s*\n\s*service:\s*(\S+)", text)
ours = [svc for host, svc in rules if host == domain]
theirs = [host for host, svc in rules if host != domain and svc.endswith(f":{port}")]
if theirs:
    print(f"CLASH {' '.join(theirs)}")
elif not ours:
    print("MISSING")
elif any(svc.endswith(f":{port}") for svc in ours):
    print("OK")
else:
    print(f"WRONGPORT {ours[0]}")
PYEOF
}

step "Port"
command -v ss >/dev/null 2>&1 || warn "'ss' not found (install iproute2) — cannot verify the port is free."
command -v pm2 >/dev/null 2>&1 && assert_port_available "$PORT" "$APP_NAME" || true

# ── 1. Node.js (optional — faster JS runtime for yt-dlp bot-detection bypass) ─
step "Node.js"
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
if command -v node &>/dev/null && [ "$(node -e "console.log(parseInt(process.version.slice(1)))" 2>/dev/null || echo 0)" -ge 18 ]; then
  info "Node.js $(node -v)"
else
  warn "Node.js not found or too old — yt-dlp falls back to its built-in JS runtime."
fi

# ── 2. PM2 ────────────────────────────────────────────────────────────────────
step "PM2"
if ! command -v pm2 &>/dev/null; then
  warn "PM2 not found — installing..."
  npm install -g pm2 2>/dev/null || sudo npm install -g pm2
fi
info "PM2 $(pm2 --version 2>/dev/null)"

# ── 3. Python env (local venv, auto-created) ─────────────────────────────────
step "Python env"
if [ ! -x "$PYTHON" ]; then
  info "Creating venv at $VENV_DIR..."
  python3 -m venv "$VENV_DIR" \
    || error "Could not create venv (install python3-venv: sudo apt install python3-venv)."
fi
info "Python $("$PYTHON" --version 2>&1 | awk '{print $2}')"

# ── 4. ffmpeg ─────────────────────────────────────────────────────────────────
step "ffmpeg"
if ! command -v ffmpeg &>/dev/null; then
  warn "ffmpeg not found — installing..."
  sudo apt-get update -qq && sudo apt-get install -y ffmpeg
fi
info "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"

# ── 5. yt-dlp standalone binary (latest release) ──────────────────────────────
step "yt-dlp binary"
mkdir -p "$YTDLP_DIR"
case "$(uname -m)" in
  aarch64|arm64)     ARCH_BIN="yt-dlp_linux_aarch64" ;;
  armv7l|armv6l)     ARCH_BIN="yt-dlp_linux_armv7l" ;;
  x86_64|amd64)      ARCH_BIN="yt-dlp_linux" ;;
  *) warn "Unknown architecture $(uname -m) — falling back to x86_64 binary."; ARCH_BIN="yt-dlp_linux" ;;
esac
warn "Architecture $(uname -m) → downloading $ARCH_BIN"
curl -fsSL -o "$YTDLP_BIN" "https://github.com/yt-dlp/yt-dlp/releases/latest/download/$ARCH_BIN"
chmod +x "$YTDLP_BIN"
export PATH="$YTDLP_DIR:$PATH"
YTDLP_VERSION="$("$YTDLP_BIN" --version)"
info "yt-dlp $YTDLP_VERSION ($YTDLP_BIN)"

# ── 6. Environment validation ─────────────────────────────────────────────────
step "Environment"
ENV_FILE="$APP_DIR/.env.local"
[ -f "$ENV_FILE" ] || warn ".env.local not found — creating from example (downloads may fail without cookies)."

# Read YOUTUBE_COOKIES (and PORT) from .env.local / .env, trimming quotes.
envget() {
  local v="" f line
  for f in "$ENV_FILE" "$APP_DIR/.env"; do
    [ -f "$f" ] || continue
    line=$(grep -E "^$1=" "$f" | tail -1 || true)
    [ -n "$line" ] && v=$(printf '%s' "${line#*=}" | sed -E 's/^["'\'']//; s/["'\'']$//')
  done
  printf '%s' "$v"
}
COOKIES=$(envget YOUTUBE_COOKIES)
[ -z "$COOKIES" ] && warn "YOUTUBE_COOKIES is not set — set it in .env.local or downloads may fail (bot detection)."
if [ -n "$COOKIES" ]; then
  printf '%s\n' "$COOKIES" > "$APP_DIR/cookies.txt"
  info "cookies.txt written from YOUTUBE_COOKIES"
fi
info "Deploying $DOMAIN → localhost:$PORT"

# ── 7. Python dependencies ────────────────────────────────────────────────────
step "Python dependencies"
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet -r "$APP_DIR/requirements.txt"
mkdir -p "$APP_DIR/downloads"
info "Backend deps installed"

# ── 8. Start / restart the app with PM2 (single worker; embedded queue) ───────
step "PM2 process"
export PORT="$PORT"
pm2 delete "$APP_NAME" 2>/dev/null || true
info "Starting '$APP_NAME' (Flask) on 127.0.0.1:$PORT..."
pm2 start "$PYTHON" \
  --name "$APP_NAME" \
  --cwd "$APP_DIR" \
  --interpreter none \
  --time \
  -- app.py
pm2 save

STARTUP_CMD=$(pm2 startup 2>&1 | grep "sudo" || true)
if [ -n "$STARTUP_CMD" ]; then
  eval "$STARTUP_CMD" && info "PM2 registered for auto-start on reboot" \
    || warn "Could not register PM2 startup — run manually: $STARTUP_CMD"
fi

# ── 9. Cloudflare Tunnel (adds yt.voidall.com, leaves existing rules intact) ─
step "Cloudflare Tunnel"
CF_CONFIG=""
for candidate in /etc/cloudflared/config.yml /root/.cloudflared/config.yml "$HOME/.cloudflared/config.yml"; do
  [ -f "$candidate" ] && { CF_CONFIG="$candidate"; break; }
done

if [ -z "$CF_CONFIG" ]; then
  warn "cloudflared config not found. Ensure this ingress rule exists:"
  echo "    - hostname: $DOMAIN"
  echo "      service: http://localhost:$PORT"
else
  ROUTE=$(check_tunnel_route "$CF_CONFIG" "$DOMAIN" "$PORT")
  case "$ROUTE" in
    OK)
      info "$DOMAIN → localhost:$PORT already routed — no change needed" ;;
    CLASH*)
      error "Port $PORT is already routed to ${ROUTE#CLASH } in $CF_CONFIG.
  Adding $DOMAIN on the same port would give two hostnames one app.
  Pick a free port:  PORT=<free-port> bash deploy.sh" ;;
    WRONGPORT*)
      error "$DOMAIN is routed to ${ROUTE#WRONGPORT } in $CF_CONFIG, not port $PORT.
  This deploy would look successful while the tunnel kept serving the old app.
  Fix the rule by hand, or deploy on that port:  PORT=<that-port> bash deploy.sh" ;;
    MISSING)
      sudo cp "$CF_CONFIG" "${CF_CONFIG}.bak"
      sudo python3 - "$CF_CONFIG" "$DOMAIN" "$PORT" <<'PYEOF'
import sys, re
config_path, domain, port = sys.argv[1], sys.argv[2], sys.argv[3]
new_rule = f"  - hostname: {domain}\n    service: http://localhost:{port}\n"
content = open(config_path).read()
m = re.search(r'^(\s*- service:\s*http_status:\d+\s*)$', content, re.MULTILINE)
content = (content[:m.start()] + new_rule + content[m.start():]) if m else (content.rstrip() + "\n" + new_rule)
open(config_path, 'w').write(content)
print("Config updated.")
PYEOF
      info "Added $DOMAIN → localhost:$PORT (existing rules untouched; backup at ${CF_CONFIG}.bak)"
      systemctl is-active --quiet cloudflared 2>/dev/null && sudo systemctl restart cloudflared && info "cloudflared restarted" \
        || warn "Restart cloudflared manually: sudo systemctl restart cloudflared"
      warn "Ensure DNS for $DOMAIN points at this tunnel:"
      echo "    cloudflared tunnel route dns <TUNNEL_NAME> $DOMAIN" ;;
  esac
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ─────────────────────────────────────────"
info "Done!"
echo ""
echo "  Single origin: Flask serves the API + the built UI on 127.0.0.1:$PORT"
echo "  Tunnel:  https://$DOMAIN"
echo ""
echo "  Useful commands:"
echo "    pm2 logs $APP_NAME        — live app logs"
echo "    pm2 restart $APP_NAME     — restart"
echo "    pm2 status                — process status"
echo ""
echo "  To update: git pull && bash deploy.sh"
echo ""