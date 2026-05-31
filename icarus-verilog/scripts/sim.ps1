param(
    [Parameter(Mandatory = $true)]
    [string]$Rtl,

    [Parameter(Mandatory = $true)]
    [string]$Testbench,

    [string]$WorkDir = "verilog/build",

    [string]$Top = "",

    [string]$OutName = "",

    [string]$Iverilog = "iverilog"
)

$ErrorActionPreference = "Stop"

function Resolve-Tool {
    param([string]$Name, [string[]]$Fallbacks)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($path in $Fallbacks) {
        if (Test-Path $path) { return $path }
    }
    throw "Tool not found: $Name. Install Icarus Verilog or add to PATH."
}

function Invoke-Verdict {
    param([string]$Stdout, [int]$SimExit)
    if ($SimExit -ne 0) {
        Write-Host "SIMULATION FAILED (runtime exit $SimExit)"
        return $SimExit
    }
    if ($Stdout -match "ALL TESTS PASSED" -and $Stdout -notmatch "FAILED:") {
        Write-Host "SIMULATION OK"
        return 0
    }
    if ($Stdout -match "FAILED:") {
        Write-Host "SIMULATION FAILED (functional)"
        return 1
    }
    Write-Host "SIMULATION INCONCLUSIVE (no verdict)"
    Write-Host "Hint: add check task and print ALL TESTS PASSED / FAILED: N errors for auto judgment."
    Write-Host "      Or review stdout and vcd_peek output manually."
    return 2
}

function Get-VcdPathFromStdout {
    param([string]$Stdout, [string]$WorkDir)
    $patterns = @(
        'VCD info:\s+dumpfile\s+(\S+)\s+opened',
        '\$dumpfile\s*\(\s*"([^"]+\.vcd)"\s*\)',
        'dumpfile\s+(\S+\.vcd)\s+opened'
    )
    foreach ($pat in $patterns) {
        if ($Stdout -match $pat) {
            $rel = $Matches[1]
            if ([System.IO.Path]::IsPathRooted($rel)) { return $rel }
            return (Join-Path $WorkDir $rel)
        }
    }
    return $null
}

$iverilogBin = Resolve-Tool $Iverilog @(
    "C:\iverilog\bin\iverilog.exe",
    "$env:ProgramFiles\iverilog\bin\iverilog.exe"
)
$vvpBin = Resolve-Tool "vvp" @(
    "C:\iverilog\bin\vvp.exe",
    "$env:ProgramFiles\iverilog\bin\vvp.exe"
)

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$tbBase = [System.IO.Path]::GetFileNameWithoutExtension($Testbench)
if (-not $OutName) { $OutName = $tbBase }

$vvpOut = Join-Path $WorkDir "$OutName.vvp"
$vvpLeaf = Split-Path $vvpOut -Leaf
$rtlFiles = @($Rtl -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$sourceFiles = $rtlFiles + @($Testbench)

$compileArgs = @("-g2012", "-Wall", "-o", $vvpOut)
if ($Top) { $compileArgs += @("-s", $Top) }
$compileArgs += $sourceFiles

Write-Host "==> compile: $iverilogBin $($compileArgs -join ' ')"
Write-Host "    OutName: $OutName.vvp$(if ($Top) { "  Top(-s): $Top" })"

& $iverilogBin @compileArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "COMPILE FAILED (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Host "==> simulate: $vvpBin $vvpOut"
Push-Location $WorkDir
try {
    $simOutput = & $vvpBin $vvpLeaf 2>&1 | ForEach-Object { "$_" }
    $simExit = $LASTEXITCODE
    $simText = $simOutput -join "`n"
    if ($simText) { Write-Host $simText }
} finally {
    Pop-Location
}

$workAbs = (Resolve-Path $WorkDir).Path
$vcdPath = Get-VcdPathFromStdout -Stdout $simText -WorkDir $workAbs
if ($vcdPath -and (Test-Path $vcdPath)) {
    Write-Host "VCD: $vcdPath"
} else {
    Write-Host "WARN: could not parse VCD path from stdout"
}

exit (Invoke-Verdict -Stdout $simText -SimExit $simExit)
