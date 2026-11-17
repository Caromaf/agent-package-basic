#!/usr/bin/env bash

#MISE description="プロジェクト内の mise 管理ツールを更新する"

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

mise upgrade --bump --no-global
