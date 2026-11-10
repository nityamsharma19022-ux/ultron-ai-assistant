<#
.SYNOPSIS
    Starts the ULTRON Windows agent automatically when you sign in to Windows.

.DESCRIPTION
    Registers a Scheduled Task for the current user (no administrator rights,
    no system-wide changes). The task runs `uv run ultron-agent run` from the
    ULTRON project folder, hidden, and restarts it if it stops.

    Run once after `ultron-agent login` works. Use -Uninstall to remove it.

.EXAMPLE
    .\scripts\windows\Install-UltronAgent.ps1
.EXAMPLE
    .\scripts\windows\Install-UltronAgent.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$ProjectDir = "D:\ULTRON\ultron-ai-assistant",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "ULTRON Agent"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the '$TaskName' task. The agent no longer starts at sign-in."
    } else {
        Write-Host "No '$TaskName' task was installed."
    }
    return
}

$AgentDir = Join-Path $ProjectDir "apps\agent"
$Config = Join-Path $ProjectDir ".ultron-agent\agent.toml"
if (-not (Test-Path $AgentDir)) { throw "Agent not found at $AgentDir" }
if (-not (Test-Path $Config)) { throw "No agent config at $Config. Run: uv run ultron-agent init" }

$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) { throw "uv is not installed or not on PATH (https://docs.astral.sh/uv/)." }

# Check the sign-in before installing.
Push-Location $AgentDir
try {
    $check = & $Uv run ultron-agent check 2>&1 | Out-String
    if ($check -notmatch "Signed in: yes") {
        throw "The agent isn't signed in yet. Run: uv run ultron-agent login"
    }
} finally {
    Pop-Location
}

$LogDir = Join-Path $ProjectDir ".ultron-agent\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "agent.log"

# Hidden PowerShell runs the agent and appends its output to a log file.
$Command = "Set-Location -LiteralPath '$AgentDir'; & '$Uv' run ultron-agent run *>> '$Log'"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$Command`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Principal $Principal -Description "ULTRON Windows agent (runs allowed PC actions for ULTRON)" `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started '$TaskName'. It starts whenever you sign in to Windows."
Write-Host "Log: $Log"
Write-Host "Stop it now:      Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it:        .\scripts\windows\Install-UltronAgent.ps1 -Uninstall"
