<#
.SYNOPSIS
  End-to-end test of ULTRON with your real local Ollama model on Windows.

.DESCRIPTION
  Checks, in order:
    1. Ollama answers on its local address and is not exposed on the network
    2. The model (default qwen3.5:4b) is installed
    3. Ollama itself can generate a reply
    4. ULTRON Core is ready and sees the local model
    5. (Docker) the ULTRON container can reach Ollama on the host
    6. Warm-up: ULTRON loads the model into memory
    7. A real chat through ULTRON (JSON and streamed, with loading-state
       events), labelled "local"
    8. A private conversation uses only local AI
    9. Cloud-to-local fallback (temporary second backend whose cloud
       provider points at a closed port, so no real or paid cloud call)
   10. Unavailable-model handling (temporary backend with a model name
       that is not installed)
  Then restores your AI preferences, deletes the test conversations and
  signs the test device out.

  Works with Windows PowerShell 5.1 and PowerShell 7. Makes no changes to
  .env, Ollama or other projects.

.EXAMPLE
  # From the repository root, with the stack running (docker compose up -d --build):
  powershell -ExecutionPolicy Bypass -File scripts\windows\Test-UltronOllama.ps1 -Email you@example.com

.EXAMPLE
  # Backend running natively (uv run ultron-core serve) instead of Docker:
  powershell -ExecutionPolicy Bypass -File scripts\windows\Test-UltronOllama.ps1 -Email you@example.com -NoDocker
#>
[CmdletBinding()]
param(
    [string]$Model = "qwen3.5:4b",
    [string]$OllamaUrl = "http://127.0.0.1:11434",
    [string]$ApiUrl = "http://localhost:8000",
    [string]$Email = "",
    [switch]$NoDocker,
    [int]$TimeoutSec = 300,
    [int]$FallbackPort = 8001,
    [int]$MissingModelPort = 8002
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$MissingModel = "qwen3.5:not-installed-ultron-test"
$FallbackContainer = "ultron-core-fallback-test"
$MissingContainer = "ultron-core-missing-model-test"
$script:Results = New-Object System.Collections.Generic.List[object]
$script:Conversations = New-Object System.Collections.Generic.List[object]

# ---------------------------------------------------------------- helpers

function Add-Result([string]$Name, [bool]$Ok, [string]$Detail) {
    $label = if ($Ok) { "PASS" } else { "FAIL" }
    $color = if ($Ok) { "Green" } else { "Red" }
    $script:Results.Add([pscustomobject]@{ Step = $Name; Result = $label; Detail = $Detail })
    Write-Host ("[{0}] {1} - {2}" -f $label, $Name, $Detail) -ForegroundColor $color
}

function Add-Note([string]$Name, [string]$Detail) {
    $script:Results.Add([pscustomobject]@{ Step = $Name; Result = "INFO"; Detail = $Detail })
    Write-Host ("[INFO] {0} - {1}" -f $Name, $Detail) -ForegroundColor Yellow
}

function Invoke-Api {
    param(
        [string]$Method = "GET",
        [string]$Url,
        $Body = $null,
        [hashtable]$Headers = @{},
        [int]$Timeout = $TimeoutSec
    )
    $params = @{ Method = $Method; Uri = $Url; Headers = $Headers; TimeoutSec = $Timeout; UseBasicParsing = $true }
    if ($null -ne $Body) {
        $json = ConvertTo-Json -InputObject $Body -Depth 10 -Compress
        $params.Body = [System.Text.Encoding]::UTF8.GetBytes($json)
        $params.ContentType = "application/json; charset=utf-8"
    }
    $status = 0
    $text = $null
    try {
        $resp = Invoke-WebRequest @params
        $status = [int]$resp.StatusCode
        $text = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
    }
    catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            return [pscustomobject]@{ Status = 0; Text = $_.Exception.Message; Json = $null }
        }
        $status = [int]$response.StatusCode
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $text = $_.ErrorDetails.Message
        }
        elseif ($response -is [System.Net.HttpWebResponse]) {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $text = $reader.ReadToEnd()
        }
    }
    $obj = $null
    if ($text) { try { $obj = ConvertFrom-Json -InputObject $text } catch { $obj = $null } }
    return [pscustomobject]@{ Status = $status; Text = $text; Json = $obj }
}

