param(
    [Parameter(Mandatory = $true)][string]$Rtl,
    [Parameter(Mandatory = $true)][string]$Testbench,
    [string]$WorkDir = "verilog/build",
    [string]$Top = "",
    [string]$OutName = "",
    [string]$Signals = "",
    [string]$Times = "",
    [string]$Model = "auto"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Log = New-TemporaryFile

function Get-VcdFromLog {
    param([string]$LogPath)
    foreach ($line in Get-Content $LogPath -ErrorAction SilentlyContinue) {
        if ($line -match '^VCD:\s*(.+)') { return $Matches[1].Trim() }
    }
    return $null
}

try {
    $simArgs = @{
        Rtl        = $Rtl
        Testbench  = $Testbench
        WorkDir    = $WorkDir
    }
    if ($Top) { $simArgs.Top = $Top }
    if ($OutName) { $simArgs.OutName = $OutName }

    & "$ScriptDir\sim.ps1" @simArgs *>&1 | Tee-Object -FilePath $Log.FullName
    $SimExit = $LASTEXITCODE

    $Vcd = Get-VcdFromLog -LogPath $Log.FullName

    if ($Signals -and $Vcd -and (Test-Path $Vcd)) {
        $peekArgs = @("$ScriptDir\vcd_peek.py", "--vcd", $Vcd, "--signals", $Signals)
        if ($Times) { $peekArgs += @("--times", $Times) }
        & python @peekArgs
    }

    if ($SimExit -eq 1 -and $Vcd -and (Test-Path $Vcd)) {
        Write-Host "==> fail_triage"
        & python "$ScriptDir\fail_triage.py" --vcd $Vcd --log $Log.FullName --model $Model
    }

    exit $SimExit
} finally {
    Remove-Item -Force $Log.FullName -ErrorAction SilentlyContinue
}
