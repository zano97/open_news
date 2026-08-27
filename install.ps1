# Open News — installazione in una riga su Windows (PowerShell):
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/zano97/open_news/main/install.ps1 | iex"
#
# Non serve Docker: lo script scarica l'app, si procura Python da solo (via
# uv), crea il comando `opennews` e la voce nel menu Start, scarica le
# notizie e apre il giornale nel browser.
# Varianti (imposta prima la variabile):  $env:OPENNEWS_DEMO=1  (notizie demo)
#                                         $env:OPENNEWS_NO_SEED=1 (salta il seed)
$ErrorActionPreference = "Stop"

$OpenNewsHome = if ($env:OPENNEWS_HOME) { $env:OPENNEWS_HOME } else { Join-Path $env:USERPROFILE ".opennews" }
$App  = Join-Path $OpenNewsHome "app"
$Zip  = Join-Path $env:TEMP "opennews.zip"
$Url  = "http://127.0.0.1:8000"

function Say($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

Say "Installo Open News in $OpenNewsHome (senza Docker)"
New-Item -ItemType Directory -Force -Path $OpenNewsHome | Out-Null

Say "Scarico l'applicazione"
Invoke-WebRequest "https://codeload.github.com/zano97/open_news/zip/refs/heads/main" -OutFile $Zip
$Tmp = Join-Path $env:TEMP ("opennews-" + [guid]::NewGuid().ToString("n"))
Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
$Src = Get-ChildItem $Tmp -Directory | Where-Object { $_.Name -like "open_news-*" } | Select-Object -First 1
if (-not $Src) { throw "archivio inatteso" }
# Conserva l'ambiente Python tra aggiornamenti; i dati vivono fuori da app\.
$VenvKeep = Join-Path $OpenNewsHome ".venv-keep"
if (Test-Path (Join-Path $App ".venv")) { Move-Item (Join-Path $App ".venv") $VenvKeep -Force }
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
Move-Item $Src.FullName $App
if (Test-Path $VenvKeep) { Move-Item $VenvKeep (Join-Path $App ".venv") -Force }
Remove-Item $Zip -Force; Remove-Item $Tmp -Recurse -Force

Say "Preparo Python (via uv, si scarica da solo se manca)"
$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) {
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression | Out-Null
  $Uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
  if (-not (Test-Path $Uv)) { throw "installazione di uv non riuscita" }
}
Set-Location $App
& $Uv venv --quiet --allow-existing --python 3.12 .venv
& $Uv pip install --quiet --python .venv\Scripts\python.exe -e .

Say "Creo il comando «opennews» e la voce nel menu Start"
$BinDir = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Exe = Join-Path $App ".venv\Scripts\opennews.exe"
"@echo off`r`n`"$Exe`" %*" | Set-Content (Join-Path $BinDir "opennews.cmd") -Encoding ascii
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$BinDir*") {
  [Environment]::SetEnvironmentVariable("Path", "$UserPath;$BinDir", "User")
  Write-Host "Aggiunto $BinDir al PATH utente (apri un nuovo terminale per usarlo)."
}
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Shell = New-Object -ComObject WScript.Shell
$Lnk = $Shell.CreateShortcut((Join-Path $StartMenu "Open News.lnk"))
$Lnk.TargetPath = $Exe
$Lnk.WorkingDirectory = $App
$Lnk.Description = "Chi paga l'informazione · come la racconta · che cosa ignora"
$Lnk.Save()

if ($env:OPENNEWS_DEMO -eq "1") {
  Say "Popolo con notizie dimostrative (dichiarate come tali)"
  & $Exe seed --demo
} elseif ($env:OPENNEWS_NO_SEED -ne "1") {
  Say "Scarico le ultime 24 ore di notizie vere (~10-15 minuti, solo la prima volta)"
  & $Exe seed
}

Say "Avvio il giornale"
Start-Process -FilePath $Exe -WindowStyle Minimized
Start-Sleep -Seconds 3

Say "Fatto. Il giornale è su $Url"
Write-Host @"

Come si usa da adesso in poi:
  - voce «Open News» nel menu Start
  - oppure da terminale:  opennews   (in un nuovo terminale)
  - aggiornare l'app: riesegui il comando di installazione (i dati restano)
  - dati e log: $OpenNewsHome
"@
