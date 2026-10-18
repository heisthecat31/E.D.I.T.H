@echo off
setlocal
rem Builds out\plugin\EDITH.dll (the satellite's behaviour, agent.md S19) like EchoCombat's plugins.
set "EC=J:\EchoVR-Tools-Launcher\EchoCombat"
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
if not exist out\plugin mkdir out\plugin
if not exist out\obj mkdir out\obj
cl.exe /nologo /LD /MT /O2 /EHa /W3 /I"%EC%\third_party\detours" /I"%EC%\plugin" /DECHOCOMBAT_LOG /Foout\obj\ /Fe"out\plugin\EDITH.dll" plugin\satellite.cpp plugin\edith_net.cpp plugin\edith_pack.cpp plugin\edith_ears.cpp "%EC%\third_party\detours\detours.lib" user32.lib ws2_32.lib winhttp.lib ole32.lib
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
del /q out\plugin\*.exp out\plugin\*.lib 2>nul
echo Built out\plugin\EDITH.dll
