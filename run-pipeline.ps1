# Pipeline completo: download -> organize -> transcribe+resumir (Windows)
# Llamado por run-pipeline.bat o manualmente.

$ErrorActionPreference = "Continue"
$e = [char]27

$ProjectDir = $PSScriptRoot
$LogDir = Join-Path $ProjectDir "data\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$LogFile = Join-Path $LogDir "$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
$HadErrors = $false

# --- Helpers de output ---

function Write-Header($text) {
    Write-Host ""
    Write-Host "$e[1m$e[36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$e[0m"
    Write-Host "$e[1m  $text$e[0m"
    Write-Host "$e[1m$e[36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$e[0m"
}

function Write-Step($num, $total, $label) {
    Write-Host ""
    Write-Host "  $e[1m[$num/$total]$e[0m $e[32m$label$e[0m"
    Write-Host "  $e[2m$('─' * 46)$e[0m"
}

function Write-Ok($msg)   { Write-Host "  $e[32m+$e[0m $msg" }
function Write-Warn($msg) { Write-Host "  $e[33m!$e[0m $msg" }
function Write-Err($msg)  { Write-Host "  $e[31mX $msg$e[0m" }
function Write-Dim($msg)  { Write-Host "  $e[2m$msg$e[0m" }

function Show-Line($line, $esc) {
    $clean = $line -replace '^\[.*?\]\s*', ''
    if ($line -match '>> TEAM|>> Abriendo|>> Navegando') {
        Write-Host "`r$(' ' * 70)`r  $esc[2m$clean$esc[0m"
    }
    elseif ($line -match '!! |ERROR') {
        Write-Host "`r$(' ' * 70)`r  $esc[31m$clean$esc[0m"
    }
    elseif ($line -match ' ! ') {
        Write-Host "`r$(' ' * 70)`r  $esc[33m$clean$esc[0m"
    }
    elseif ($line -match ' \+ |OK:') {
        Write-Host "`r$(' ' * 70)`r  $esc[32m$clean$esc[0m"
    }
    elseif ($line -match 'Transcribiendo:|Generando resumen|Resumen pendiente') {
        Write-Host "`r$(' ' * 70)`r  $esc[2m$clean$esc[0m"
    }
    elseif ($line -match 'Encontrados|pendientes|Resultado:|Estado:') {
        Write-Host "`r$(' ' * 70)`r  $clean"
    }
    elseif ($line -match 'Contexto:|\.\.\.transcribiendo|Transcripcion completada|Descargando modelo') {
        Write-Host "`r$(' ' * 70)`r  $esc[2m$clean$esc[0m"
    }
    elseif ($line -match '%\||frames/s') {
        if ($line -match '(\d+)%') {
            $pct = [int]$Matches[1]
            $filled = [int]($pct / 5)
            $empty = 20 - $filled
            $bar = ('█' * $filled) + ('░' * $empty)
            Write-Host -NoNewline "`r  $esc[2mTranscribiendo [$bar] $pct%$esc[0m  "
        }
    }
    elseif ($line -match 'SKIP|skip|Listando|archivo:|carpeta:|Crawleando|Library:|Discovering') {
        # Solo al log, no mostrar
    }
    else {
        # Mostrar todo lo demas en dim (mejor que perderlo)
        Write-Host "`r$(' ' * 70)`r  $esc[2m$clean$esc[0m"
    }
}

# Corre un comando Python y muestra output filtrado
function Invoke-Step {
    param($Label, [string[]]$Command)

    & $Command[0] $Command[1..($Command.Length-1)] 2>&1 | ForEach-Object {
        $line = $_.ToString()
        Add-Content -Path $LogFile -Value $line
        Show-Line $line $e
    }
    Write-Host "`r$(' ' * 70)`r" -NoNewline
    return $LASTEXITCODE
}

# --- Validaciones pre-pipeline ---

