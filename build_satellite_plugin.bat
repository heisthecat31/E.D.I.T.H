@echo off
setlocal
rem Builds out\plugin\EDITH.dll: the satellite's behaviour (agent.md S19), her voice banks and her
rem lobby data in one DLL that runs under nEVR (NvrPluginInitEx) and under the dbgcore plugin loader
rem (DllMain) alike (docs/nevr_plan.md). out\edith_voice.bin comes from build_voice_banks.bat.
rem The nEVR ABI header is EchoCombat's nevr-pack worktree's; logdir.h is EchoCombat main's.
rem The EchoCombat checkouts beside this repo (override with EC= / ECN= in the environment)
if not defined EC set "EC=%~dp0..\EchoCombat"
if not defined ECN set "ECN=%~dp0..\EchoCombat-nevr"
set "VARS_BAT="
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
        if exist "%%i\VC\Auxiliary\Build\vcvars64.bat" set "VARS_BAT=%%i\VC\Auxiliary\Build\vcvars64.bat"
    )
)
if not defined VARS_BAT (
    echo [ERROR] MSVC not found.
    exit /b 1
)
if not defined VSCMD_ARG_TGT_ARCH call "%VARS_BAT%" >nul
cd /d "%~dp0"
set /p VER=<VERSION
for /f "tokens=1-3 delims=." %%a in ("%VER%") do set "VMAJ=%%a" & set "VMIN=%%b" & set "VPAT=%%c"
if not exist out\plugin mkdir out\plugin
if not exist out\obj mkdir out\obj
if not exist out\edith_voice.bin ( echo [ERROR] out\edith_voice.bin missing: run build_voice_banks.bat & exit /b 1 )
rc.exe /nologo /fo out\obj\edith.res plugin\edith.rc
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
cl.exe /nologo /LD /MT /O2 /EHa /W3 /std:c++17 /I"%EC%\third_party\detours" /I"%ECN%\plugin" /I"%EC%\plugin" /DECHOCOMBAT_LOG /DEDITH_VERSION_MAJOR=%VMAJ% /DEDITH_VERSION_MINOR=%VMIN% /DEDITH_VERSION_PATCH=%VPAT% /Foout\obj\ /Fe"out\plugin\EDITH.dll" plugin\satellite.cpp plugin\edith_net.cpp plugin\edith_pack.cpp plugin\edith_ears.cpp plugin\edith_voice.cpp out\obj\edith.res "%EC%\third_party\detours\detours.lib" user32.lib ws2_32.lib winhttp.lib ole32.lib
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
del /q out\plugin\*.exp out\plugin\*.lib 2>nul
echo Built out\plugin\EDITH.dll (%VER%)
