# The model runs behind the numbers: each demo inbox once without Countersign and once with it, against the PayPal sandbox.
#
#   .\scripts\final_runs.ps1                                       the three inboxes on one model
#   .\scripts\final_runs.ps1 -Models cerebras/gpt-oss-120b,groq/openai/gpt-oss-120b
#   .\scripts\final_runs.ps1 -Inboxes final -Repeats 2
#
# Every run starts the sandbox shop over (--fresh), so stop the local server first. Each pair is open first, guarded second.
# A run whose model stopped answering is saved as incomplete and is not counted. Runs made with an earlier guard or prompt
# are not counted either (see fingerprint.py), so this is also how the old numbers get replaced.
param(
    [string[]]$Models = @("cerebras/gpt-oss-120b"),
    [string[]]$Inboxes = @("standard", "holdout", "final"),
    [int]$Repeats = 1
)

Set-Location (Split-Path $PSScriptRoot -Parent)
$started = Get-Date
for ($round = 1; $round -le $Repeats; $round++) {
    foreach ($model in $Models) {
        foreach ($inbox in $Inboxes) {
            foreach ($mode in @("open", "guarded")) {
                Write-Host ""
                Write-Host "==== $model | $inbox | $mode | round $round | $((Get-Date).ToString('HH:mm:ss'))"
                $runArgs = @("scripts\run_inbox.py", "--inbox", $inbox, "--model", $model, "--fresh")
                if ($mode -eq "open") { $runArgs += "--open" }
                python @runArgs
                if ($LASTEXITCODE -ne 0) { Write-Host "(this run ended with exit code $LASTEXITCODE)" }
            }
        }
    }
}

Write-Host ""
Write-Host "==== finished in $([int]((Get-Date) - $started).TotalMinutes) minutes"
foreach ($inbox in $Inboxes) {
    Write-Host ""
    Write-Host "---- $inbox, every counted run"
    python scripts\compare_runs.py --all --inbox $inbox
}
