@echo off
rem E.D.I.T.H installer: finds Echo VR (Spark's settings, else asks), then puts EDITH.dll into its
rem plugins folder. EDITH.dll is all of her (voice, lobby data, settings) and runs under nEVR and under
rem the plain plugin loader alike: with nEVR it turns on nEVR's local plugins (x-local-plugins: true in
rem _local\config.yaml) so the launcher loads her; without nEVR it adds the plugin loader if there's none.
setlocal EnableExtensions EnableDelayedExpansion
rem Windows' own tools by full path: a PATH with Git's Unix tools first made "find /i" crawl the I: drive
set "SYS=%SystemRoot%\System32"
title E.D.I.T.H installer
set "HERE=%~dp0"
set "FILES=%HERE%files"
set "STOCK_BUGSPLAT_SHA256=618e34d3bfde69846c0202d42951366bff5e03cd2885b6825f55e09fb2cf160b"
echo.
echo   E.D.I.T.H  -  the satellite for the Echo VR lobby
echo   ================================================
echo.
if not exist "%FILES%\plugins\EDITH.dll" (
    echo   The "files" folder is missing. Extract the whole zip first, then run install.bat again.
    goto :fail
)

rem ---- 1. find Echo VR -----------------------------------------------------------------------
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
    echo   ^(For example C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena^)
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
echo   Echo VR found at: %GAME%
echo.

rem ---- 2. Echo must be closed ------------------------------------------------------------------
"%SYS%\tasklist.exe" /fi "imagename eq echovr.exe" /nh 2>nul | "%SYS%\findstr.exe" /i /c:"echovr.exe" >nul
if not errorlevel 1 (
    echo   Echo VR is running. Close it, then press a key.
    pause >nul
    "%SYS%\tasklist.exe" /fi "imagename eq echovr.exe" /nh 2>nul | "%SYS%\findstr.exe" /i /c:"echovr.exe" >nul
    if not errorlevel 1 ( echo   Echo VR is still running. & goto :fail )
)

rem ---- 3. nEVR? (its BugSplat64.dll replaces the stock one and is far bigger) -----------------
set "NEVR=0"
if exist "%GAME%\BugSplat64.dll" (
    for %%F in ("%GAME%\BugSplat64.dll") do set "BSIZE=%%~zF"
    if !BSIZE! gtr 665600 (
        set "BHASH="
        for /f "skip=1 delims=" %%H in ('%SYS%\certutil.exe -hashfile "%GAME%\BugSplat64.dll" SHA256 2^>nul') do if not defined BHASH set "BHASH=%%H"
        set "BHASH=!BHASH: =!"
        if /i not "!BHASH!"=="%STOCK_BUGSPLAT_SHA256%" set "NEVR=1"
    )
)
if not exist "%GAME%\plugins\" mkdir "%GAME%\plugins" || goto :copyfail

if "%NEVR%"=="1" (
    rem nEVR loads only the plugins its config lists; the launcher writes that config before every
    rem start and keeps a DLL put into plugins\ by hand only with local plugins on
    echo   nEVR is installed: E.D.I.T.H runs as an nEVR plugin.
    for %%R in ("%GAME%\..\..") do set "ROOT=%%~fR"
    if not exist "!ROOT!\_local\" mkdir "!ROOT!\_local"
    set "CFG=!ROOT!\_local\config.yaml"
    "%SYS%\findstr.exe" /r /c:"^x-local-plugins: *true" "!CFG!" >nul 2>nul
    if errorlevel 1 (
        if exist "!CFG!" (
            copy /y "!CFG!" "!CFG!.edith-backup" >nul
            ( echo x-local-plugins: true& type "!CFG!.edith-backup" ) > "!CFG!" || goto :copyfail
        ) else (
            ( echo x-local-plugins: true ) > "!CFG!" || goto :copyfail
        )
        echo   Turned on nEVR's local plugins ^(x-local-plugins: true in _local\config.yaml^).
    )
) else (
    rem ---- the plugin loader: bin\win10\dbgcore.dll (the game loads it itself) ------------------
    if not exist "%GAME%\dbgcore.dll" (
        echo   Installing the plugin loader ^(dbgcore.dll^).
        copy /y "%FILES%\loader\dbgcore.dll" "%GAME%\dbgcore.dll" >nul || goto :copyfail
    ) else (
        echo   Plugin loader already there: keeping it.
    )
)

rem ---- 4. E.D.I.T.H -------------------------------------------------------------------------------
set "P=%GAME%\plugins"
copy /y "%FILES%\plugins\EDITH.dll" "%P%\EDITH.dll" >nul || goto :copyfail
rem an older release's files: her lobby data and voice are inside EDITH.dll now, and an old
rem plugins\EDITH\*.edith would be loaded over the built-in one
if exist "%P%\EDITH\" rd /s /q "%P%\EDITH"
if exist "%P%\EdithVoice\" rd /s /q "%P%\EdithVoice"
echo.
echo   Done. E.D.I.T.H is installed: start Echo VR and go to the lobby.
if "%NEVR%"=="1" echo   ^(Start it from the Echo VR launcher as usual; she shows on its Mods page as a local plugin.^)
echo.
pause
exit /b 0

rem ---- helpers -------------------------------------------------------------------------------------
rem :resolve <path>  ->  FOUND = the folder holding echovr.exe (from echovr.exe, bin\win10 or the game root)
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

:copyfail
echo.
echo   Copying failed. Is Echo VR closed, and can this folder be written to? Nothing else was changed after that point.
goto :fail
:cancel
echo   Cancelled: nothing was installed.
:fail
echo.
echo   Press a key to close.
pause >nul
exit /b 1
