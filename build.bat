@echo off
rem ===========================================================================
rem  Raiden Shadow - one-shot packaging script.
rem
rem    build.bat            make sure the baked art exists, package with
rem                         PyInstaller, zip + sha256, then boot the frozen
rem                         exe headless for a 240-frame self-test
rem    build.bat full       the same, after the quality gate (ruff/mypy/pytest)
rem    build.bat gate       quality gate only, no packaging
rem    build.bat rebake     re-derive every shipped texture first (slow:
rem                         tileset, maps, sprite sources, sprite sheets)
rem    build.bat nozip      build the folder, skip the zip + checksum
rem    build.bat noverify   skip the frozen-exe self-test
rem    build.bat console    keep a console window in the built exe
rem    build.bat pause      wait for a keypress at the end (double-click use)
rem    build.bat help       show this text
rem
rem  Output:  dist\RaidenShadow\RaidenShadow.exe
rem           dist\RaidenShadow.zip  (+ dist\RaidenShadow.zip.sha256)
rem  Everything under dist\ and build\ is disposable.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "GATE=0"
set "BUILD=1"
set "VERIFY=1"
set "WAIT=0"
set "BUILDFLAGS="
set "PYTHON="

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="full"     set "GATE=1"         & shift & goto parse
if /i "%~1"=="gate"     set "GATE=1" & set "BUILD=0" & shift & goto parse
if /i "%~1"=="rebake"   set "REBAKE=1"       & shift & goto parse
if /i "%~1"=="nozip"    set "BUILDFLAGS=%BUILDFLAGS% --no-zip"  & shift & goto parse
if /i "%~1"=="noverify" set "VERIFY=0"       & shift & goto parse
if /i "%~1"=="console"  set "BUILDFLAGS=%BUILDFLAGS% --console" & shift & goto parse
if /i "%~1"=="pause"    set "WAIT=1"         & shift & goto parse
if /i "%~1"=="help"     goto usage
if /i "%~1"=="--help"   goto usage
echo unknown option: %~1
echo.
goto usage

:parsed
call :find_python || goto fail

if "%GATE%"=="1" call :gate || goto fail
if "%BUILD%"=="0" (
  echo.
  echo quality gate passed, nothing packaged
  call :maybe_pause
  endlocal
  exit /b 0
)

call :ensure_art || goto fail

echo.
echo packaging ...
call %PYTHON% scripts\build.py %BUILDFLAGS% || goto fail

if "%VERIFY%"=="0" goto report
echo.
echo self-testing the frozen exe (240 frames, dummy video and audio) ...
set "SDL_VIDEODRIVER=dummy"
set "SDL_AUDIODRIVER=dummy"
"dist\RaidenShadow\RaidenShadow.exe" --self-test 240 || goto fail

:report
echo.
echo ---------------------------------------------------------------------------
if exist "dist\RaidenShadow\RaidenShadow.exe" (
  echo   exe      dist\RaidenShadow\RaidenShadow.exe
  for %%s in ("dist\RaidenShadow\RaidenShadow.exe") do echo   size    %%~zs bytes
)
if exist "dist\RaidenShadow.zip" (
  echo   archive  dist\RaidenShadow.zip
  for %%s in ("dist\RaidenShadow.zip") do echo   size    %%~zs bytes
  echo   sha256   type dist\RaidenShadow.zip.sha256
)
echo   run:      dist\RaidenShadow\RaidenShadow.exe
echo ---------------------------------------------------------------------------
call :maybe_pause
endlocal
exit /b 0

:fail
echo.
echo BUILD FAILED - see the output above.
call :maybe_pause
endlocal
exit /b 1

rem ---------------------------------------------------------------------------
rem  python 3.10+ on PATH ('py -3' preferred, then 'python')
rem ---------------------------------------------------------------------------
:find_python
where py >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON where python >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON (
  echo python 3.10 or newer was not found on PATH.
  exit /b 1
)
for /f "delims=" %%v in ('%PYTHON% -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%v"
echo using python %PYVER%
exit /b 0

rem ---------------------------------------------------------------------------
rem  ruff / mypy / pytest.  A missing tool is a note, a failing one is fatal:
rem  packaging is not the place to discover a broken commit.
rem ---------------------------------------------------------------------------
:gate
call :tool ruff check src scripts tests || exit /b 1
call :tool mypy src                     || exit /b 1
call :tool pytest -q                    || exit /b 1
exit /b 0

:tool
%PYTHON% -m %~1 --version >nul 2>&1
if errorlevel 1 (
  echo %~1 is not installed - skipping ^(pip install -e .[dev] to enable^)
  exit /b 0
)
echo.
echo %~1 ...
%PYTHON% -m %*
if errorlevel 1 (
  echo.
  echo %~1 reported problems, refusing to package.
  exit /b 1
)
exit /b 0

rem ---------------------------------------------------------------------------
rem  Shipped art is generated but committed; only re-derive what is missing.
rem  scripts/build.py refuses to package an incomplete data tree, so this runs
rem  before it and a fresh clone works from a double-click.
rem ---------------------------------------------------------------------------
:ensure_art
if defined REBAKE (
  echo rebaking every texture, this takes a few minutes ...
  call %PYTHON% scripts\bake_tiles.py       || exit /b 1
  call %PYTHON% scripts\bake_terrain.py     || exit /b 1
  if exist "assets\textures\sprites_raw" call %PYTHON% scripts\bake_sprite_raws.py || exit /b 1
  call %PYTHON% scripts\bake_sprites.py     || exit /b 1
  exit /b 0
)
if not exist "data\textures\tiles\manifest.json" (
  echo tileset missing, baking tiles ...
  call %PYTHON% scripts\bake_tiles.py       || exit /b 1
)
if not exist "data\textures\terrain\1_countryside_base.png" (
  echo baked maps missing, baking terrain ...
  call %PYTHON% scripts\bake_terrain.py     || exit /b 1
)
if not exist "data\textures\sprites\e_boss9.png" (
  echo sprite sheets missing, baking sprites ...
  if exist "assets\textures\sprites_raw" call %PYTHON% scripts\bake_sprite_raws.py || exit /b 1
  call %PYTHON% scripts\bake_sprites.py     || exit /b 1
)
exit /b 0

rem ---------------------------------------------------------------------------
rem  Pause only when launched by double-clicking in Explorer; never when a
rem  shell, CI or an agent invoked the script.  %cmdcmdline% is expanded
rem  through a variable so metacharacters in the command line stay inert.
rem ---------------------------------------------------------------------------
rem ---------------------------------------------------------------------------
rem  Never pause on our own: CI, an agent, or a script that calls this one would
rem  block forever waiting on a console nobody is watching.  Double-click use
rem  opts in with 'build.bat pause'.
rem ---------------------------------------------------------------------------
:maybe_pause
if not "%WAIT%"=="1" exit /b 0
echo.
pause
exit /b 0

:usage
echo usage: build.bat [full ^| gate ^| rebake ^| nozip ^| noverify ^| console ^| pause]
echo.
echo   full      quality gate, then package, zip, checksum and self-test
echo   gate      run ruff, mypy and pytest, package nothing
echo   rebake    re-derive data\textures from assets\ first (slow)
echo   nozip     leave the build unpacked
echo   noverify  do not boot the built exe
echo   console   build with a console window for diagnostics
echo   pause     wait for a keypress before closing (double-click use)
exit /b 2
