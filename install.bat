@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Ставит всё нужное рядом со скриптом. Запускать после git clone и после каждого git pull.
rem Системный Python не нужен и не трогается: uv сам скачает Python нужной версии в tools\python,
rem создаст .venv на нём и поставит туда пакеты. PATH и реестр не меняются.

set PYVER=3.13
set "TOOLS=%~dp0tools"
set "UV=%TOOLS%\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%TOOLS%\python"
set "UV_CACHE_DIR=%TOOLS%\cache"
set UV_PYTHON_PREFERENCE=only-managed

set "UV_URL=https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
if not exist "%UV%" (
  echo Качаю uv ...
  if not exist "%TOOLS%" mkdir "%TOOLS%"
  rem Сначала встроенным PowerShell, если его нет — встроенными curl.exe и tar.exe (Windows 10 1803+)
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing '%UV_URL%' -OutFile '%TOOLS%\uv.zip'; Expand-Archive -Force '%TOOLS%\uv.zip' '%TOOLS%'" 2>nul
  if not exist "%UV%" (
    curl.exe -L -f -o "%TOOLS%\uv.zip" "%UV_URL%" && tar.exe -xf "%TOOLS%\uv.zip" -C "%TOOLS%"
  )
  if exist "%TOOLS%\uv.zip" del "%TOOLS%\uv.zip"
  if not exist "%UV%" (
    echo Не получилось скачать uv. Скачай руками этот файл и распакуй uv.exe в папку tools:
    echo %UV_URL%
    goto :fail
  )
)

echo Ставлю Python %PYVER% в tools\python ...
"%UV%" python install %PYVER% || goto :fail

rem Если .venv собран на другой версии Python — пересобираем
if exist .venv\pyvenv.cfg (
  findstr /c:"version_info = %PYVER%." .venv\pyvenv.cfg >nul || (
    echo .venv на другой версии Python, пересоздаю ...
    rmdir /s /q .venv
  )
)
if not exist .venv\Scripts\python.exe (
  "%UV%" venv --python %PYVER% .venv || goto :fail
)
"%UV%" pip install --python .venv\Scripts\python.exe -r requirements.txt || goto :fail

rem Робот открывает обычный Google Chrome. Если Chrome нет — ставим браузер Playwright.
if not exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" if not exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
  echo Chrome не найден, ставлю Chromium для Playwright ...
  .venv\Scripts\python.exe -m playwright install chromium || goto :fail
)

if not exist config.json (
  copy config.example.json config.json >nul
  echo Создан config.json — впиши в него токен бота, api_id и api_hash.
)
echo.
.venv\Scripts\python.exe --version
echo Готово.
pause
exit /b 0

:fail
echo.
echo Ошибка установки, смотри сообщения выше.
pause
exit /b 1
