@echo off
setlocal
rem Builds out\tools\adpcm_tool.dll (plugin\edith_adpcm.h for tools\make_voice_banks.py), then
rem out\edith_voice.bin: her voice lines as Wwise banks (ADPCM). Arguments go to make_voice_banks.py.
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
if not exist out\tools mkdir out\tools
if not exist out\obj_tools mkdir out\obj_tools
cl.exe /nologo /LD /O2 /W3 /Foout\obj_tools\ /Fe"out\tools\adpcm_tool.dll" tools\adpcm_tool.c
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
python -I tools\make_voice_banks.py %*
