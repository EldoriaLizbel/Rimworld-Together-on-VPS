#!/bin/sh
# Install through a forced-command authorized_keys entry. Accept only the
# bounded release protocol emitted by deploy-production.yml.
set -efu
unset CDPATH
request=${SSH_ORIGINAL_COMMAND:-}
old_ifs=$IFS
IFS=' '
# Intentional fixed-protocol tokenization with globbing disabled.
# shellcheck disable=SC2086
set -- $request
IFS=$old_ifs
[ "$#" -eq 5 ] && [ "$1" = rwt-deploy ] || { printf '%s\n' 'Expected the rwt-deploy protocol.' >&2; exit 2; }
release=$2
scope=$3
maintenance=$4
dry_run=$5
[ "${#release}" -eq 40 ] || exit 2
case "$release" in *[!0-9a-f]*) exit 2;; esac
case "$scope" in all|app|web|api|rimworld|beekeeper) ;; *) exit 2;; esac
case "$maintenance:$dry_run" in 0:0|0:1|1:0|1:1) ;; *) exit 2;; esac
set -- --version "$release" --scope "$scope"
[ "$maintenance" = 0 ] || set -- "$@" --maintenance
[ "$dry_run" = 0 ] || set -- "$@" --dry-run
exec sh "$(dirname "$0")/deploy-release.sh" "$@"
