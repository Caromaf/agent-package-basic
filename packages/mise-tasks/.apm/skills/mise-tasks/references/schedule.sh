#!/usr/bin/env bash

#MISE description="定期実行するスケジューラの管理"
#MISE quiet=true
#USAGE arg "[subcommand]" help="実行するサブコマンド" {
#USAGE   choices "install" "status" "uninstall"
#USAGE }
#USAGE flag "-I --interval-minutes <minutes>" help="収集間隔（分、1〜44640。省略時は30）"

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR" || exit 1

# shellcheck source=mise/common.sh
# shellcheck disable=SC1091
source "${ROOT_DIR}/mise/common.sh"

SUBCOMMANDS=(
  $'install\t使用状況を記録するスケジュールを導入する\t-I / --interval-minutes <minutes> で収集間隔を指定可能（既定は30分間隔）'
  $'status\t定期実行するスケジューラの設定状況を表示する'
  $'uninstall\t使用状況を記録するスケジュールを削除する'
)
SUBCOMMAND_NAMES=()
for subcommand_entry in "${SUBCOMMANDS[@]}"; do
  SUBCOMMAND_NAMES+=("${subcommand_entry%%$'\t'*}")
done

subcommand=$(subcommand_or_fail "${usage_subcommand:-}" "${SUBCOMMAND_NAMES[@]}") || exit 1
interval_minutes="${usage_interval_minutes:-}"

if [ -n "$interval_minutes" ] && [ "$subcommand" != "install" ]; then
  print_red "[Error] --interval-minutes は install でのみ指定できます"$'\n' >&2
  exit 1
fi

# サブコマンドの選択を行い、対応する処理は他のスクリプトやモジュールに委譲する
case "$subcommand" in
install)
  if [ -n "$interval_minutes" ]; then
    python -m codex_usage schedule install --interval-minutes "$interval_minutes"
  else
    python -m codex_usage schedule install
  fi
  ;;
status)
  python -m codex_usage schedule status
  ;;
uninstall)
  bash "$ROOT_DIR/mise/scripts/schedule_uninstall.sh"
  ;;
*)
  print_red "[Error] Unknown Subcommand '$subcommand'"$'\n' >&2
  exit 1
  ;;
esac
