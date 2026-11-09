<#
.SYNOPSIS
  Safe environment audit + verified backup for the ULTRON project on Windows.

.DESCRIPTION
  Read-only checks, plus ONE write: a new, timestamped backup folder.
    A. Project: path, Git root, origin, branch, commit, uncommitted changes
    B. GitHub: read access and (dry-run) push authentication
    C. Existing backup: inspected only (never modified)
    D. New backup: robocopy WITH Git history, WITHOUT .venv / node_modules /
       caches / .env and key files; every tracked file verified by SHA-256;
       Git integrity checked; manifest written into the new backup
    E. Tools: git, docker, compose, python, uv, node, npm, ollama, claude, gh
    F. Docker: engine, compose file validity, ULTRON containers and volumes
    G. .env: required keys present, placeholders, consistency (values are
       NEVER printed)
    H. Ollama: version, qwen3.5:4b installed / loaded, not exposed (no downloads)
    I. ULTRON API health (only if already running; nothing is started)
    J. Claude Code: version, project instructions, session folders (names and
       counts only; session contents and keys are never read)
    K. Line endings that would break Docker

  Never deletes, moves, resets, pushes or overwrites anything.
  Works with Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File D:\ULTRON\ultron-ai-assistant\scripts\windows\Invoke-UltronEnvironmentAudit.ps1

.EXAMPLE
  # Audit only, no new backup:
  powershell -ExecutionPolicy Bypass -File ...\Invoke-UltronEnvironmentAudit.ps1 -SkipBackup
#>
[CmdletBinding()]
param(
    [string]$ProjectPath = "D:\ULTRON\ultron-ai-assistant",
    [string]$ExistingBackupPath = "D:\ULTRON\ultron-ai-assistant-main-backup",
    [string]$BackupRoot = "D:\ULTRON\backups",
    [string]$ExpectedOrigin = "https://github.com/nityamsharma19022-ux/ultron-ai-assistant",
    [string]$ExpectedBranch = "claude/fervent-lovelace-fqank5",
    [string]$ExpectedCommit = "425e942",
    [string]$ApiUrl = "http://localhost:8000",
    [string]$OllamaUrl = "http://127.0.0.1:11434",
    [string]$Model = "qwen3.5:4b",
    [switch]$SkipBackup,
    [switch]$SkipPushAuthCheck,
    [switch]$RunUnitTests
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$script:Results = New-Object System.Collections.Generic.List[object]

function Add-Check([string]$Area, [string]$Check, [string]$Level, [string]$Detail) {
    $script:Results.Add([pscustomobject]@{ Area = $Area; Check = $Check; Result = $Level; Detail = $Detail })
    $color = @{ PASS = "Green"; WARN = "Yellow"; FAIL = "Red"; INFO = "Gray" }[$Level]
    Write-Host ("[{0}] {1} / {2} - {3}" -f $Level, $Area, $Check, $Detail) -ForegroundColor $color
}

# Runs a native program with an argument ARRAY (no PowerShell parameter
# parsing of its flags) and never throws on stderr output.
function Invoke-Native([string]$Exe, [string[]]$ArgList = @()) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe @ArgList 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    catch { $out = $_.Exception.Message; $code = 9009 }
    finally { $ErrorActionPreference = $old }
    return [pscustomobject]@{ Code = $code; Output = ([string]$out).Trim() }
}

