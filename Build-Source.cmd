@echo off
setlocal
cd /d "%~dp0"
rem opened by double-click (Explorer runs it as cmd /c "...Build-Source.cmd"): keep the window open at the end
set "PAUSE_AT_END="
echo %cmdcmdline% | find /i "/c" >nul && set "PAUSE_AT_END=1"
if defined MVP_NO_PAUSE set "PAUSE_AT_END="
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
 echo MVP05-Plus Launcher can put it there for you: python tools\installer\install.py --xbox "your Xbox image or folder" --dir .
 echo See START-HERE.txt.
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
 echo Then open "x64 Native Tools Command Prompt for VS" from the Start menu, then in it: cd /d "%~dp0" and run Build-Source.cmd.
 exit /b 1
)
cmake --preset release
if errorlevel 1 exit /b 1
cmake --build --preset release --target MVP05 --parallel 4
if errorlevel 1 exit /b 1
copy /y "out\build\release\MVP05.exe" "MVP05.exe" >nul
if errorlevel 1 exit /b 1
rem Microsoft's shader compiler beside the exe under its own name, which the game loads first: under Proton
rem (SteamOS) the system's d3dcompiler_47 is Wine's, which can't compile the game's shaders (a black screen)
set "D3DC="
if defined WindowsSdkDir if exist "%WindowsSdkDir%Redist\D3D\x64\d3dcompiler_47.dll" set "D3DC=%WindowsSdkDir%Redist\D3D\x64\d3dcompiler_47.dll"
if not defined D3DC if exist "%ProgramFiles(x86)%\Windows Kits\10\Redist\D3D\x64\d3dcompiler_47.dll" set "D3DC=%ProgramFiles(x86)%\Windows Kits\10\Redist\D3D\x64\d3dcompiler_47.dll"
if not defined D3DC if exist "%SystemRoot%\System32\d3dcompiler_47.dll" set "D3DC=%SystemRoot%\System32\d3dcompiler_47.dll"
if defined D3DC copy /y "%D3DC%" "d3dcompiler_ms.dll" >nul
if not defined D3DC echo No d3dcompiler_47.dll found to copy: under Proton, copy one beside the exe as d3dcompiler_ms.dll.
echo Built MVP05.exe beside assets. No game was launched.
exit /b 0
