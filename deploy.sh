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
    printf '%s\n' 'Usage: [RIMWORLD_PUBLIC_HOST=IP_OR_DNS] sh deploy.sh [--prepare|--maintenance|--dry-run]' \
        '--prepare installs Docker if needed and creates the private environment without starting services.' \
        '--maintenance allows replacement of an existing game after a verified backup.' \
        'Existing deployments reuse .rwt-deploy/*.env. Game data lives in .rwt-deploy/game.'
    exit 0
fi
case "${1:-}" in ''|--prepare|--maintenance|--dry-run) ;; *) fail 'Run sh deploy.sh --help.';; esac
[ "$#" -le 1 ] || fail 'Run sh deploy.sh --help.'
[ "${1:-}" != --dry-run ] || exec python3 scripts/ops.py bootstrap --dry-run
[ -f compose.yaml ] && [ -f frontend_1/package-lock.json ] && [ -f apps/api/Dockerfile ] \
    || fail "Run this script from a complete checkout of RimWorld Together on VPS."

say 'Checking Docker Engine and Compose'
if ! command -v python3 >/dev/null 2>&1; then
    as_root apt-get update
    as_root apt-get install -y python3
fi
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    [ -r /etc/os-release ] || fail 'Install Docker Engine and its Compose plugin on this host.'
    # shellcheck source=/dev/null
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

[ ! -L "$deploy_dir" ] || fail 'The deployment directory must not be a symlink.'
if [ ! -e "$deploy_dir" ]; then
    project=${RWT_PROJECT_NAME:-rimworld-together-vps}
    public_host=${RIMWORLD_PUBLIC_HOST:-}
    game_bind=${RIMWORLD_HOST_BIND:-0.0.0.0}
    game_port=${RIMWORLD_HOST_PORT:-25555}
    web_port=${RIMWORLD_WEB_PORT:-10005}
    web_bind=${RIMWORLD_WEB_BIND:-127.0.0.1}
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
    trap 'exit 130' INT TERM
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
RIMWORLD_WEB_BIND=$web_bind
BEEKEEPER_WEB_PORT=$beekeeper_port
RWT_BEEKEEPER_ENABLED=${RWT_BEEKEEPER_ENABLED:-1}
POSTGRES_VERSION=16.14-bookworm@sha256:64154d0babcb1741988719e703419af0382b19953706149f9872fbd0f438efa8
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
    trap - EXIT INT TERM
else
    say 'Reusing saved deployment settings and credentials'
fi
for file in "$compose_env" "$deploy_dir/postgres.env" "$deploy_dir/web.env"; do
    [ -s "$file" ] || fail "Missing $file. Restore it from the existing deployment before continuing."
done
# The deployment directory hides this mount from other host users. Inside the
# container, the read-only API uses a different UID from the game process.
[ ! -L "$deploy_dir/game" ] || fail 'The game data directory must not be a symlink.'
[ -d "$deploy_dir/game" ] || install -d -m 0755 "$deploy_dir/game"
if [ "${1:-}" = --prepare ]; then
    python3 scripts/ops.py preflight
    say 'Environment prepared. No services were started.'
    exit 0
fi
python3 scripts/ops.py bootstrap "$@"
public_host=$(sed -n 's/^RIMWORLD_PUBLIC_HOST=//p' "$compose_env")
game_port=$(sed -n 's/^RIMWORLD_HOST_PORT=//p' "$compose_env")
web_port=$(sed -n 's/^RIMWORLD_WEB_PORT=//p' "$compose_env")
beekeeper_port=$(sed -n 's/^BEEKEEPER_WEB_PORT=//p' "$compose_env")
say "Ready. Game endpoint: ${public_host:-<VPS-public-IP>}:${game_port}/tcp"
say "Allow inbound TCP $game_port in your VPS provider's firewall for external players."
say "Use the dashboard and Beekeeper through SSH when bound to loopback. From your computer:"
printf '  ssh -N -L %s:127.0.0.1:%s -L %s:127.0.0.1:%s user@%s\n' \
    "$web_port" "$web_port" "$beekeeper_port" "$beekeeper_port" "${public_host:-<VPS-public-IP>}"
say "Dashboard user: rimworldtogether. Initial password: RIMWORLD_ADMIN_PASSWORD in $deploy_dir/postgres.env"
