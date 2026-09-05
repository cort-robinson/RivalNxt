param([Parameter(Mandatory)][string]$Installer, [Parameter(Mandatory)][string]$Version, [string]$PreviousInstaller)
$ErrorActionPreference = 'Stop'
# Never run installer smoke tests on a developer's profile or gaming installation.
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'Use an ephemeral GitHub-hosted Windows runner.' }
$smokeRoot = Join-Path $env:RUNNER_TEMP 'rivalnxt-install-smoke'
$installDir = Join-Path $smokeRoot 'app'
New-Item -ItemType Directory -Force $installDir | Out-Null
$dataDir = Join-Path $env:APPDATA 'com.rivalnxt.modmanager'
New-Item -ItemType Directory -Force $dataDir | Out-Null
$sentinel = Join-Path $dataDir 'release-smoke-preserved.txt'
[IO.File]::WriteAllText($sentinel, 'Synthetic user data must survive an upgrade.')
$before = (Get-FileHash -LiteralPath $sentinel).Hash
$settingsSentinel = Join-Path $dataDir 'settings.json'
[IO.File]::WriteAllText($settingsSentinel, '{"nexus_api_key":"synthetic-release-test"}')
$dbSentinel = Join-Path $dataDir 'mods.db'
python -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE release_fixture (value TEXT)"); c.execute("INSERT INTO release_fixture VALUES (?)", ("preserve this synthetic row",)); c.commit(); c.close()' $dbSentinel
if ($LASTEXITCODE -ne 0) { throw 'Could not create synthetic upgrade fixture.' }
$settingsHash = (Get-FileHash -LiteralPath $settingsSentinel).Hash
$dbHash = (Get-FileHash -LiteralPath $dbSentinel).Hash
function Install-And-Check([string]$Path) {
  $process = Start-Process -FilePath (Resolve-Path -LiteralPath $Path).Path -ArgumentList @('/S', "/D=$installDir") -WindowStyle Hidden -PassThru -Wait
  if ($process.ExitCode -ne 0) { throw "Installer failed with exit code $($process.ExitCode)" }
  if (-not (Test-Path (Join-Path $installDir 'rivalnxt.exe'))) { throw 'Desktop executable missing.' }
  if (-not (Test-Path (Join-Path $installDir 'rivalnxt_backend.exe'))) { throw 'Backend executable missing.' }
  if ((Get-FileHash -LiteralPath $sentinel).Hash -ne $before -or (Get-FileHash -LiteralPath $settingsSentinel).Hash -ne $settingsHash -or (Get-FileHash -LiteralPath $dbSentinel).Hash -ne $dbHash) { throw 'Installer changed synthetic user settings or database.' }
}
if ($PreviousInstaller) { Install-And-Check $PreviousInstaller }
Install-And-Check $Installer
$exe = Get-Item (Join-Path $installDir 'rivalnxt.exe')
if ($exe.VersionInfo.ProductVersion -ne $Version) { throw "Installed product version mismatch: $($exe.VersionInfo.ProductVersion) != $Version" }
Install-And-Check $Installer
Write-Host "Installed version $Version; upgrade/reinstall preserved synthetic user data and both executables."
$backendData = Join-Path $smokeRoot 'backend-data'
New-Item -ItemType Directory -Force $backendData | Out-Null
# Both settings import and the frozen entry point must resolve to this synthetic directory.
$env:MOD_MANAGER_DATA_DIR = $backendData
$env:MODMANAGER_DATA_DIR = $backendData
[IO.File]::WriteAllText((Join-Path $backendData 'settings.json'), '{}')
$backend = Start-Process -FilePath (Join-Path $installDir 'rivalnxt_backend.exe') -ArgumentList @('--host', '127.0.0.1', '--port', '18763', '--data-dir', "`"$backendData`"") -WindowStyle Hidden -PassThru
try {
  $ready = $false
  for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ($backend.HasExited) { throw 'Installed backend exited before becoming ready.' }
    try {
      $health = Invoke-RestMethod 'http://127.0.0.1:18763/health' -TimeoutSec 2
      if ($health.ok -eq $true) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) { throw 'Installed backend health endpoint did not become available.' }
  $bootstrap = Invoke-RestMethod 'http://127.0.0.1:18763/api/bootstrap/status' -TimeoutSec 5
  if ($bootstrap.needs_bootstrap -ne $true) { throw 'Fresh synthetic profile must request bootstrap.' }
  Write-Host 'Installed backend launched and served health/bootstrap endpoints on an isolated profile.'
  @{
    version = $exe.VersionInfo.ProductVersion
    installerSha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLower()
    installedExecutableSha256 = (Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash.ToLower()
    upgradeVerified = [bool]$PreviousInstaller
    reinstallVerified = $true
    userDataPreserved = $true
    backendResponded = $true
    freshProfileNeedsBootstrap = $true
  } | ConvertTo-Json | Set-Content -LiteralPath 'release-smoke-result.json' -Encoding utf8
} finally {
  if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
