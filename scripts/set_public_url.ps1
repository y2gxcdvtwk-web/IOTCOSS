param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string]$PublicUrl
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
$notificationUri = $PublicUrl.TrimEnd('/') + '/api/v1/mobius/notifications'

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $envPath
}

$content = [System.IO.File]::ReadAllText($envPath)
$line = "MOBIUS_NOTIFICATION_URI=$notificationUri"
if ($content -match '(?m)^MOBIUS_NOTIFICATION_URI=.*$') {
    $content = [regex]::Replace(
        $content,
        '(?m)^MOBIUS_NOTIFICATION_URI=.*$',
        $line
    )
} else {
    $content = $content.TrimEnd() + [Environment]::NewLine + $line + [Environment]::NewLine
}
[System.IO.File]::WriteAllText(
    $envPath,
    $content,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Notification URI configured: $notificationUri"
Write-Host 'Restart FastAPI to validate device containers and create/update subscriptions.'