function Test-Setup {
    $ok = $true

    # Verificar .venv
    if (-not (Test-Path (Join-Path $ProjectDir ".venv\Scripts\python.exe"))) {
        Write-Err "No se encontro el entorno virtual (.venv)"
        Write-Host "  Correr primero: python setup.py"
        $ok = $false
    }

    # Verificar config
    $envFile = Join-Path $ProjectDir ".env"
    $hasTeams = $false
    if (Test-Path $envFile) {
        $content = Get-Content $envFile -Raw
        if ($content -match 'TEAM_PREFIXES=\S+') { $hasTeams = $true }
    }
    if (-not $hasTeams) {
        # Verificar si hay env var del sistema
        if ($env:TEAM_PREFIXES) { $hasTeams = $true }
    }
    if (-not $hasTeams) {
        Write-Err "No hay equipos de Teams configurados"
        Write-Host "  Correr 'python setup.py' o agregar TEAM_PREFIXES al archivo .env"
        $ok = $false
    }

    return $ok
}

# --- Prevenir sleep ---
$SleepPrevented = $false
try {
    Add-Type -TypeDefinition @"
        using System;
        using System.Runtime.InteropServices;
        public class SleepUtil {
            [DllImport("kernel32.dll")]
            public static extern uint SetThreadExecutionState(uint esFlags);
            public const uint ES_CONTINUOUS = 0x80000000;
            public const uint ES_SYSTEM_REQUIRED = 0x00000001;
        }
"@
    [SleepUtil]::SetThreadExecutionState(
        [SleepUtil]::ES_CONTINUOUS -bor [SleepUtil]::ES_SYSTEM_REQUIRED
    ) | Out-Null
    $SleepPrevented = $true
} catch { }

# --- Main ---

Write-Header "UADE Pipeline — $(Get-Date -Format 'dd/MM HH:mm')"
Write-Dim "Log completo: $LogFile"
if ($SleepPrevented) { Write-Dim "Sleep bloqueado" }

Set-Location $ProjectDir

# Validar setup
if (-not (Test-Setup)) {
    Write-Host ""
    Write-Err "Setup incompleto. Correr: python setup.py"
    Write-Host ""
    exit 1
}

& "$ProjectDir\.venv\Scripts\Activate.ps1"

$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

# Paso 1: Descargar
Write-Step 1 4 "Descarga de Teams"
$dlExit = Invoke-Step "Descargando" python -u downloader.py

if ($dlExit -eq 0) {
    Write-Ok "Descarga completada"
} elseif ($dlExit -eq 2) {
    Write-Err "Sesion expirada — correr: uade-login.bat"
    Write-Warn "Continuando con material existente..."
    $HadErrors = $true
} else {
    Write-Err "Descarga fallo (exit $dlExit)"
    Write-Warn "Continuando con material existente..."
    $HadErrors = $true
}

# Paso 2: Organizar
Write-Step 2 4 "Organizacion de archivos"
$orgExit = Invoke-Step "Organizando" python -u organizer.py
if ($orgExit -eq 0) {
    Write-Ok "Organizacion completada"
} else {
    Write-Err "Organizacion fallo (exit $orgExit)"
    $HadErrors = $true
}

# Paso 3: Transcribir + Resumir
Write-Step 3 4 "Transcripcion + Resumenes"
$trExit = Invoke-Step "Transcribiendo" python -u transcriber.py
if ($trExit -eq 0) {
    Write-Ok "Transcripcion completada"
} else {
    Write-Err "Transcripcion fallo (exit $trExit)"
    $HadErrors = $true
}

# Paso 4: Status
Write-Step 4 4 "Estado del pipeline"
Write-Host ""
python -u status.py 2>&1 | Tee-Object -FilePath $LogFile -Append

$Stopwatch.Stop()
$elapsed = $Stopwatch.Elapsed
Write-Header "Pipeline completado — $($elapsed.Minutes)m $($elapsed.Seconds)s"

if ($HadErrors) {
    Write-Host ""
    Write-Warn "Hubo errores durante el pipeline."
    Write-Warn "Log completo en: $LogFile"
    Write-Warn "Si necesitas ayuda, copia el contenido del log y envialo."
}

# Restaurar sleep
if ($SleepPrevented) {
    try {
        [SleepUtil]::SetThreadExecutionState([SleepUtil]::ES_CONTINUOUS) | Out-Null
    } catch { }
}

# Limpiar logs viejos (>30 dias)
Get-ChildItem $LogDir -Filter "*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -ErrorAction SilentlyContinue
