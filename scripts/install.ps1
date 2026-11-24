# SecondThought installer for Windows.
#
#   irm https://raw.githubusercontent.com/ayman-tech/SecondThought/master/scripts/install.ps1 | iex
#
# Sets everything up in your home folder (no admin rights needed) and finishes
# with three clicks in your browser. Run it again any time to update.
#
# Optional, set before running:
#   $env:SECONDTHOUGHT_HOME   where to install (default: ~\SecondThought)
#   $env:SECONDTHOUGHT_MODEL  path to the both-t5 model folder or its .zip
#                             (otherwise it's downloaded from the latest release, if attached there)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # makes downloads much faster

$Repo = "https://github.com/ayman-tech/SecondThought"
$Dir = if ($env:SECONDTHOUGHT_HOME) { $env:SECONDTHOUGHT_HOME } else { Join-Path $HOME "SecondThought" }
$ModelDir = Join-Path $Dir "models\both-t5"
$ExtensionDir = Join-Path $Dir "extension\frontend"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Magenta }
function Note($text) { Write-Host "    $text" }
function Warn($text) { Write-Host "    ! $text" -ForegroundColor Yellow }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed. Fix the error above and run the installer again." } }

Write-Host "SecondThought installer" -ForegroundColor Magenta
Note "Installing to $Dir"

# 1. uv installs Python and the project's packages, without admin rights.
Step "Checking for uv"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Note "Installing uv (https://docs.astral.sh/uv/)..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$HOME\.local\bin;$env:Path"
}
Note "uv $((uv --version) -replace '^uv ', '')"

$drive = (Get-Item ([System.IO.Path]::GetPathRoot($HOME))).PSDrive
if ($drive.Free -lt 4GB) { Warn "Only $([math]::Round($drive.Free / 1GB, 1)) GB free. SecondThought needs about 4 GB." }

# 2. The project: git if it's there, a zip download if not.
Step "Getting SecondThought"
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $Dir ".git")) {
        git -C $Dir pull --ff-only --quiet; Check "Updating"
        Note "Updated to the latest version."
    } else {
        git clone --depth 1 --quiet $Repo $Dir; Check "Downloading"
        Note "Downloaded."
    }
} else {
    $zip = Join-Path $env:TEMP "secondthought.zip"
    $unpacked = Join-Path $env:TEMP "secondthought-unpacked"
    Invoke-WebRequest "$Repo/archive/refs/heads/master.zip" -OutFile $zip
    Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $zip $unpacked
    New-Item -ItemType Directory -Force $Dir | Out-Null
    # Copy over the old files but keep the model and environment already there.
    Copy-Item (Join-Path $unpacked "SecondThought-master\*") $Dir -Recurse -Force
    Remove-Item $zip, $unpacked -Recurse -Force
    Note "Downloaded (no git found, so used the zip)."
}

# 3. Python and packages.
Step "Installing what it needs (a few minutes the first time)"
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue  # always use SecondThought's own environment
Push-Location $Dir
try { uv sync --extra evaluation; Check "Installing packages" } finally { Pop-Location }
Note "Done."

# 4. The rewriting model isn't public yet, so it comes from the team.
Step "Checking for the rewriting model"
if (Test-Path (Join-Path $ModelDir "model.safetensors")) {
    Note "Found models\both-t5."
} elseif ($env:SECONDTHOUGHT_MODEL -and (Test-Path $env:SECONDTHOUGHT_MODEL)) {
    New-Item -ItemType Directory -Force (Split-Path $ModelDir) | Out-Null
    if ($env:SECONDTHOUGHT_MODEL -like "*.zip") {
        Expand-Archive $env:SECONDTHOUGHT_MODEL (Split-Path $ModelDir) -Force
    } else {
        Copy-Item $env:SECONDTHOUGHT_MODEL $ModelDir -Recurse -Force
    }
    if (Test-Path (Join-Path $ModelDir "model.safetensors")) { Note "Copied the model into models\both-t5." }
    else { Warn "Couldn't find model.safetensors in $env:SECONDTHOUGHT_MODEL. Copy the both-t5 folder to $ModelDir yourself." }
} else {
    # The release only has the model once someone attaches both-t5.zip to it.
    $modelZip = Join-Path $env:TEMP "both-t5.zip"
    try {
        Note "Downloading the model (about 230 MB)..."
        Invoke-WebRequest "$Repo/releases/latest/download/both-t5.zip" -OutFile $modelZip
        New-Item -ItemType Directory -Force (Split-Path $ModelDir) | Out-Null
        Expand-Archive $modelZip (Split-Path $ModelDir) -Force
    } catch {
        Note "It isn't available for download yet."
    } finally {
        Remove-Item $modelZip -ErrorAction SilentlyContinue
    }
    if (Test-Path (Join-Path $ModelDir "model.safetensors")) {
        Note "Downloaded the model into models\both-t5."
    } else {
        Warn "One manual step: copy the both-t5 model folder (ask the team) to"
        Warn "  $ModelDir"
    }
}

# 5. A double-clickable way to start the service.
Step "Creating the start script"
$Start = Join-Path $Dir "start-secondthought.cmd"
@"
@echo off
title SecondThought
cd /d "%~dp0"
set VIRTUAL_ENV=
echo Starting SecondThought. Keep this window open while you use it.
uv run python -m extension.api.server
pause
"@ | Set-Content -Encoding ASCII $Start
# And a shortcut on the Desktop, which is where most people will look for it.
$Desktop = [Environment]::GetFolderPath("Desktop")
if ($Desktop -and -not $env:SECONDTHOUGHT_NO_SHORTCUT) {
    "@call `"$Start`"" | Set-Content -Encoding ASCII (Join-Path $Desktop "Start SecondThought.cmd")
    Note "Added Start SecondThought to your Desktop."
    $StartHint = "Double-click Start SecondThought on your Desktop"
} else {
    Note "Double-click start-secondthought in $Dir to start it."
    $StartHint = "Double-click start-secondthought in $Dir"
}

try {
    Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 2 | Out-Null
    Warn "Something is already running on port 8000. Close it (maybe an older SecondThought) before starting."
} catch {}

# 6. Open the browser's extensions page and the folder to load.
Step "Adding it to your browser"
$browsers = @(
    @{ Name = "Chrome"; Page = "chrome://extensions"; Paths = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") },
    @{ Name = "Edge"; Page = "edge://extensions"; Paths = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") },
    @{ Name = "Brave"; Page = "brave://extensions"; Paths = @("$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe", "$env:ProgramFiles\BraveSoftware\Brave-Browser\Application\brave.exe") }
)
$browser = $null
foreach ($candidate in $browsers) {
    $found = $candidate.Paths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if ($found) { $browser = $candidate; $browser.Exe = $found; break }
}
if (-not $env:SECONDTHOUGHT_NO_BROWSER) {
    if ($browser) { Start-Process $browser.Exe $browser.Page }
    Start-Process explorer.exe $ExtensionDir
}
$name = if ($browser) { $browser.Name } else { "your browser" }
$page = if ($browser) { $browser.Page } else { "chrome://extensions" }

Write-Host "`nAlmost there. In $name ($page):" -ForegroundColor Green
Note "1. Switch on Developer mode (top right)."
Note "2. Click Load unpacked and choose this folder:"
Note "   $ExtensionDir"
Note "3. $StartHint, then type something heated in Gmail or Slack."
Write-Host ""
