@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Ставит всё нужное в папку .venv рядом со скриптом. Запускать один раз после git clone/pull.

set PY=
rem Проверяем кандидатов запуском: у py бывают записи на удалённые установки.
for %%C in ("python" "%ProgramFiles%\Python314\python.exe" "%ProgramFiles%\Python313\python.exe" "%ProgramFiles%\Python312\python.exe") do (
  if not defined PY (
    "%%~C" -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul && set PY="%%~C"
  )
)
if not defined PY (
  py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul && set PY=py -3
)
if not defined PY (
  echo Не нашёл рабочий Python 3.10+. Поставь его с python.org и запусти снова.
  pause
  exit /b 1
)
echo Python: %PY%

if not exist .venv\Scripts\python.exe (
  echo Создаю .venv ...
  %PY% -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail

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
echo Готово.
pause
exit /b 0

:fail
echo.
echo Ошибка установки, смотри сообщения выше.
pause
exit /b 1
