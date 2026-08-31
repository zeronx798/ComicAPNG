@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    set "PYTHON_COMMAND="%VENV_PYTHON%""
    goto validate
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_COMMAND=python"
    goto validate
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_COMMAND=py -3.11"
    goto validate
)

echo Python 3.11 or newer was not found. Create .venv and install the project dependencies. 1>&2
exit /b 1

:validate
%PYTHON_COMMAND% -c "import sys; assert sys.version_info >= (3, 11); import PIL, PySide6, platformdirs, qtawesome"
if errorlevel 1 (
    echo ComicAPNG dependencies are unavailable. Run: python -m pip install -e . 1>&2
    exit /b 1
)

if defined PYTHONPATH (
    set "PYTHONPATH=%PROJECT_ROOT%src;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%PROJECT_ROOT%src"
)

if /i "%~1"=="--check" (
    %PYTHON_COMMAND% -c "import comicapng"
    if errorlevel 1 (
        echo ComicAPNG could not be imported from the source tree. 1>&2
        exit /b 1
    )
    echo ComicAPNG source environment is ready.
    exit /b 0
)

%PYTHON_COMMAND% -m comicapng %*
set "APPLICATION_EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %APPLICATION_EXIT_CODE%
