[CmdletBinding()]
param(
    [switch]$SelfTest,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArguments
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$callbackPath = "/api/v1/shopify/oauth/callback"

function Get-ShopifyCommand {
    $runningOnWindows = $env:OS -eq "Windows_NT"
    if ($runningOnWindows) {
        $command = Get-Command "shopify.cmd" -ErrorAction Stop
    }
    else {
        $command = Get-Command "shopify" -ErrorAction Stop
    }
    return $command.Source
}

function Get-ShopifyTunnelUrl {
    param([string]$Line)

    $match = [regex]::Match(
        $Line,
        "https://[a-z0-9-]+\.trycloudflare\.com",
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    if (-not $match.Success) {
        return $null
    }
    return $match.Value.ToLowerInvariant().TrimEnd("/")
}

function Get-ShopifyRedirectUri {
    param([string]$TunnelUrl)

    return "$($TunnelUrl.TrimEnd('/'))$callbackPath"
}

if ($SelfTest) {
    $sampleLine = "15:24:59 | app_home | Using URL: https://sample-tunnel.trycloudflare.com"
    $tunnelUrl = Get-ShopifyTunnelUrl $sampleLine
    $redirectUri = Get-ShopifyRedirectUri $tunnelUrl
    if ($tunnelUrl -ne "https://sample-tunnel.trycloudflare.com") {
        throw "Tunnel URL parser regression"
    }
    if ($redirectUri -ne "https://sample-tunnel.trycloudflare.com/api/v1/shopify/oauth/callback") {
        throw "Redirect URI builder regression"
    }
    if ($null -ne (Get-ShopifyTunnelUrl "Preview URL: https://admin.shopify.com/store/test")) {
        throw "Non-tunnel URL must not be accepted"
    }
    $shopifyCommand = Get-ShopifyCommand
    if ($env:OS -eq "Windows_NT" -and -not $shopifyCommand.EndsWith("shopify.cmd")) {
        throw "Windows must bypass the npm shopify.ps1 wrapper"
    }
    Write-Output "Shopify dev launcher self-test passed"
    exit 0
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$tunnelConfigured = $false
$lastTunnelUrl = $null
$shopifyArguments = @(
    "app",
    "dev",
    "--skip-dependencies-installation",
    "--no-color"
) + $ExtraArguments
$shopifyCommand = Get-ShopifyCommand

Push-Location $repositoryRoot
try {
    if (-not (Test-Path -LiteralPath "compose.yaml")) {
        throw "compose.yaml was not found in $repositoryRoot"
    }

    Write-Host "Stopping the Docker frontend so Shopify CLI can use port 3000..."
    & docker compose stop frontend
    if ($LASTEXITCODE -ne 0) {
        throw "Could not stop the Docker frontend"
    }

    Write-Host "Starting Shopify CLI. Press Ctrl+C to stop and restore Docker services."
    & $shopifyCommand @shopifyArguments 2>&1 | ForEach-Object {
        $line = $_.ToString()
        Write-Host $line

        $tunnelUrl = Get-ShopifyTunnelUrl $line
        if ($null -eq $tunnelUrl -or $tunnelUrl -eq $lastTunnelUrl) {
            return
        }

        $lastTunnelUrl = $tunnelUrl
        $redirectUri = Get-ShopifyRedirectUri $tunnelUrl
        $env:SHOPIFY_REDIRECT_URI = $redirectUri

        Write-Host "Synchronizing backend OAuth redirect URI with $tunnelUrl ..."
        & docker compose up -d --force-recreate backend worker
        if ($LASTEXITCODE -ne 0) {
            throw "Could not recreate backend and worker with the tunnel redirect URI"
        }

        $loadedRedirectUri = (& docker compose exec -T backend python -c `
            "from app.config import get_settings; print(get_settings().shopify_redirect_uri)"
        ).Trim()
        if ($loadedRedirectUri -ne $redirectUri) {
            throw "Backend redirect URI did not synchronize with the Shopify tunnel"
        }

        $tunnelConfigured = $true
        Write-Host "Backend OAuth callback synchronized: $redirectUri"
    }

    if ($LASTEXITCODE -ne 0) {
        throw "shopify app dev exited with code $LASTEXITCODE"
    }
}
finally {
    if (Test-Path Env:SHOPIFY_REDIRECT_URI) {
        Remove-Item Env:SHOPIFY_REDIRECT_URI
    }

    if ($tunnelConfigured) {
        Write-Host "Restoring backend, worker, and frontend from .env..."
        & docker compose up -d --force-recreate backend worker frontend
    }
    else {
        Write-Host "Restoring the Docker frontend..."
        & docker compose start frontend
    }
    Pop-Location
}