# Simple (non-advanced) function taking ONE array, so docker flags such as
# -e / -d / -p are never mistaken for PowerShell's own common parameters.
function Invoke-Docker([string[]]$DockerArgs) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"   # docker writes progress to stderr
    try {
        $out = & docker @DockerArgs 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $old }
    return [pscustomobject]@{ Code = $code; Output = $out.Trim() }
}

function Wait-Live([string]$BaseUrl, [int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $r = Invoke-Api -Url "$BaseUrl/health/live" -Timeout 3
        if ($r.Status -eq 200) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function New-Conversation([string]$BaseUrl, [hashtable]$Headers, [bool]$Private = $false) {
    $r = Invoke-Api -Method POST -Url "$BaseUrl/api/v1/conversations" -Headers $Headers -Body @{ is_private = $Private }
    if ($r.Status -ne 201) { throw "Could not create a conversation (HTTP $($r.Status)): $($r.Text)" }
    $script:Conversations.Add($r.Json.id)
    return $r.Json.id
}

function Send-Message([string]$BaseUrl, [hashtable]$Headers, [string]$ConversationId, [string]$Text, [bool]$Stream = $false) {
    $started = Get-Date
    $r = Invoke-Api -Method POST -Url "$BaseUrl/api/v1/conversations/$ConversationId/messages" -Headers $Headers -Body @{ content = $Text; stream = $Stream }
    $r | Add-Member -NotePropertyName Seconds -NotePropertyValue ([math]::Round(((Get-Date) - $started).TotalSeconds, 1))
    return $r
}

function Get-Attempts($Json) {
    if ($null -eq $Json) { return @() }
    if ($Json.routing -and $Json.routing.attempts) { return @($Json.routing.attempts) }
    if ($Json.detail -and $Json.detail.attempts) { return @($Json.detail.attempts) }
    return @()
}

$CloudKeysOff = @(
    "-e", "ULTRON_GROQ_API_KEY=", "-e", "ULTRON_GEMINI_API_KEY=", "-e", "ULTRON_OPENROUTER_API_KEY=",
    "-e", "ULTRON_ANTHROPIC_API_KEY=", "-e", "ULTRON_AI_DEV_MOCK=off", "-e", "ULTRON_RUN_MIGRATIONS_ON_START=false"
)

# ---------------------------------------------------------------- start

Write-Host "ULTRON + Ollama integration test" -ForegroundColor Cyan
Write-Host "Model: $Model | Ollama: $OllamaUrl | ULTRON API: $ApiUrl | Docker: $(-not $NoDocker)`n"
Push-Location $RepoRoot
$token = $null
$headers = @{}
$originalPrefs = $null

try {
    # 1. Ollama reachable, and only on this PC
    $r = Invoke-Api -Url "$OllamaUrl/api/version" -Timeout 10
    Add-Result "Ollama reachable" ($r.Status -eq 200) $(if ($r.Status -eq 200) { "version $($r.Json.version)" } else { "no answer from $OllamaUrl ($($r.Text))" })
    if ($r.Status -ne 200) { throw "Start Ollama first (it normally runs in the system tray)." }

    try {
        $listen = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction Stop | Select-Object -ExpandProperty LocalAddress -Unique)
        $public = @($listen | Where-Object { $_ -notin @("127.0.0.1", "::1") })
        Add-Result "Ollama not exposed on the network" ($public.Count -eq 0) ("listening on: " + ($listen -join ", "))
    }
    catch { Add-Note "Ollama exposure check" "could not read listening ports ($($_.Exception.Message))" }

    # 2. Model installed
    $r = Invoke-Api -Url "$OllamaUrl/api/tags" -Timeout 10
    $names = @()
    if ($r.Json -and $r.Json.models) { $names = @($r.Json.models | ForEach-Object { $_.name }) }
    $installed = ($names -contains $Model) -or ($names -contains "$($Model):latest")
    Add-Result "Model installed" $installed $(if ($installed) { $Model } else { "'$Model' not in: $($names -join ', ')" })
    if (-not $installed) { throw "Run: ollama pull $Model" }

    # 3. Ollama generates a reply on its own
    $started = Get-Date
    $r = Invoke-Api -Method POST -Url "$OllamaUrl/api/chat" -Body @{
        model    = $Model
        messages = @(@{ role = "user"; content = "Reply with one short sentence that includes the word ULTRON." })
        stream   = $false
        think    = $false
        options  = @{ num_ctx = 8192; num_predict = 128 }
    }
    $secs = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    $answer = if ($r.Json -and $r.Json.message) { [string]$r.Json.message.content } else { "" }
    Add-Result "Ollama direct reply" (($r.Status -eq 200) -and $answer.Trim().Length -gt 0) ("{0}s: {1}" -f $secs, $answer.Trim())

    # 4. ULTRON ready and sees the model
    $r = Invoke-Api -Url "$ApiUrl/health/ready" -Timeout 15
    $localAi = if ($r.Json) { $r.Json.checks.local_ai } else { $null }
    $ok = ($r.Status -eq 200) -and $localAi -and ($localAi.status -eq "ok") -and ($localAi.model -eq $Model)
    Add-Result "ULTRON ready with local model" $ok $(if ($localAi) { "local_ai=$($localAi.status) model=$($localAi.model) $($localAi.reason)" } else { "HTTP $($r.Status) $($r.Text)" })

    # 5. Container -> host Ollama
    if (-not $NoDocker) {
        $py = 'import os,json,urllib.request as r; u=os.environ[''ULTRON_OLLAMA_BASE_URL'']; print(u, json.load(r.urlopen(u+''/api/version'', timeout=5))[''version''])'
        $d = Invoke-Docker -DockerArgs @("compose", "exec", "-T", "core", "python", "-c", $py)
        Add-Result "Container reaches Ollama on the host" ($d.Code -eq 0) $d.Output
    }

    # 6. Sign in
    if (-not $Email) { $Email = Read-Host "ULTRON owner email" }
    $plain = $env:ULTRON_TEST_PASSWORD
    if (-not $plain) {
        $secure = Read-Host "ULTRON owner password" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
    $r = Invoke-Api -Method POST -Url "$ApiUrl/api/v1/auth/login" -Timeout 30 -Body @{
        email = $Email; password = $plain; device_name = "ULTRON Ollama test"; platform = "windows"
    }
    $plain = $null
    if ($r.Status -ne 200) { throw "Login failed (HTTP $($r.Status)): $($r.Text)" }
    $token = $r.Json.access_token
    $headers = @{ Authorization = "Bearer $token" }
    Add-Result "Signed in" $true $Email

    # AI status
    $r = Invoke-Api -Url "$ApiUrl/api/v1/ai/status" -Headers $headers
    $ollama = @($r.Json.providers | Where-Object { $_.name -eq "ollama" })[0]
    Add-Result "AI status shows local AI" ($r.Json.local_ai_available -eq $true -and $ollama.status -eq "ready") ("local_ai_available={0} ollama={1} model={2}" -f $r.Json.local_ai_available, $ollama.status, $ollama.model)

    # Remember preferences, then force local_only for the chat tests
    $originalPrefs = (Invoke-Api -Url "$ApiUrl/api/v1/ai/preferences" -Headers $headers).Json
    $order = @()
    if ($originalPrefs.cloud_order) { $order = @($originalPrefs.cloud_order) }
    $null = Invoke-Api -Method PUT -Url "$ApiUrl/api/v1/ai/preferences" -Headers $headers -Body @{ mode = "local_only"; cloud_order = $order; private_by_default = [bool]$originalPrefs.private_by_default }

    # Warm-up: load the model before the first chat
    $r = Invoke-Api -Method POST -Url "$ApiUrl/api/v1/ai/local/warmup" -Headers $headers
    $ok = ($r.Status -eq 200) -and ($r.Json.status -eq "ready") -and ($r.Json.model -eq $Model)
    Add-Result "Warm-up loads the model" $ok $(if ($r.Json -and $r.Json.status) { "{0}s, already loaded: {1}" -f $r.Json.seconds, $r.Json.already_loaded } else { "HTTP $($r.Status) $($r.Text)" })
    $r = Invoke-Api -Url "$ApiUrl/api/v1/ai/status" -Headers $headers
    $ollama = @($r.Json.providers | Where-Object { $_.name -eq "ollama" })[0]
    Add-Result "Model reported as loaded" ($ollama.model_loaded -eq $true) ("model_loaded={0}" -f $ollama.model_loaded)

    # 7. Real chat through ULTRON
    $cid = New-Conversation $ApiUrl $headers
    $r = Send-Message $ApiUrl $headers $cid "Reply with one short sentence that includes the word ULTRON."
    $m = if ($r.Json) { $r.Json.assistant_message } else { $null }
    $ok = ($r.Status -eq 200) -and $m -and ($m.provider_kind -eq "local") -and ($m.model -eq $Model) -and ([string]$m.content).Trim().Length -gt 0
    Add-Result "Chat via ULTRON (local)" $ok $(if ($m) { "{0}s, {1}/{2}: {3}" -f $r.Seconds, $m.provider, $m.model, ([string]$m.content).Trim() } else { "HTTP $($r.Status) $($r.Text)" })

    $r = Send-Message $ApiUrl $headers $cid "Now say it again in different words." $true
    $events = @(([regex]::Matches([string]$r.Text, "(?m)^event: (\S+)")) | ForEach-Object { $_.Groups[1].Value })
    $phases = @(([regex]::Matches([string]$r.Text, '"phase": "([a-z_]+)"')) | ForEach-Object { $_.Groups[1].Value })
    $ok = ($r.Status -eq 200) -and ($events -contains "provider.selected") -and ($events -contains "delta") -and ($events[-1] -eq "message.completed") -and ([string]$r.Text -match '"kind": "local"')
    Add-Result "Streamed chat via ULTRON" $ok ("{0}s, events: {1} ({2} deltas)" -f $r.Seconds, (($events | Select-Object -Unique) -join " > "), @($events | Where-Object { $_ -eq "delta" }).Count)
    $ok = ($phases.Count -ge 3) -and ($phases[0] -eq "routing") -and ($phases[-1] -eq "generating")
    Add-Result "Loading-state events" $ok ("phases: " + ($phases -join " > "))

    # 8. Private conversation in normal (auto) mode -> local only
    $null = Invoke-Api -Method PUT -Url "$ApiUrl/api/v1/ai/preferences" -Headers $headers -Body @{ mode = "auto"; cloud_order = $order; private_by_default = [bool]$originalPrefs.private_by_default }
    $pid2 = New-Conversation $ApiUrl $headers $true
    $r = Send-Message $ApiUrl $headers $pid2 "This is a private note. Reply with one word."
    $m = if ($r.Json) { $r.Json.assistant_message } else { $null }
    $cloudTried = @(Get-Attempts $r.Json | Where-Object { $_.kind -ne "local" })
    $ok = ($r.Status -eq 200) -and $m -and ($m.provider_kind -eq "local") -and ($cloudTried.Count -eq 0)
    Add-Result "Private conversation stays local" $ok $(if ($m) { "{0}s, provider={1}, cloud attempts={2}" -f $r.Seconds, $m.provider, $cloudTried.Count } else { "HTTP $($r.Status) $($r.Text)" })

    if ($NoDocker) {
        Add-Note "Fallback / missing-model tests" "skipped with -NoDocker; run the pytest live suite instead (see docs\WINDOWS_OLLAMA.md)"
    }
    else {
        # 9. Cloud -> local fallback (temporary backend; its only cloud provider is a closed port)
        $null = Invoke-Docker -DockerArgs @("rm", "-f", $FallbackContainer)
        $runArgs = @("compose", "run", "-d", "--rm", "--no-deps", "--name", $FallbackContainer, "-p", "127.0.0.1:$($FallbackPort):8000") + $CloudKeysOff + @(
            "-e", "ULTRON_AI_CLOUD_PROVIDERS=custom",
            "-e", "ULTRON_CUSTOM_AI_BASE_URL=http://127.0.0.1:9/v1",
            "-e", "ULTRON_CUSTOM_AI_API_KEY=fallback-test-not-a-real-key",
            "-e", "ULTRON_CUSTOM_AI_MODEL=fallback-test",
            "core")
        $d = Invoke-Docker -DockerArgs $runArgs
        try {
            $fb = "http://127.0.0.1:$FallbackPort"
            if (-not (Wait-Live $fb)) { throw "temporary backend did not start: $($d.Output)" }
            $cid3 = New-Conversation $fb $headers
            $r = Send-Message $fb $headers $cid3 "Reply with one short sentence."
            $m = if ($r.Json) { $r.Json.assistant_message } else { $null }
            $first = @(Get-Attempts $r.Json)[0]
            $ok = ($r.Status -eq 200) -and $m -and ($m.provider_kind -eq "local") -and ($m.fallback_used -eq $true) -and $first -and ($first.provider -eq "custom") -and ($first.outcome -eq "offline")
            Add-Result "Cloud failure falls back to local" $ok $(if ($m) { "{0}s, attempts: {1}" -f $r.Seconds, ((Get-Attempts $r.Json | ForEach-Object { "$($_.provider)=$($_.outcome)" }) -join ", ") } else { "HTTP $($r.Status) $($r.Text)" })
        }
        catch { Add-Result "Cloud failure falls back to local" $false $_.Exception.Message }
        finally { $null = Invoke-Docker -DockerArgs @("stop", $FallbackContainer) }

        # 10. Unavailable model (temporary backend asking for a model that isn't installed)
        $null = Invoke-Docker -DockerArgs @("rm", "-f", $MissingContainer)
        $runArgs = @("compose", "run", "-d", "--rm", "--no-deps", "--name", $MissingContainer, "-p", "127.0.0.1:$($MissingModelPort):8000") + $CloudKeysOff + @(
            "-e", "ULTRON_CUSTOM_AI_API_KEY=",
            "-e", "ULTRON_OLLAMA_MODEL=$MissingModel",
            "core")
        $d = Invoke-Docker -DockerArgs $runArgs
        try {
            $mm = "http://127.0.0.1:$MissingModelPort"
            if (-not (Wait-Live $mm)) { throw "temporary backend did not start: $($d.Output)" }
            $s = (Invoke-Api -Url "$mm/api/v1/ai/status" -Headers $headers).Json
            $o = @($s.providers | Where-Object { $_.name -eq "ollama" })[0]
            Add-Result "Missing model reported, not claimed" (($s.local_ai_available -eq $false) -and ([string]$o.reason -like "*not installed*")) ("local_ai_available={0}: {1}" -f $s.local_ai_available, $o.reason)

            $cid4 = New-Conversation $mm $headers
            $r = Send-Message $mm $headers $cid4 "hi"
            Add-Result "Chat with missing model fails clearly" (($r.Status -eq 503) -and ($r.Json.detail.code -eq "no_ai_available")) ("HTTP {0} {1}: {2}" -f $r.Status, $r.Json.detail.code, $r.Json.detail.message)

            $cid5 = New-Conversation $mm $headers $true
            $r = Send-Message $mm $headers $cid5 "hi"
            Add-Result "Private + missing model never uses cloud" (($r.Status -eq 503) -and ($r.Json.detail.code -eq "private_requires_local_ai")) ("HTTP {0} {1}" -f $r.Status, $r.Json.detail.code)
        }
        catch { Add-Result "Missing-model handling" $false $_.Exception.Message }
        finally { $null = Invoke-Docker -DockerArgs @("stop", $MissingContainer) }
    }
}
catch {
    Add-Result "Run stopped" $false $_.Exception.Message
}
finally {
    if ($token) {
        if ($originalPrefs) {
            $order = @()
            if ($originalPrefs.cloud_order) { $order = @($originalPrefs.cloud_order) }
            $null = Invoke-Api -Method PUT -Url "$ApiUrl/api/v1/ai/preferences" -Headers $headers -Body @{ mode = [string]$originalPrefs.mode; cloud_order = $order; private_by_default = [bool]$originalPrefs.private_by_default }
        }
        foreach ($c in $script:Conversations) { $null = Invoke-Api -Method DELETE -Url "$ApiUrl/api/v1/conversations/$c" -Headers $headers }
        $null = Invoke-Api -Method POST -Url "$ApiUrl/api/v1/auth/logout" -Headers $headers
    }
    Pop-Location
}

Write-Host ""
$script:Results | Format-Table -AutoSize -Wrap | Out-String -Width 220 | Write-Host
$failed = @($script:Results | Where-Object { $_.Result -eq "FAIL" }).Count
if ($failed -gt 0) {
    Write-Host "$failed check(s) failed. See docs\WINDOWS_OLLAMA.md -> Troubleshooting." -ForegroundColor Red
    exit 1
}
Write-Host "All checks passed." -ForegroundColor Green
exit 0
