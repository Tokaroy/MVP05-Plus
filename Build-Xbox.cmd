@echo off
setlocal
cd /d "%~dp0"
rem MVP05-Plus for the Xbox (Dev Mode): the app, packed for Device Portal in out\xbox. See docs\XBOX.md.
rem opened by double-click (Explorer runs it as cmd /c "...Build-Xbox.cmd"): keep the window open at the end
set "PAUSE_AT_END="
echo %cmdcmdline% | find /i "/c" >nul && set "PAUSE_AT_END=1"
call :build
set "RESULT=%errorlevel%"
if defined PAUSE_AT_END (
 echo.
 pause
)
exit /b %RESULT%

:build
if not exist "assets\default.xbe" (
 echo Supply your extracted Xbox game in assets first: default.xbe goes directly in assets.
 exit /b 1
)
rem Visual Studio's own clang, CMake and Ninja (its "C++ Clang tools" and "CMake tools" components), when the
rem prompt doesn't have them on PATH (as the release script finds them)
where clang++ >nul 2>&1
if errorlevel 1 if defined VSINSTALLDIR if exist "%VSINSTALLDIR%VC\Tools\Llvm\x64\bin\clang++.exe" set "PATH=%VSINSTALLDIR%VC\Tools\Llvm\x64\bin;%PATH%"
where clang++ >nul 2>&1
if errorlevel 1 if exist "%ProgramFiles%\LLVM\bin\clang++.exe" set "PATH=%ProgramFiles%\LLVM\bin;%PATH%"
where cmake >nul 2>&1
if errorlevel 1 if defined VSINSTALLDIR set "PATH=%VSINSTALLDIR%Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;%PATH%"
where ninja >nul 2>&1
if errorlevel 1 if defined VSINSTALLDIR set "PATH=%VSINSTALLDIR%Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%"
where clang++ >nul 2>&1
if errorlevel 1 (
 echo clang isn't installed: in the Visual Studio Installer, Modify, Individual components, tick
 echo "C++ Clang Compiler for Windows" and "C++ CMake tools for Windows" ^(or: winget install LLVM.LLVM^).
 echo Then open "x64 Native Tools Command Prompt for VS" from the Start menu, then in it: cd /d "%~dp0" and run Build-Xbox.cmd.
 exit /b 1
)
if not defined VCToolsInstallDir (
 echo Run this from "x64 Native Tools Command Prompt for VS".
 exit /b 1
)
if not exist "%VCToolsInstallDir%lib\x64\store\msvcrt.lib" (
 echo Visual Studio's app runtime libraries aren't installed. In the Visual Studio Installer, add the
 echo "Universal Windows Platform development" workload with its "C++ (v143) Universal Windows Platform tools".
 exit /b 1
)

echo == 1. The game's code, recompiled from your default.xbe (the PC build's step)
cmake --preset release
if errorlevel 1 exit /b 1
cmake --build --preset release --target recompile_MVP05
if errorlevel 1 exit /b 1

echo == 2. The Xbox app
rem the C++ runtime for apps (vcruntime140_app) in place of the PC's
set "LIB=%VCToolsInstallDir%lib\x64\store;%LIB%"
cmake --preset xbox-release
if errorlevel 1 exit /b 1
cmake --build --preset xbox-release --target MVP05 --parallel 4
if errorlevel 1 exit /b 1

echo == 3. The app package
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\xbox\Package-Xbox.ps1"
if errorlevel 1 exit /b 1
exit /b 0