function Test-Command([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Get-Http([string]$Url, [int]$Timeout = 5) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $Timeout
        $text = [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
        return [pscustomobject]@{ Status = [int]$r.StatusCode; Json = ($text | ConvertFrom-Json) }
    }
    catch {
        $status = 0
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        return [pscustomobject]@{ Status = $status; Json = $null }
    }
}

function Read-EnvKeys([string]$Path) {
    # Returns key -> value. Values stay in memory only and are never printed.
    $map = @{}
    foreach ($line in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=(.*)$') { $map[$Matches[1]] = $Matches[2].Trim() }
    }
    return $map
}

function Get-TreeStats([string]$Path) {
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\(\.git|\.venv|node_modules|__pycache__|\.pytest_cache|\.ruff_cache)\\' })
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    return [pscustomobject]@{ Count = $files.Count; MB = [math]::Round(($bytes / 1MB), 2) }
}

Write-Host "ULTRON environment audit - $(Get-Date -Format 'yyyy-MM-dd HH:mm')" -ForegroundColor Cyan
Write-Host "Project: $ProjectPath`n"

# ------------------------------------------------------------------ A. Project
$git = Test-Command git
if (-not (Test-Path -LiteralPath $ProjectPath)) {
    Add-Check "Project" "Folder" "FAIL" "$ProjectPath does not exist"
}
elseif (-not $git) {
    Add-Check "Project" "Git" "FAIL" "git is not installed or not on PATH"
}
else {
    $top = Invoke-Native git @("-C", $ProjectPath, "rev-parse", "--show-toplevel")
    $topNorm = ($top.Output -replace '/', '\').TrimEnd('\')
    Add-Check "Project" "Git root" $(if ($topNorm -ieq $ProjectPath.TrimEnd('\')) { "PASS" } else { "FAIL" }) $topNorm

    $origin = (Invoke-Native git @("-C", $ProjectPath, "remote", "get-url", "origin")).Output
    $originOk = ($origin -replace '\.git$', '') -ieq $ExpectedOrigin
    Add-Check "Project" "Origin" $(if ($originOk) { "PASS" } else { "FAIL" }) $origin

    $branch = (Invoke-Native git @("-C", $ProjectPath, "branch", "--show-current")).Output
    Add-Check "Project" "Branch" $(if ($branch -eq $ExpectedBranch) { "PASS" } else { "WARN" }) $branch

    $head = (Invoke-Native git @("-C", $ProjectPath, "rev-parse", "HEAD")).Output
    Add-Check "Project" "Commit" $(if ($head.StartsWith($ExpectedCommit)) { "PASS" } else { "WARN" }) ("{0} (expected {1})" -f $head.Substring(0, [math]::Min(12, $head.Length)), $ExpectedCommit)

    $status = (Invoke-Native git @("-C", $ProjectPath, "status", "--porcelain", "--untracked-files=all")).Output
    $changes = @($status -split "`r?`n" | Where-Object { $_ })
    Add-Check "Project" "Uncommitted changes" $(if ($changes.Count -eq 0) { "PASS" } else { "WARN" }) $(if ($changes.Count -eq 0) { "none" } else { "$($changes.Count): " + (($changes | Select-Object -First 8) -join "; ") })

    $stashes = @(((Invoke-Native git @("-C", $ProjectPath, "stash", "list")).Output -split "`r?`n") | Where-Object { $_ })
    Add-Check "Project" "Stashes" $(if ($stashes.Count -eq 0) { "PASS" } else { "WARN" }) "$($stashes.Count)"

    $branches = (Invoke-Native git @("-C", $ProjectPath, "for-each-ref", "--format=%(refname:short)", "refs/heads")).Output -split "`r?`n"
    Add-Check "Project" "Local branches" "INFO" ($branches -join ", ")

    # ------------------------------------------------------------- B. GitHub
    $remote = Invoke-Native git @("-C", $ProjectPath, "ls-remote", "--heads", "origin")
    if ($remote.Code -eq 0) {
        Add-Check "GitHub" "Read access" "PASS" "ls-remote OK"
        $remoteHead = ($remote.Output -split "`r?`n" | Where-Object { $_ -match "refs/heads/$([regex]::Escape($branch))$" }) -replace '\s.*$', ''
        if ($remoteHead) {
            $synced = $remoteHead -eq $head
            Add-Check "GitHub" "Branch pushed" $(if ($synced) { "PASS" } else { "WARN" }) $(if ($synced) { "local = GitHub ($($head.Substring(0,7)))" } else { "local $($head.Substring(0,7)) vs GitHub $($remoteHead.Substring(0,7)): unpushed or unpulled commits" })
        }
        else { Add-Check "GitHub" "Branch pushed" "WARN" "branch '$branch' not found on GitHub" }
        $remoteBranches = ($remote.Output -split "`r?`n" | ForEach-Object { ($_ -split "refs/heads/")[-1] }) -join ", "
        Add-Check "GitHub" "Remote branches" "INFO" $remoteBranches
    }
    else { Add-Check "GitHub" "Read access" "FAIL" "git ls-remote failed (network or credentials)" }

    if (-not $SkipPushAuthCheck) {
        # --dry-run authenticates and compares refs but sends/changes nothing.
        $dry = Invoke-Native git @("-C", $ProjectPath, "push", "--dry-run", "origin", "HEAD:refs/heads/$branch")
        Add-Check "GitHub" "Push authentication (dry run)" $(if ($dry.Code -eq 0) { "PASS" } else { "WARN" }) $(if ($dry.Code -eq 0) { "credentials accepted; nothing was pushed" } else { "dry-run push failed: not signed in (Git Credential Manager / 'gh auth login') or local branch is behind GitHub" })
    }
    if (Test-Command gh) {
        $gh = Invoke-Native gh @("auth", "status")
        Add-Check "GitHub" "gh CLI" $(if ($gh.Code -eq 0) { "PASS" } else { "WARN" }) $(if ($gh.Code -eq 0) { "signed in" } else { "not signed in" })
    }

    $log = (Invoke-Native git @("-C", $ProjectPath, "log", "--oneline", "-8")).Output -split "`r?`n"
    Add-Check "GitHub" "Recent history" "INFO" ($log -join " | ")
}

# ---------------------------------------------------------- C. Existing backup
if (Test-Path -LiteralPath $ExistingBackupPath) {
    $stats = Get-TreeStats $ExistingBackupPath
    Add-Check "Old backup" "Contents" "INFO" ("{0} files, {1} MB (excluding .git/.venv/caches)" -f $stats.Count, $stats.MB)
    if (Test-Path -LiteralPath (Join-Path $ExistingBackupPath ".git")) {
        $ob = (Invoke-Native git @("-C", $ExistingBackupPath, "branch", "--show-current")).Output
        $oc = (Invoke-Native git @("-C", $ExistingBackupPath, "log", "--oneline", "-1")).Output
        Add-Check "Old backup" "Git" "INFO" "branch '$ob' at $oc"
        if ($ob -eq "main" -and $git) {
            $count = (Invoke-Native git @("-C", $ExistingBackupPath, "ls-files")).Output -split "`r?`n" | Where-Object { $_ }
            if (@($count).Count -le 2) { Add-Check "Old backup" "Completeness" "WARN" "only $(@($count).Count) tracked file(s): GitHub 'main' has just the initial README; the project lives on '$ExpectedBranch'" }
        }
    }
    else { Add-Check "Old backup" "Git" "WARN" "not a Git repository (no history)" }
    if (Test-Path -LiteralPath (Join-Path $ExistingBackupPath ".env")) {
        Add-Check "Old backup" "Secrets" "WARN" ".env present: this backup contains passwords/keys; keep it private"
    }
    if ($git -and (Test-Path -LiteralPath $ProjectPath)) {
        $tracked = (Invoke-Native git @("-C", $ProjectPath, "ls-files")).Output -split "`r?`n" | Where-Object { $_ }
        $missing = @($tracked | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ExistingBackupPath $_)) })
        Add-Check "Old backup" "Project files present" $(if ($missing.Count -eq 0) { "PASS" } else { "WARN" }) ("{0} of {1} current project files missing{2}" -f $missing.Count, @($tracked).Count, $(if ($missing.Count) { ": " + (($missing | Select-Object -First 5) -join ", ") + " ..." } else { "" }))
    }
}
else { Add-Check "Old backup" "Folder" "WARN" "$ExistingBackupPath not found" }

# --------------------------------------------------------------- D. New backup
if ($SkipBackup) { Add-Check "New backup" "Skipped" "INFO" "-SkipBackup" }
elseif ($git -and (Test-Path -LiteralPath $ProjectPath)) {
    $target = Join-Path $BackupRoot ("ultron-ai-assistant-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    if ($target.StartsWith($ProjectPath.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        Add-Check "New backup" "Target" "FAIL" "backup folder must be outside the project folder"
    }
    elseif (Test-Path -LiteralPath $target) {
        Add-Check "New backup" "Target" "FAIL" "$target already exists; not overwriting"
    }
    else {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        $secretFiles = @(Get-ChildItem -LiteralPath $ProjectPath -Recurse -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notmatch '\\(\.git|\.venv|node_modules)\\' -and (
                ($_.Name -like ".env*" -and $_.Name -ne ".env.example") -or $_.Extension -in @(".pem", ".key", ".p12", ".jks", ".keystore") -or $_.Name -eq "key.properties") } |
            ForEach-Object { $_.FullName })
        $rcArgs = @($ProjectPath, $target, "/E", "/COPY:DAT", "/DCOPY:T", "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH",
            "/XD", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".dart_tool", "build")
        if ($secretFiles.Count) { $rcArgs += @("/XF") + $secretFiles }
        $rc = Invoke-Native robocopy $rcArgs
        if ($rc.Code -ge 8) {
            Add-Check "New backup" "Copy" "FAIL" "robocopy exit code $($rc.Code)"
        }
        else {
            Add-Check "New backup" "Copy" "PASS" "$target (excluded $($secretFiles.Count) secret file(s), dependencies and caches)"
            $tracked = (Invoke-Native git @("-C", $ProjectPath, "ls-files")).Output -split "`r?`n" | Where-Object { $_ }
            $bad = New-Object System.Collections.Generic.List[string]
            $manifest = New-Object System.Collections.Generic.List[string]
            foreach ($f in $tracked) {
                $src = Join-Path $ProjectPath $f
                $dst = Join-Path $target $f
                if (-not (Test-Path -LiteralPath $src)) { continue }   # deleted locally (shown in status)
                if (-not (Test-Path -LiteralPath $dst)) { $bad.Add("missing: $f"); continue }
                $h1 = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash
                $h2 = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
                if ($h1 -ne $h2) { $bad.Add("differs: $f") } else { $manifest.Add("$h1  $f") }
            }
            Add-Check "New backup" "Tracked files verified (SHA-256)" $(if ($bad.Count -eq 0) { "PASS" } else { "FAIL" }) $(if ($bad.Count -eq 0) { "$($manifest.Count) files identical" } else { ($bad | Select-Object -First 5) -join "; " })

            $important = @("README.md", "PROJECT_STATUS.md", "docker-compose.yml", ".env.example", "apps\core\pyproject.toml",
                "apps\core\uv.lock", "apps\core\Dockerfile", "apps\core\src\ultron_core\main.py", "apps\core\src\ultron_core\config.py",
                "apps\core\src\ultron_core\ai\providers\ollama.py", "scripts\windows\Test-UltronOllama.ps1")
            $missingImportant = @($important | Where-Object { -not (Test-Path -LiteralPath (Join-Path $target $_)) })
            Add-Check "New backup" "Key files" $(if ($missingImportant.Count -eq 0) { "PASS" } else { "FAIL" }) $(if ($missingImportant.Count -eq 0) { "all $($important.Count) present" } else { $missingImportant -join ", " })

            $bh = (Invoke-Native git @("-C", $target, "rev-parse", "HEAD")).Output
            $fsck = Invoke-Native git @("-C", $target, "fsck", "--no-dangling")
            Add-Check "New backup" "Git history" $(if ($bh -eq $head -and $fsck.Code -eq 0) { "PASS" } else { "FAIL" }) "HEAD $($bh.Substring(0, [math]::Min(7, $bh.Length))), integrity $(if ($fsck.Code -eq 0) { 'OK' } else { 'FAILED' })"
            $leaked = @(Get-ChildItem -LiteralPath $target -Recurse -File -Force -Filter ".env" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\\.git\\' })
            Add-Check "New backup" "No secrets copied" $(if ($leaked.Count -eq 0) { "PASS" } else { "FAIL" }) $(if ($leaked.Count -eq 0) { ".env excluded" } else { "found .env in backup" })

            $header = @("ULTRON backup manifest", "Created: $(Get-Date -Format o)", "Source:  $ProjectPath",
                "Branch:  $branch", "Commit:  $head", "Origin:  $origin",
                "Excluded: .venv, node_modules, caches, .env (secrets). Restore .env separately.", "", "SHA256  path")
            Set-Content -LiteralPath (Join-Path $target "BACKUP-MANIFEST.txt") -Value ($header + $manifest) -Encoding UTF8
            Add-Check "New backup" "Manifest" "INFO" "BACKUP-MANIFEST.txt written"
        }
    }
}

# ----------------------------------------------------------------- E. Tools
$tools = [ordered]@{
    "git"    = @{ Args = @("--version"); Need = "required" }
    "docker" = @{ Args = @("--version"); Need = "required" }
    "ollama" = @{ Args = @("--version"); Need = "required for local AI" }
    "python" = @{ Args = @("--version"); Need = "optional (direct run / tests)" }
    "uv"     = @{ Args = @("--version"); Need = "optional (direct run / tests)" }
    "claude" = @{ Args = @("--version"); Need = "optional (Claude Code CLI)" }
    "gh"     = @{ Args = @("--version"); Need = "optional" }
    "node"   = @{ Args = @("--version"); Need = "not used by ULTRON yet" }
    "npm"    = @{ Args = @("--version"); Need = "not used by ULTRON yet" }
}
foreach ($t in $tools.Keys) {
    if (Test-Command $t) {
        $v = Invoke-Native $t $tools[$t].Args
        Add-Check "Tools" $t "PASS" ((($v.Output -split "`r?`n")[0]) + " - " + $tools[$t].Need)
    }
    else {
        $level = if ($tools[$t].Need -like "required*") { "FAIL" } else { "INFO" }
        Add-Check "Tools" $t $level ("not found - " + $tools[$t].Need)
    }
}

# ---------------------------------------------------------------- F. Docker
if (Test-Command docker) {
    $info = Invoke-Native docker @("info", "--format", "{{.ServerVersion}}")
    Add-Check "Docker" "Engine" $(if ($info.Code -eq 0) { "PASS" } else { "FAIL" }) $(if ($info.Code -eq 0) { "running ($($info.Output))" } else { "not running: start Docker Desktop" })
    $cv = Invoke-Native docker @("compose", "version", "--short")
    Add-Check "Docker" "Compose" $(if ($cv.Code -eq 0) { "PASS" } else { "FAIL" }) $cv.Output
    if ($info.Code -eq 0 -and (Test-Path -LiteralPath $ProjectPath)) {
        Push-Location $ProjectPath
        try {
            $cfg = Invoke-Native docker @("compose", "config", "-q")
            Add-Check "Docker" "docker-compose.yml valid" $(if ($cfg.Code -eq 0) { "PASS" } else { "FAIL" }) $(if ($cfg.Code -eq 0) { "valid with current .env" } else { ($cfg.Output -split "`r?`n")[0] })
            $ps = Invoke-Native docker @("ps", "-a", "--filter", "name=ultron-", "--format", "{{.Names}}: {{.Status}}")
            Add-Check "Docker" "ULTRON containers" "INFO" $(if ($ps.Output) { ($ps.Output -split "`r?`n") -join "; " } else { "none" })
            $vol = Invoke-Native docker @("volume", "ls", "--filter", "name=ultron_", "--format", "{{.Name}}")
            Add-Check "Docker" "ULTRON data volumes" "INFO" $(if ($vol.Output) { ($vol.Output -split "`r?`n") -join ", " } else { "none yet (first start creates them)" })
        }
        finally { Pop-Location }
    }
}

# ------------------------------------------------------------------ G. .env
$envPath = Join-Path $ProjectPath ".env"
$examplePath = Join-Path $ProjectPath ".env.example"
if (-not (Test-Path -LiteralPath $envPath)) {
    Add-Check ".env" "File" "FAIL" "missing: Copy-Item .env.example .env, then set passwords and JWT secret (docs\DEVELOPMENT.md)"
}
else {
    $envMap = Read-EnvKeys $envPath
    Add-Check ".env" "File" "PASS" "present ($($envMap.Count) settings; values not shown)"
    $ignored = Invoke-Native git @("-C", $ProjectPath, "check-ignore", "-q", ".env")
    Add-Check ".env" "Ignored by Git" $(if ($ignored.Code -eq 0) { "PASS" } else { "FAIL" }) $(if ($ignored.Code -eq 0) { "never committed" } else { ".env is NOT ignored" })
    if (Test-Path -LiteralPath $examplePath) {
        $exampleKeys = (Read-EnvKeys $examplePath).Keys
        $missingKeys = @($exampleKeys | Where-Object { -not $envMap.ContainsKey($_) } | Sort-Object)
        Add-Check ".env" "Keys from .env.example" $(if ($missingKeys.Count -eq 0) { "PASS" } else { "WARN" }) $(if ($missingKeys.Count -eq 0) { "all present" } else { "missing $($missingKeys.Count) (defaults apply): " + ($missingKeys -join ", ") })
    }
    $placeholders = @($envMap.Keys | Where-Object { $envMap[$_] -match "change-me" } | Sort-Object)
    Add-Check ".env" "Placeholders" $(if ($placeholders.Count -eq 0) { "PASS" } else { "FAIL" }) $(if ($placeholders.Count -eq 0) { "none" } else { "still placeholder: " + ($placeholders -join ", ") })
    $jwt = [string]$envMap["ULTRON_JWT_SECRET"]
    Add-Check ".env" "JWT secret length" $(if ($jwt.Length -ge 32) { "PASS" } else { "FAIL" }) "$($jwt.Length) characters (min 32)"
    $pg = [string]$envMap["ULTRON_POSTGRES_PASSWORD"]; $dbUrl = [string]$envMap["ULTRON_LOCAL_DATABASE_URL"]
    Add-Check ".env" "Postgres password matches URL" $(if ($pg -and $dbUrl.Contains(":$pg@")) { "PASS" } else { "WARN" }) "only used when running the backend directly"
    $rd = [string]$envMap["ULTRON_REDIS_PASSWORD"]; $rdUrl = [string]$envMap["ULTRON_REDIS_URL"]
    Add-Check ".env" "Redis password matches URL" $(if ($rd -and $rdUrl.Contains(":$rd@")) { "PASS" } else { "WARN" }) "only used when running the backend directly"
    Add-Check ".env" "ULTRON_OLLAMA_MODEL" $(if ($envMap["ULTRON_OLLAMA_MODEL"] -eq $Model) { "PASS" } else { "WARN" }) ([string]$envMap["ULTRON_OLLAMA_MODEL"])
    Add-Check ".env" "ULTRON_OLLAMA_BASE_URL" $(if ($envMap["ULTRON_OLLAMA_BASE_URL"] -match '^http://(127\.0\.0\.1|localhost):11434/?$') { "PASS" } else { "WARN" }) ([string]$envMap["ULTRON_OLLAMA_BASE_URL"])
    Add-Check ".env" "ULTRON_CORE_OLLAMA_BASE_URL" $(if ($envMap["ULTRON_CORE_OLLAMA_BASE_URL"] -match 'host\.docker\.internal:11434') { "PASS" } else { "WARN" }) ([string]$envMap["ULTRON_CORE_OLLAMA_BASE_URL"])
    foreach ($k in @("ULTRON_DB_MODE", "ULTRON_DEPLOYMENT", "ULTRON_AI_DEV_MOCK", "ULTRON_CORE_BIND_HOST")) {
        Add-Check ".env" $k "INFO" ([string]$envMap[$k])
    }
    $keys = @($envMap.Keys | Where-Object { $_ -match '_API_KEY$' -and $envMap[$_] })
    Add-Check ".env" "Cloud AI keys set" "INFO" $(if ($keys.Count) { ($keys | Sort-Object) -join ", " } else { "none (local AI only)" })
}

# --------------------------------------------------------------- H. Ollama
$ov = Get-Http "$OllamaUrl/api/version"
Add-Check "Ollama" "Runtime" $(if ($ov.Status -eq 200) { "PASS" } else { "FAIL" }) $(if ($ov.Status -eq 200) { "version $($ov.Json.version)" } else { "not reachable at $OllamaUrl" })
if ($ov.Status -eq 200) {
    $tags = Get-Http "$OllamaUrl/api/tags"
    $names = @($tags.Json.models | ForEach-Object { $_.name })
    Add-Check "Ollama" "Model installed" $(if ($names -contains $Model) { "PASS" } else { "FAIL" }) $(if ($names -contains $Model) { $Model } else { "'$Model' not installed (no download attempted)" })
    $ps = Get-Http "$OllamaUrl/api/ps"
    Add-Check "Ollama" "Model in memory" "INFO" $(if (@($ps.Json.models | ForEach-Object { $_.name }) -contains $Model) { "loaded" } else { "not loaded (loads on first use or warm-up)" })
    try {
        $listen = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction Stop | Select-Object -ExpandProperty LocalAddress -Unique)
        $public = @($listen | Where-Object { $_ -notin @("127.0.0.1", "::1") })
        Add-Check "Ollama" "Not exposed on network" $(if ($public.Count -eq 0) { "PASS" } else { "WARN" }) ("listening on " + ($listen -join ", "))
    }
    catch { Add-Check "Ollama" "Not exposed on network" "INFO" "could not read listening ports" }
}

# ----------------------------------------------------------- I. ULTRON API
$ready = Get-Http "$ApiUrl/health/ready"
if ($ready.Status -eq 0) {
    Add-Check "ULTRON API" "Health" "INFO" "not running (start with: docker compose up -d --build)"
}
else {
    $la = $ready.Json.checks.local_ai
    Add-Check "ULTRON API" "Health" $(if ($ready.Status -eq 200) { "PASS" } else { "WARN" }) ("status={0}, local_ai={1} {2}" -f $ready.Json.status, $la.status, $la.reason)
}

# ----------------------------------------------------------- J. Claude Code
foreach ($f in @("CLAUDE.md", ".claude\settings.json", ".claude\settings.local.json")) {
    Add-Check "Claude Code" "Project $f" "INFO" $(if (Test-Path -LiteralPath (Join-Path $ProjectPath $f)) { "present" } else { "absent" })
}
$claudeHome = Join-Path $env:USERPROFILE ".claude"
$projectsDir = Join-Path $claudeHome "projects"
$expectedKey = ($ProjectPath -replace '[^A-Za-z0-9]', '-')
if (Test-Path -LiteralPath $projectsDir) {
    $dirs = @(Get-ChildItem -LiteralPath $projectsDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*ultron*" })
    foreach ($d in $dirs) {
        $sessions = @(Get-ChildItem -LiteralPath $d.FullName -Filter "*.jsonl" -File -ErrorAction SilentlyContinue)
        $mark = if ($d.Name -ieq $expectedKey) { " (THIS folder)" } else { "" }
        Add-Check "Claude Code" "Session folder" "INFO" ("{0}{1}: {2} session(s), last used {3}" -f $d.Name, $mark, $sessions.Count, $d.LastWriteTime.ToString("yyyy-MM-dd HH:mm"))
    }
    if (-not ($dirs | Where-Object { $_.Name -ieq $expectedKey })) {
        Add-Check "Claude Code" "Sessions for $ProjectPath" "INFO" "none yet: open Claude Code in this folder once to create them"
    }
}
else { Add-Check "Claude Code" "Local sessions" "INFO" "no $projectsDir (Claude Code CLI/Desktop not used on this PC yet)" }

# ------------------------------------------------------------ K. Line endings
$entry = Join-Path $ProjectPath "apps\core\docker-entrypoint.sh"
if (Test-Path -LiteralPath $entry) {
    $hasCr = ([System.IO.File]::ReadAllText($entry)).Contains("`r")
    Add-Check "Files" "docker-entrypoint.sh line endings" $(if (-not $hasCr) { "PASS" } else { "FAIL" }) $(if ($hasCr) { "CRLF: the container would fail to start (re-checkout with .gitattributes)" } else { "LF" })
}
if ($git) { Add-Check "Files" "git core.autocrlf" "INFO" ((Invoke-Native git @("-C", $ProjectPath, "config", "core.autocrlf")).Output) }

# -------------------------------------------------------------- Unit tests
if ($RunUnitTests) {
    if (Test-Command uv) {
        Push-Location (Join-Path $ProjectPath "apps\core")
        try {
            $t = Invoke-Native uv @("run", "pytest", "-q", "-m", "not integration and not ollama_live")
            Add-Check "Tests" "Unit tests" $(if ($t.Code -eq 0) { "PASS" } else { "FAIL" }) ((($t.Output -split "`r?`n") | Select-Object -Last 1))
        }
        finally { Pop-Location }
    }
    else { Add-Check "Tests" "Unit tests" "WARN" "uv not installed" }
}

# ------------------------------------------------------------------ Summary
Write-Host ""
$script:Results | Format-Table Area, Check, Result, Detail -AutoSize -Wrap | Out-String -Width 240 | Write-Host
$fail = @($script:Results | Where-Object { $_.Result -eq "FAIL" }).Count
$warn = @($script:Results | Where-Object { $_.Result -eq "WARN" }).Count
Write-Host ("FAIL: {0}  WARN: {1}  (nothing was deleted, moved, pushed or overwritten)" -f $fail, $warn) -ForegroundColor $(if ($fail) { "Red" } elseif ($warn) { "Yellow" } else { "Green" })
if ($fail) { exit 1 } else { exit 0 }
