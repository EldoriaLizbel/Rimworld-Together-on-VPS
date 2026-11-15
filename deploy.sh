#!/bin/sh
set -eu

cd "$(dirname "$0")"
deploy_dir=.rwt-deploy
compose_env="$deploy_dir/compose.env"

say() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
fail() { say "$*" >&2; exit 1; }
as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}
docker_cmd() {
    if [ "${use_sudo_docker:-0}" = 1 ]; then as_root docker "$@"; else docker "$@"; fi
}
compose() { docker_cmd compose --ansi never --env-file "$compose_env" "$@"; }
port() {
    case "$1" in ''|*[!0-9]*) fail "Invalid TCP port: $1";; esac
    [ "${#1}" -le 5 ] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ] || fail "Invalid TCP port: $1"
}
secret() { od -An -N 32 -tx1 /dev/urandom | tr -d ' \n'; }
detect_public_ipv4() {
    if command -v curl >/dev/null 2>&1; then
        address=$(curl -4fsS --connect-timeout 4 --max-time 8 https://api.ipify.org) || return 1
    elif command -v wget >/dev/null 2>&1; then
        address=$(wget -4 --timeout=5 --tries=1 -qO- https://api.ipify.org) || return 1
    else
        return 1
    fi
    printf '%s\n' "$address" | awk -F. '
        NR == 1 && NF == 4 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ && $4 ~ /^[0-9]+$/ &&
        $1 <= 255 && $2 <= 255 && $3 <= 255 && $4 <= 255 { ip = $0 }
        END { if (NR != 1 || ip == "") exit 1; print ip }'
}

if [ "${1:-}" = "--help" ]; then
    printf '%s\n' 'Usage: [RIMWORLD_PUBLIC_HOST=IP_OR_DNS] sh deploy.sh' \
        'First-run overrides: RWT_PROJECT_NAME, RIMWORLD_HOST_BIND, RIMWORLD_HOST_PORT, RIMWORLD_WEB_PORT, BEEKEEPER_WEB_PORT.' \
        'Existing deployments reuse .rwt-deploy/*.env. Game data lives in .rwt-deploy/game.'
    exit 0
fi
[ "$#" -eq 0 ] || fail "Unexpected argument. Run sh deploy.sh --help."
[ -f compose.yaml ] && [ -f frontend_1/package-lock.json ] && [ -f apps/api/Dockerfile ] \
    || fail "Run this script from a complete checkout of RimWorld Together on VPS."

say 'Checking Docker Engine and Compose'
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    [ -r /etc/os-release ] || fail 'Install Docker Engine and its Compose plugin on this host.'
    . /etc/os-release
    case "${ID:-}" in ubuntu|debian) ;; *) fail 'Automatic Docker installation supports Ubuntu and Debian. Install Docker Engine and Compose first on this distro.';; esac
    distro_code=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
    [ -n "$distro_code" ] || fail 'Unable to identify the distribution release.'
    say "Installing Docker packages from Docker's official $ID repository"
    as_root apt-get update
    as_root apt-get install -y ca-certificates curl
    as_root install -m 0755 -d /etc/apt/keyrings
    as_root curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
    as_root chmod a+r /etc/apt/keyrings/docker.asc
    printf '%s\n' "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $distro_code stable" \
        | as_root tee /etc/apt/sources.list.d/docker.list >/dev/null
    as_root apt-get update
    as_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    as_root systemctl enable --now docker
fi
if ! docker info >/dev/null 2>&1; then
    use_sudo_docker=1
    say 'Checking Docker with elevated privileges'
    docker_cmd info >/dev/null || fail 'Docker is unavailable. Check the engine service and Docker permissions.'
fi
docker_cmd compose version
docker_cmd compose up --help | grep -q -- '--wait-timeout' || fail 'Upgrade Docker Compose to a version with --wait-timeout.'
case "$(docker_cmd info --format '{{.OSType}}/{{.Architecture}}')" in
    linux/x86_64|linux/amd64) ;;
    *) fail 'This release of the official RimWorld Together image requires a Linux x86-64 Docker host.' ;;
esac

if [ ! -e "$deploy_dir" ]; then
    project=${RWT_PROJECT_NAME:-rimworld-together-vps}
    public_host=${RIMWORLD_PUBLIC_HOST:-}
    game_bind=${RIMWORLD_HOST_BIND:-0.0.0.0}
    game_port=${RIMWORLD_HOST_PORT:-25555}
    web_port=${RIMWORLD_WEB_PORT:-10005}
    beekeeper_port=${BEEKEEPER_WEB_PORT:-5800}
    case "$project" in ''|[!a-z0-9]*|*[!a-z0-9_-]*) fail 'Invalid Compose project name.';; esac
    case "$public_host" in *[!A-Za-z0-9.:-]*) fail 'Use an IP address or DNS name without a URL scheme for RIMWORLD_PUBLIC_HOST.';; esac
    if [ -z "$public_host" ]; then
        say 'Detecting this VPS public IPv4 address'
        if public_host=$(detect_public_ipv4); then
            say "Detected public IPv4: $public_host"
        else
            say 'Public IPv4 detection unavailable. Use your provider dashboard to look up the game address.'
        fi
    fi
    case "$game_bind" in ''|*[!0-9.]*) fail 'RIMWORLD_HOST_BIND must be an IPv4 address.';; esac
    port "$game_port"; port "$web_port"; port "$beekeeper_port"
    [ "$game_port" -ne "$web_port" ] && [ "$game_port" -ne "$beekeeper_port" ] && [ "$web_port" -ne "$beekeeper_port" ] \
        || fail 'Choose distinct game, dashboard, and Beekeeper ports.'
    say "Generating deployment configuration for $project"
    umask 077
    scratch=$(mktemp -d .rwt-deploy.XXXXXX)
    trap 'rm -f "$scratch/compose.env" "$scratch/postgres.env" "$scratch/web.env"; rmdir "$scratch" 2>/dev/null || :' EXIT
    web_password=$(secret)
    cat > "$scratch/compose.env" <<EOF
