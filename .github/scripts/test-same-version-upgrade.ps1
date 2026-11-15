param(
  [Parameter(Mandatory)][string]$BaselineInstaller,
  [Parameter(Mandatory)][string]$CandidateInstaller,
  [Parameter(Mandatory)][string]$CandidateExe
)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or -not $IsWindows) {
  throw 'Run only on a disposable GitHub-hosted Windows runner.'
}
$baselineHash = '3ef8e38ddd49d03aceaa0bebf418287734bad0f814f86a69dfba9f1a34c5e7b8'
$BaselineInstaller = (Resolve-Path -LiteralPath $BaselineInstaller).Path
$CandidateInstaller = (Resolve-Path -LiteralPath $CandidateInstaller).Path
if ((Get-FileHash -LiteralPath $BaselineInstaller).Hash -ne $baselineHash) {
  throw 'Pinned 1.0.148 test installer hash mismatch; refusing to execute.'
}
$candidateHash = (Get-FileHash -LiteralPath $CandidateExe).Hash
if ((Get-FileHash -LiteralPath $CandidateInstaller).Hash -eq $baselineHash) {
  throw 'Candidate installer is identical to the baseline.'
}
$root = Join-Path $env:RUNNER_TEMP ("idb-upgrade-" + [guid]::NewGuid())
$installDir = Join-Path $root 'app'
$exe = Join-Path $installDir 'ImageDrawBot.exe'
$oldAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = Join-Path $root 'localappdata'
$settingsRoot = Join-Path $env:LOCALAPPDATA 'ImageDrawBot'
$originalFailure = $null
$installed = $false
function Run-Checked($path, $argsList, $step) {
  $p = Start-Process -FilePath $path -ArgumentList $argsList -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "$step failed: exit $($p.ExitCode)" }
}
try {
  New-Item -ItemType Directory -Path $settingsRoot -Force | Out-Null
  $flags = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$installDir`"")
  Run-Checked $BaselineInstaller $flags 'Baseline installation'
  $installed = $true
  if ((Get-FileHash -LiteralPath $exe).Hash -eq $candidateHash) {
    throw 'Baseline and candidate application binaries are identical; replacement is not demonstrated.'
  }
  $seed = @{
    'settings.json' = @{settings_schema = 2; precision = 'Normal'; contrast = 1.2}
    'settings-gartic-phone.json' = @{settings_schema = 2; precision = 'Ultra'; contrast = 1.7}
  }
  $hashes = @{}
  foreach ($name in $seed.Keys) {
    $path = Join-Path $settingsRoot $name
    $seed[$name] | ConvertTo-Json -Compress | Set-Content -LiteralPath $path -Encoding utf8NoBOM
    $hashes[$name] = (Get-FileHash -LiteralPath $path).Hash
  }
  Run-Checked $CandidateInstaller $flags 'Same-version upgrade'
  if ((Get-FileHash -LiteralPath $exe).Hash -ne $candidateHash) {
    throw 'Installed executable does not match the candidate build.'
  }
  function Assert-SettingsPreserved($phase) {
    foreach ($name in $seed.Keys) {
      if ((Get-FileHash -LiteralPath (Join-Path $settingsRoot $name)).Hash -ne $hashes[$name]) {
        throw "$phase changed $name."
      }
    }
  }
  Assert-SettingsPreserved 'Same-version upgrade'
  Run-Checked $exe @('--self-test') 'Upgraded app self-test'
  Assert-SettingsPreserved 'Upgraded app self-test'
  Write-Host 'Same-version upgrade replaced the binary and preserved generic/profile settings byte for byte.'
} catch {
  $originalFailure = $_
  throw
} finally {
  try {
    $uninstall = Join-Path $installDir 'unins000.exe'
    if ($installed -and -not (Test-Path -LiteralPath $uninstall)) {
      throw 'Uninstaller is missing after successful installation.'
    }
    if (Test-Path -LiteralPath $uninstall) {
      Run-Checked $uninstall @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'Upgrade test uninstall'
    }
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
  } catch {
    if ($null -eq $originalFailure) { throw }
    Write-Warning "Upgrade test cleanup also failed: $_"
  } finally {
    $env:LOCALAPPDATA = $oldAppData
  }
}
