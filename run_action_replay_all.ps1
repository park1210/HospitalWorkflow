[CmdletBinding()]
param(
    [ValidateRange(1, 1000)][int]$Repeats = 1,
    [string]$StudyDir = 'outputs/action_replay_study_15_v1',
    [string]$OutputDir = '',
    [string]$RoutingData = '',
    [string]$RoutingUtility = '',
    [string]$Python = 'python',
    [switch]$Preview
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Stage {
    param([string]$Title, [string[]]$Arguments)
    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
    Write-Host ($Python + ' ' + ($Arguments -join ' '))
    if (-not $Preview) {
        & $Python @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Title failed (exit code $LASTEXITCODE). Later stages were NOT run."
        }
    }
}

Push-Location $PSScriptRoot
$transcribing = $false
try {
    $study = (Resolve-Path -LiteralPath $StudyDir).Path
    $plan = Get-Content -LiteralPath (Join-Path $study 'plan.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $plan.inputs.PSObject.Properties) {
        if ($property.Name -ne 'routing_utility') {
            $property.Value = (Resolve-Path -LiteralPath (Join-Path $study $property.Value)).Path
        }
    }
    $probes = (Resolve-Path -LiteralPath (Join-Path $study 'routing_probes.json')).Path
    if ([string]::IsNullOrWhiteSpace($OutputDir)) {
        $runName = 'action_replay_pipeline_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0, 6)
        $OutputDir = Join-Path 'outputs' $runName
    }
    if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
        $OutputDir = Join-Path $PSScriptRoot $OutputDir
    }
    $runRoot = [System.IO.Path]::GetFullPath($OutputDir)
    if (Test-Path -LiteralPath $runRoot) {
        throw "Output directory already exists. Choose a new -OutputDir: $runRoot"
    }
    $fitDir = Join-Path $runRoot 'fitted'
    $runPlan = Join-Path $runRoot 'plan.json'
    $results = Join-Path $runRoot 'results'
    $reuseRows = -not [string]::IsNullOrWhiteSpace($RoutingData)
    if ($reuseRows) {
        $rows = (Resolve-Path -LiteralPath $RoutingData).Path
    } else {
        $rows = Join-Path $runRoot 'routing_train.json'
    }
    $reuseUtility = -not [string]::IsNullOrWhiteSpace($RoutingUtility)
    if ($reuseUtility -and $reuseRows) {
        throw 'Specify only one of -RoutingUtility or -RoutingData.'
    }
    if ($reuseUtility) {
        $plan.inputs.routing_utility = (Resolve-Path -LiteralPath $RoutingUtility).Path
    } else {
        $plan.inputs.routing_utility = Join-Path $fitDir 'routing_utility.json'
    }
    $plan.repeats = $Repeats

    Write-Host "Output: $runRoot"
    $caseCount = @(Get-Content -LiteralPath $plan.inputs.cases -Raw -Encoding UTF8 | ConvertFrom-Json).Count
    Write-Host "Conditions: B0 B1 B2 B3 B4; patients per condition: $caseCount; repeats: $Repeats"
    Write-Host 'B4 is exploratory: unreviewed support annotations imply Unresolved final diagnoses.' -ForegroundColor Yellow
    if (-not $Preview) {
        $null = New-Item -ItemType Directory -Path $runRoot
        # Python json.loads expects UTF-8 without BOM (Windows PowerShell 5 writes a BOM).
        $planText = $plan | ConvertTo-Json -Depth 100
        [System.IO.File]::WriteAllText($runPlan, $planText, (New-Object System.Text.UTF8Encoding($false)))
        Start-Transcript -LiteralPath (Join-Path $runRoot 'pipeline.log') | Out-Null
        $transcribing = $true
    }

    if ($reuseUtility) {
        Write-Host "Skipping collection and fitting; using routing model: $RoutingUtility"
    } elseif ($reuseRows) {
        Write-Host "Using explicitly supplied routing outcomes: $rows"
    } else {
        Write-Host 'Training collection is separate from the evaluation subset (330 calls for the prepared study).'
        Invoke-Stage -Title '1/4 Collect specialty responses (live Ollama calls)' -Arguments @(
            '-m', 'app.scripts.collect_routing_outcomes', '--probes', $probes,
            '--registry', $plan.inputs.registry, '--prices', $plan.inputs.prices, '--output', $rows)
    }
    if (-not $reuseUtility) {
      Invoke-Stage -Title '2/4 Fit routing model' -Arguments @(
        '-m', 'app.scripts.build_research_models', '--evaluation-cases', $plan.inputs.cases,
        '--registry', $plan.inputs.registry, '--routing-data', $rows, '--output-dir', $fitDir)
    }
    Invoke-Stage -Title '3/4 Validate experiment plan (no model calls)' -Arguments @(
        '-m', 'app.scripts.run_paper_experiments', '--plan', $runPlan, '--conditions', 'B0', 'B1', 'B2', 'B3', 'B4')
    Invoke-Stage -Title '4/4 Run B0 B1 B2 B3 B4 sequentially' -Arguments @(
        '-m', 'app.scripts.run_paper_experiments', '--plan', $runPlan,
        '--conditions', 'B0', 'B1', 'B2', 'B3', 'B4', '--execute', '--repeats', [string]$Repeats, '--output-dir', $results)

    if ($Preview) {
        Write-Host "`nPreview only: no files written and no Python/model calls made."
    } else {
        Write-Host "`nFinished. Results: $results" -ForegroundColor Green
    }
} finally {
    if ($transcribing) { Stop-Transcript | Out-Null }
    Pop-Location
}
