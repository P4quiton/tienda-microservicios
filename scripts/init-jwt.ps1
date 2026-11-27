
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

$keyDirectory = Join-Path $root "api-usuarios/storage/keys"

$privateKey = Join-Path $keyDirectory "jwt-private.pem"
$publicKey = Join-Path $keyDirectory "jwt-public.pem"

$privateExists = Test-Path $privateKey -PathType Leaf
$publicExists = Test-Path $publicKey -PathType Leaf

if ($privateExists -and $publicExists) {
    Write-Host "Las claves JWT ya existen. No se modificaran." -ForegroundColor Green
    return
}

if ((Test-Path $privateKey) -or (Test-Path $publicKey)) {
    throw "Existe una configuracion parcial de claves JWT. Revisala manualmente."
}

$opensslCommand = Get-Command openssl.exe -ErrorAction SilentlyContinue

if ($opensslCommand) {
    $openssl = $opensslCommand.Source
}
else {
    $openssl = "C:\Program Files\Git\mingw64\bin\openssl.exe"
}

if (-not (Test-Path $openssl -PathType Leaf)) {
    throw "No se encontro OpenSSL. Instala OpenSSL o Git para Windows."
}

New-Item -ItemType Directory -Force $keyDirectory | Out-Null

try {
    & $openssl genpkey `
        -algorithm RSA `
        -pkeyopt rsa_keygen_bits:3072 `
        -out $privateKey

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo generar la clave privada."
    }

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

    & icacls $privateKey /grant:r "${currentUser}:(F)" | Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudieron configurar los permisos de la clave privada."
    }

    & icacls $privateKey /inheritance:r | Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo restringir la herencia de permisos."
    }

    & $openssl pkey `
        -in $privateKey `
        -pubout `
        -out $publicKey

    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo generar la clave publica."
    }

    & $openssl pkey -in $privateKey -check -noout

    if ($LASTEXITCODE -ne 0) {
        throw "La clave privada no es valida."
    }

    & $openssl pkey -pubin -in $publicKey -pubcheck -noout

    if ($LASTEXITCODE -ne 0) {
        throw "La clave publica no es valida."
    }

    Write-Host "Claves JWT RSA de 3072 bits generadas." -ForegroundColor Green
    Write-Host "Nunca compartas ni subas la clave privada."
}
catch {
    Remove-Item $privateKey, $publicKey -Force -ErrorAction SilentlyContinue
    throw
}
