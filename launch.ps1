param(
    [switch]$Check,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ApplicationArgs
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$WindowsVenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PosixVenvPython = Join-Path $ProjectRoot ".venv/bin/python"

if (Test-Path -LiteralPath $WindowsVenvPython) {
    $PythonPath = $WindowsVenvPython
} elseif (Test-Path -LiteralPath $PosixVenvPython) {
    $PythonPath = $PosixVenvPython
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        $PythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if ($null -eq $PythonCommand) {
        throw "Python 3.11 or newer was not found. Create .venv and install the project dependencies."
    }
    $PythonPath = $PythonCommand.Source
}

& $PythonPath -c "import sys; assert sys.version_info >= (3, 11); import PIL, PySide6, platformdirs, qtawesome"
if ($LASTEXITCODE -ne 0) {
    throw "ComicAPNG dependencies are unavailable. Run: python -m pip install -e ."
}

$PreviousPythonPath = $env:PYTHONPATH
$SourcePath = Join-Path $ProjectRoot "src"
if ([string]::IsNullOrEmpty($PreviousPythonPath)) {
    $env:PYTHONPATH = $SourcePath
} else {
    $env:PYTHONPATH = $SourcePath + [IO.Path]::PathSeparator + $PreviousPythonPath
}

try {
    if ($Check) {
        & $PythonPath -c "import comicapng"
        if ($LASTEXITCODE -ne 0) {
            throw "ComicAPNG could not be imported from the source tree."
        }
        Write-Output "ComicAPNG source environment is ready."
        $ApplicationExitCode = 0
    } else {
        & $PythonPath -m comicapng @ApplicationArgs
        $ApplicationExitCode = $LASTEXITCODE
    }
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}

exit $ApplicationExitCode
