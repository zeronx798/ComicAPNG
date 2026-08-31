$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Invoke-CheckedPython {
    & $PythonPath @args
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

Push-Location $ProjectRoot
try {
    Invoke-CheckedPython -m pip install -e "$ProjectRoot[dev]"
    Invoke-CheckedPython -m pytest
    Invoke-CheckedPython (Join-Path $ProjectRoot "scripts\check_source_ascii.py")
    Invoke-CheckedPython -m ruff check .
    Invoke-CheckedPython (Join-Path $ProjectRoot "scripts\validate_packaging.py")
    Invoke-CheckedPython -m PyInstaller --clean --noconfirm (Join-Path $ProjectRoot "ComicAPNG.spec")
    Invoke-CheckedPython (Join-Path $ProjectRoot "scripts\validate_frozen_archive.py")

    $PreviousQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        $Executable = Join-Path $ProjectRoot "dist\ComicAPNG.exe"
        $Process = Start-Process -FilePath $Executable -ArgumentList "--packaging-smoke-test" -Wait -PassThru -WindowStyle Hidden
        if ($Process.ExitCode -ne 0) {
            throw "Frozen application smoke test failed with exit code $($Process.ExitCode)."
        }
    } finally {
        $env:QT_QPA_PLATFORM = $PreviousQtPlatform
    }
} finally {
    Pop-Location
}
