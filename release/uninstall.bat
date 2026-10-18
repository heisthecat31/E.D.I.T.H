@echo off
rem E.D.I.T.H uninstaller: finds Echo VR the same way as install.bat and removes EDITH.dll, EDITH.ini,
rem her map package and her voice. The plugin loader (dbgcore.dll) stays: other mods use it (user).
setlocal EnableExtensions EnableDelayedExpansion
rem Windows' own tools by full path: a PATH with Git's Unix tools first made "find /i" crawl the I: drive
set "SYS=%SystemRoot%\System32"
title E.D.I.T.H uninstaller
echo.
echo   E.D.I.T.H uninstaller
echo   =====================
echo.

set "GAME="
set "SPARK=%APPDATA%\IgniteVR\Spark\settings.json"
set "SPARKPATH="
if exist "%SPARK%" (
    for /f "usebackq delims=" %%P in (`%SYS%\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { (Get-Content -Raw -LiteralPath $env:SPARK | ConvertFrom-Json).echoVRPath } catch { }"`) do set "SPARKPATH=%%P"
)
if defined SPARKPATH (
    call :resolve "!SPARKPATH!"
    if defined FOUND (
        echo   Spark says Echo VR is here:
        echo     !FOUND!
        echo.
        "%SYS%\choice.exe" /c YN /m "  Is this the right Echo VR"
        if !errorlevel! equ 1 set "GAME=!FOUND!"
        echo.
    )
)
:ask
if not defined GAME (
    echo   Where is Echo VR? Drag its folder ^(or echovr.exe^) into this window and press Enter.
    set "ANSWER="
    set /p "ANSWER=  > "
    if not defined ANSWER goto :cancel
    set ANSWER=!ANSWER:"=!
    call :resolve "!ANSWER!"
    if not defined FOUND (
        echo.
        echo   No echovr.exe there. Try again, or press Enter on an empty line to cancel.
        echo.
        goto :ask
    )
    set "GAME=!FOUND!"
)
set "P=%GAME%\plugins"
if not exist "%P%\EDITH.dll" if not exist "%P%\EDITH\" (
    echo   E.D.I.T.H isn't installed in %GAME%.
    goto :end
)
"%SYS%\tasklist.exe" /fi "imagename eq echovr.exe" /nh 2>nul | "%SYS%\findstr.exe" /i /c:"echovr.exe" >nul
if not errorlevel 1 (
    echo   Echo VR is running. Close it, then press a key.
    pause >nul
)

del /q "%P%\EDITH.dll" "%P%\EDITH.ini" "%P%\EDITH.ini.new" 2>nul
if exist "%P%\EDITH" rd /s /q "%P%\EDITH"
if exist "%P%\EdithVoice" rd /s /q "%P%\EdithVoice"
if exist "%P%\EDITH.dll" ( echo   EDITH.dll is in use: close Echo VR and run this again. & goto :end )
echo   Removed E.D.I.T.H from %P%. The plugin loader stays for your other mods.

echo.
echo   Done.
goto :end

:resolve
set "FOUND="
set "R=%~1"
if not defined R exit /b
if "!R:~-1!"=="\" set "R=!R:~0,-1!"
if /i "!R:~-10!"=="echovr.exe" (
    if exist "!R!" for %%D in ("!R!") do set "FOUND=%%~dpD"
) else if exist "!R!\echovr.exe" (
    set "FOUND=!R!"
) else if exist "!R!\bin\win10\echovr.exe" (
    set "FOUND=!R!\bin\win10"
)
if defined FOUND if "!FOUND:~-1!"=="\" set "FOUND=!FOUND:~0,-1!"
exit /b

:cancel
echo   Cancelled: nothing was removed.
:end
echo.
echo   Press a key to close.
pause >nul
exit /b 0