COMPOSE_PROJECT_NAME=$project
RWT_POSTGRES_ENV_FILE=./$deploy_dir/postgres.env
RWT_WEB_ENV_FILE=./$deploy_dir/web.env
RWT_GAME_DATA=./$deploy_dir/game
RIMWORLD_API_DB_NAME=app_db
RIMWORLD_API_DB_PASSWORD=$(secret)
RIMWORLD_API_TOKEN=$(secret)
RIMWORLD_HOST_BIND=$game_bind
RIMWORLD_HOST_PORT=$game_port
RIMWORLD_PUBLIC_HOST=$public_host
RIMWORLD_WEB_PORT=$web_port
BEEKEEPER_WEB_PORT=$beekeeper_port
EOF
    cat > "$scratch/postgres.env" <<EOF
POSTGRES_USER=app_user
POSTGRES_DB=app_db
POSTGRES_PASSWORD=$(secret)
RIMWORLD_ADMIN_PASSWORD=$(secret)
RIMWORLD_WEB_DB_PASSWORD=$web_password
TZ=Asia/Bangkok
EOF
    cat > "$scratch/web.env" <<EOF
DATABASE_URL=postgresql://rimworld_web:$web_password@postgres:5432/app_db
SESSION_SECRET=$(secret)
COOKIE_SECURE=false
EOF
    mv -T "$scratch" "$deploy_dir"
    trap - EXIT
else
    say 'Reusing saved deployment settings and credentials'
fi
for file in "$compose_env" "$deploy_dir/postgres.env" "$deploy_dir/web.env"; do
    [ -s "$file" ] || fail "Missing $file. Restore it from the existing deployment before continuing."
done
# The deployment directory hides this mount from other host users. Inside the
# container, the read-only API uses a different UID from the game process.
install -d -m 0755 "$deploy_dir/game"

say 'Validating Compose configuration and internal network'
compose config --quiet
say 'Building application images'
BUILDKIT_PROGRESS=plain compose build
say 'Starting PostgreSQL and waiting for readiness'
compose up -d --wait --wait-timeout 150 postgres
for migration in 003_app_role.sql 004_game_dashboard.sql 005_player_online.sql 006_worker_metrics.sql; do
    say "Applying $migration"
    compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        < "postgresql_1/postgres-docker/sql/$migration"
done
say 'Starting dashboard, API, Beekeeper Studio, and RimWorld'
if ! compose up -d --wait --wait-timeout 180; then
    compose ps
    fail 'One or more services did not become ready. Inspect the affected service with docker compose --env-file .rwt-deploy/compose.env logs SERVICE.'
fi

say 'Checking service discovery and game TCP from inside the stack'
compose exec -T web node - <<'NODE'
const net = require("node:net");
const { Client } = require("pg");
async function verify() {
  for (const [service, url] of [
    ["Dashboard", "http://127.0.0.1:3000/api/health"],
    ["FastAPI", "http://api:8000/healthz"],
    ["Beekeeper Studio", "http://beekeeper:5800/"],
  ]) {
    const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error(`${service} returned HTTP ${response.status}`);
    console.log(`${service}: HTTP ${response.status}`);
  }
  const db = new Client({ connectionString: process.env.DATABASE_URL, connectionTimeoutMillis: 5000 });
  await db.connect();
  try { await db.query("SELECT username FROM user_profile LIMIT 1"); } finally { await db.end(); }
  console.log("Dashboard → PostgreSQL: authenticated query passed");
  await new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: "rimworld", port: 25555, timeout: 5000 });
    socket.once("error", reject);
    socket.once("timeout", () => socket.destroy(new Error("Game TCP probe timed out")));
    socket.once("connect", () => { socket.destroy(); resolve(); });
  });
  console.log("Dashboard → RimWorld: TCP listener reachable");
}
verify().catch(error => { console.error(error.message); process.exitCode = 1; });
NODE
say 'Checking the initial game configuration snapshot in PostgreSQL'
attempt=0
while [ "$(compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT EXISTS (SELECT 1 FROM world_config WHERE boot_id IS NOT NULL)"')" != t ]; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 15 ] || fail 'The API did not synchronize the game configuration. Inspect the API logs and game data mount.'
    sleep 2
done
compose ps
public_host=${RIMWORLD_PUBLIC_HOST:-$(sed -n 's/^RIMWORLD_PUBLIC_HOST=//p' "$compose_env")}
game_port=$(sed -n 's/^RIMWORLD_HOST_PORT=//p' "$compose_env")
web_port=$(sed -n 's/^RIMWORLD_WEB_PORT=//p' "$compose_env")
beekeeper_port=$(sed -n 's/^BEEKEEPER_WEB_PORT=//p' "$compose_env")
say "Ready. Game endpoint: ${public_host:-<VPS-public-IP>}:${game_port}/tcp"
say "Allow inbound TCP $game_port in your VPS provider's firewall for external players."
say "Dashboard and Beekeeper are host-local on $web_port and $beekeeper_port. From your computer:"
printf '  ssh -N -L %s:127.0.0.1:%s -L %s:127.0.0.1:%s user@%s\n' \
    "$web_port" "$web_port" "$beekeeper_port" "$beekeeper_port" "${public_host:-<VPS-public-IP>}"
say "Dashboard user: rimworldtogether. Initial password: RIMWORLD_ADMIN_PASSWORD in $deploy_dir/postgres.env"
