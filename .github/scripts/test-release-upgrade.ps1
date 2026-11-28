param(
  [Parameter(Mandatory)][string]$CandidateInstaller,
  [Parameter(Mandatory)][string]$CandidateExe,
  [Parameter(Mandatory)][string]$CandidateVersion
)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or -not $IsWindows) {
  throw 'Run only on a disposable GitHub-hosted Windows runner.'
}
$baselineVersion = '1.0.148'
$baselineHash = '5bcd5bf5b9ff822600c3f05d9f358e8b33c1762ce05cfa23afb1a2868bd0d65c'
$baselineName = "ImageDrawBot-${baselineVersion}-Windows-x64-Setup.exe"
$baselineUrl = "https://github.com/Vxiey/Image-Draw-Bot/releases/download/v${baselineVersion}/$baselineName"
$CandidateInstaller = (Resolve-Path -LiteralPath $CandidateInstaller).Path
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
$machineDir = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Image Draw Bot'
$machineInstalled = $false
function Run-Checked($path, $argsList, $step) {
  $p = Start-Process -FilePath $path -ArgumentList $argsList -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "$step failed: exit $($p.ExitCode)" }
}
function Assert-MachineInstallBlocked($directory, $label) {
  $log = Join-Path $root "$label.log"
  $argsList = @('/ALLUSERS', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
    "/DIR=`"$directory`"", "/LOG=`"$log`"")
  $p = Start-Process -FilePath $CandidateInstaller -ArgumentList $argsList -Wait -PassThru
  if ($p.ExitCode -ne 7 -or -not (Select-String -LiteralPath $log -SimpleMatch -Quiet -Pattern 'All-users installation requires the protected folder')) {
    throw "$label did not fail at the machine-destination gate (exit $($p.ExitCode))."
  }
}
try {
  New-Item -ItemType Directory -Path $settingsRoot -Force | Out-Null
  $baselineInstaller = Join-Path $root $baselineName
  Invoke-WebRequest -Uri $baselineUrl -OutFile $baselineInstaller -ErrorAction Stop
  if ((Get-FileHash -LiteralPath $baselineInstaller -Algorithm SHA256).Hash -ne $baselineHash) {
    throw "Published v$baselineVersion installer SHA-256 mismatch; refusing to execute."
  }
  $unsafe = Join-Path $root 'legacy-machine-path'
  New-Item -ItemType Directory -Path $unsafe | Out-Null
  $sentinel = Join-Path $unsafe 'existing.txt'
  'preserve' | Set-Content -LiteralPath $sentinel
  $before = (Get-FileHash -LiteralPath $sentinel).Hash
  Assert-MachineInstallBlocked $unsafe 'misplaced-all-users'
  if ((Get-FileHash -LiteralPath $sentinel).Hash -ne $before -or @(Get-ChildItem -Force -LiteralPath $unsafe).Count -ne 1) {
    throw 'Rejected installation modified the old directory.'
  }
  $flags = @('/CURRENTUSER', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$installDir`"")
  Run-Checked $baselineInstaller $flags 'Baseline installation'
  $installed = $true
  if ((Get-Item -LiteralPath $exe).VersionInfo.ProductVersion -ne $baselineVersion) {
    throw "Installed baseline executable does not report v$baselineVersion."
  }
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
  Run-Checked $CandidateInstaller $flags 'Upgrade from published release'
  if ((Get-Item -LiteralPath $exe).VersionInfo.ProductVersion -ne $CandidateVersion.Split('-')[0]) {
    throw "Installed candidate executable does not report the expected version for v$CandidateVersion."
  }
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
  Assert-SettingsPreserved 'Upgrade from published release'
  Run-Checked $exe @('--self-test') 'Upgraded app self-test'
  Assert-SettingsPreserved 'Upgraded app self-test'
  Write-Host "Upgrade from v$baselineVersion to v$CandidateVersion replaced the binary and preserved generic/profile settings byte for byte."

  if (Test-Path -LiteralPath $machineDir) { throw "Machine smoke target already exists: $machineDir" }
  $allUsers = @('/ALLUSERS', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-')
  Run-Checked $CandidateInstaller $allUsers 'Protected all-users installation'
  $machineInstalled = $true
  Run-Checked $CandidateInstaller $allUsers 'Protected all-users upgrade'
  if ((Get-FileHash -LiteralPath (Join-Path $machineDir 'ImageDrawBot.exe')).Hash -ne $candidateHash) {
    throw 'Protected machine installation has the wrong executable.'
  }
  $permissionProbe = Join-Path $machineDir 'ci-permissions.txt'
  'owned CI fixture' | Set-Content -LiteralPath $permissionProbe
  try {
    $acl = Get-Acl -LiteralPath $permissionProbe
    $users = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-545')
    $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($users, 'Modify', 'Allow'))
    Set-Acl -LiteralPath $permissionProbe -AclObject $acl
    Assert-MachineInstallBlocked $machineDir 'writable-machine-file'
  } finally {
    Remove-Item -LiteralPath $permissionProbe -Force
  }
  $junction = Join-Path $machineDir 'ci-directory-link'
  New-Item -ItemType Junction -Path $junction -Target $unsafe | Out-Null
  try {
    Assert-MachineInstallBlocked $machineDir 'redirected-machine-directory'
  } finally {
    [System.IO.Directory]::Delete($junction)
  }
} catch {
  $originalFailure = $_
  throw
} finally {
  try {
    if ($machineInstalled) {
      Run-Checked (Join-Path $machineDir 'unins000.exe') @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'Machine smoke uninstall'
    }
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
