#MISE description="プロジェクト内の mise 管理ツールを更新する"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Push-Location -LiteralPath $projectRoot
$exitCode = 0
try {
    mise upgrade --no-global
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    exit $exitCode
}
