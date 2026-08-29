$ErrorActionPreference = "Stop"

$launcher = Join-Path $PSScriptRoot "shopify-dev.ps1"
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Missing Shopify dev launcher: $launcher"
}

& $launcher -SelfTest
if ($LASTEXITCODE -ne 0) {
    throw "Shopify dev launcher self-test failed"
}

$viteConfig = Get-Content -LiteralPath (
    Join-Path (Split-Path -Parent $PSScriptRoot) "frontend/vite.config.ts"
) -Raw
if ($viteConfig -notmatch 'allowedHosts:\s*\["\.trycloudflare\.com"\]') {
    throw "Vite must allow Cloudflare quick-tunnel subdomains without a hard-coded host"
}
