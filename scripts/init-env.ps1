
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$template = Join-Path $root ".env.example"
$destination = Join-Path $root ".env"

if (Test-Path $destination) {
    throw "El archivo .env ya existe. No se sobrescribira."
}

function New-SecurePassword {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()

    try {
        $rng.GetBytes($bytes)
        return ([System.BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $rng.Dispose()
    }
}

$content = [System.IO.File]::ReadAllText($template)

$content = [regex]::Replace(
    $content,
    '(?m)^([A-Z0-9_]+)=REPLACE_ME\r?$',
    {
        param($match)
        return $match.Groups[1].Value + "=" + (New-SecurePassword)
    }
)

$utf8 = New-Object System.Text.UTF8Encoding($false)

[System.IO.File]::WriteAllText(
    $destination,
    $content,
    $utf8
)

Write-Host "Archivo .env generado correctamente." -ForegroundColor Green
Write-Host "No compartas ni subas este archivo a GitHub."
