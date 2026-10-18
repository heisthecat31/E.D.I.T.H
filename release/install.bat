@echo off
rem E.D.I.T.H installer: finds Echo VR (Spark's settings, else asks), refuses nEVR, installs the
rem plugin loader if there isn't one, then EDITH.dll, EDITH.ini, her map package and her voice.
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
if exist "%GAME%\BugSplat64.dll" (
    for %%F in ("%GAME%\BugSplat64.dll") do set "BSIZE=%%~zF"
    if !BSIZE! gtr 665600 (
        set "BHASH="
        for /f "skip=1 delims=" %%H in ('%SYS%\certutil.exe -hashfile "%GAME%\BugSplat64.dll" SHA256 2^>nul') do if not defined BHASH set "BHASH=%%H"
        set "BHASH=!BHASH: =!"
        if /i not "!BHASH!"=="%STOCK_BUGSPLAT_SHA256%" (
            echo   nEVR is installed in this Echo VR ^(its BugSplat64.dll is !BSIZE! bytes, the original is 630,288^).
            echo   E.D.I.T.H does not work with nEVR, so nothing was installed.
            echo.
            echo   Press a key to close.
            pause >nul
            exit /b 1
        )
    )
)

rem ---- 4. the plugin loader ---------------------------------------------------------------------
set "LOADER_NEW=0"
if not exist "%GAME%\plugins\" (
    echo   No plugins folder: installing the plugin loader ^(dbgcore.dll^).
    if exist "%GAME%\dbgcore.dll" copy /y "%GAME%\dbgcore.dll" "%GAME%\dbgcore.dll.edith-backup" >nul
    copy /y "%FILES%\loader\dbgcore.dll" "%GAME%\dbgcore.dll" >nul || goto :copyfail
    mkdir "%GAME%\plugins" || goto :copyfail
    set "LOADER_NEW=1"
) else (
    echo   Plugin loader already there: keeping it.
)

rem ---- 5. E.D.I.T.H -------------------------------------------------------------------------------
set "P=%GAME%\plugins"
copy /y "%FILES%\plugins\EDITH.dll" "%P%\EDITH.dll" >nul || goto :copyfail
if exist "%P%\EDITH.ini" (
    copy /y "%FILES%\plugins\EDITH.ini" "%P%\EDITH.ini.new" >nul
    echo   Kept your EDITH.ini ^(the new default is EDITH.ini.new^).
) else (
    copy /y "%FILES%\plugins\EDITH.ini" "%P%\EDITH.ini" >nul || goto :copyfail
)
if exist "%P%\EDITH\cache" rd /s /q "%P%\EDITH\cache"
"%SYS%\robocopy.exe" "%FILES%\plugins\EDITH" "%P%\EDITH" /e /njh /njs /ndl /nfl /nc /ns /np >nul
if errorlevel 8 goto :copyfail
echo   Copying her voice ^(about 200 MB^)...
"%SYS%\robocopy.exe" "%FILES%\plugins\EdithVoice" "%P%\EdithVoice" /e /njh /njs /ndl /nfl /nc /ns /np >nul
if errorlevel 8 goto :copyfail
echo.
echo   Done. E.D.I.T.H is installed: start Echo VR and go to the lobby.
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
