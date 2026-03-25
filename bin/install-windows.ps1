$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:KDX_REPO_URL) { $env:KDX_REPO_URL } else { "https://github.com/Neptaverse/Kdx.git" }
$Branch = if ($env:KDX_BRANCH) { $env:KDX_BRANCH } else { "main" }
$InstallRoot = if ($env:KDX_INSTALL_ROOT) { $env:KDX_INSTALL_ROOT } else { Join-Path $env:USERPROFILE ".kdx\src" }
$RepoDir = if ($env:KDX_REPO_DIR) { $env:KDX_REPO_DIR } else { Join-Path $InstallRoot "Kdx" }

function Write-Log {
    param([string]$Message)
    Write-Host "[kdx-install] $Message"
}

function Fail {
    param([string]$Message)
    throw "[kdx-install] ERROR: $Message"
}

function Test-StablePython {
    param(
        [string]$Exe,
        [string[]]$Args
    )
    try {
        & $Exe @Args -c "import sys; raise SystemExit(0 if sys.version_info.releaselevel == 'final' else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Pick-Python {
    $candidates = @()
    if ($env:KDX_PYTHON) {
        $parts = $env:KDX_PYTHON.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
        if ($parts.Count -gt 0) {
            $extraArgs = @()
            if ($parts.Count -gt 1) {
                $extraArgs = $parts[1..($parts.Count - 1)]
            }
            $candidates += @{ Exe = $parts[0]; Args = $extraArgs }
        }
    }
    $candidates += @{ Exe = "py"; Args = @("-3.12") }
    $candidates += @{ Exe = "py"; Args = @("-3.11") }
    $candidates += @{ Exe = "py"; Args = @("-3") }
    $candidates += @{ Exe = "python"; Args = @() }

    foreach ($candidate in $candidates) {
        if (Test-StablePython -Exe $candidate.Exe -Args $candidate.Args) {
            return $candidate
        }
    }
    return $null
}

function Sync-Repo {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    if (-not (Test-Path (Join-Path $RepoDir ".git"))) {
        Write-Log "cloning KDX into $RepoDir"
        git clone $RepoUrl $RepoDir | Out-Null
        return
    }
    Write-Log "using existing clone at $RepoDir"
    $dirty = git -C $RepoDir status --porcelain 2>$null
    if ($dirty) {
        Write-Log "local changes detected; skipping git pull"
        return
    }
    try { git -C $RepoDir remote set-url origin $RepoUrl | Out-Null } catch {}
    try { git -C $RepoDir fetch --depth=1 origin $Branch | Out-Null } catch { git -C $RepoDir fetch origin | Out-Null }
    try { git -C $RepoDir checkout $Branch | Out-Null } catch {}
    try { git -C $RepoDir pull --ff-only | Out-Null } catch {}
}

function Print-PathHint {
    param(
        [string]$Exe,
        [string[]]$Args
    )
    $binDir = & $Exe @Args -c "import site, pathlib; print(pathlib.Path(site.getuserbase()) / 'Scripts')"
    Write-Log "kdx is installed but not on PATH."
    Write-Log "add this directory to user PATH and open a new terminal:"
    Write-Host $binDir
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "missing required command: git"
}

$python = Pick-Python
if (-not $python) {
    Fail "no stable python found (need Python 3.11 or 3.12 final). Install Python and retry."
}

$version = & $python.Exe @($python.Args + @("--version")) 2>&1
Write-Log "using Python: $version"

Sync-Repo
Push-Location $RepoDir
try {
    & $python.Exe @($python.Args + @("bootstrap.py", "--setup-only"))
} finally {
    Pop-Location
}

if (Get-Command kdx -ErrorAction SilentlyContinue) {
    Write-Log "install complete. run: kdx"
} else {
    Print-PathHint -Exe $python.Exe -Args $python.Args
}
