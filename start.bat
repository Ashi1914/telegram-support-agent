@echo off
echo Starting Telegram Customer Support AI Agent...

:: Start ngrok only if nothing is already listening on its local API port (4040).
:: Ngrok's free tier only allows one agent session at a time, and starting a
:: second one here would either fail outright or fight the existing tunnel.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if %errorlevel%==1 (
    echo ngrok is already running on port 4040 - reusing the existing tunnel.
) else (
    start "ngrok" cmd /k "ngrok http 8000"
    echo Waiting for ngrok to initialize...
    timeout /t 4 /nobreak >nul
)

:: Get ngrok URL and update .env
echo Fetching ngrok tunnel URL...
for /f "tokens=*" %%i in ('powershell -NoProfile -Command "(Invoke-RestMethod http://localhost:4040/api/tunnels).tunnels[0].public_url"') do set NGROK_URL=%%i
echo ngrok URL: %NGROK_URL%

:: Update WEBHOOK_URL in .env
powershell -NoProfile -Command "[System.IO.File]::WriteAllText((Resolve-Path 'backend\.env').Path, ((Get-Content 'backend\.env' -Raw) -replace 'WEBHOOK_URL=.*', 'WEBHOOK_URL=%NGROK_URL%/webhook'))"
echo Updated .env with new webhook URL.

:: Start the backend only if port 8000 is free. Two processes bound to the
:: same port is undefined behaviour on Windows (requests land on whichever
:: one the OS picks) and stopping one can take the other down with it -
:: never start a second instance on top of one that's already running.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if %errorlevel%==1 (
    echo Backend is already running on port 8000 - reusing it, skipping start.
) else (
    start "FastAPI Backend" cmd /k "cd backend && ..\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    echo Waiting for backend to start...
    timeout /t 8 /nobreak >nul
)

:: Register Telegram webhook
echo Registering Telegram webhook...
powershell -Command "try { $r = Invoke-RestMethod http://localhost:8000/admin/webhook/register -Method Post; Write-Host 'Webhook registered:' $r.description } catch { Write-Host 'Webhook registration failed - register manually at http://localhost:8000/docs' }"

echo.
echo ============================================
echo  All services started!
echo  ngrok:   %NGROK_URL%
echo  Backend: http://localhost:8000
echo  Docs:    http://localhost:8000/docs
echo ============================================
pause
