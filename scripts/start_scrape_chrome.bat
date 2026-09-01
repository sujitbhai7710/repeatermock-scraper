@echo off
REM Starts a dedicated Chrome instance with remote debugging enabled.
REM Log into Google + https://repeatermock.com ONCE in this window, then
REM leave it open — the scraper connects to it for automatic re-login.

set CHROME_EXE="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_EXE% set CHROME_EXE="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_EXE% (
    echo Chrome not found in default locations. Edit this file to set CHROME_EXE.
    pause
    exit /b 1
)

start "" %CHROME_EXE% --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\repeatermock-chrome" --no-first-run --no-default-browser-check https://repeatermock.com/login

echo.
echo Chrome started with remote debugging on port 9222.
echo Log into Google + repeatermock.com in that window ONCE.
echo Keep this Chrome window OPEN while the scraper is running.
