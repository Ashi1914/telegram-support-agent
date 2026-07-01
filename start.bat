@echo off
echo Starting Telegram Customer Support AI Agent...

:: Start ngrok in a new window
start "ngrok" cmd /k "ngrok http 8000"

:: Wait for ngrok to initialize
timeout /t 4 /nobreak >nul

:: Get ngrok URL and update .env
echo Fetching ngrok tunnel URL...
for /f "tokens=*" %%i in ('powershell -Command "(Invoke-RestMethod http://localhost:4040/api/tunnels).tunnels[0].public_url"') do set NGROK_URL=%%i
echo ngrok URL: %NGROK_URL%

:: Update WEBHOOK_URL in .env
powershell -Command "[System.IO.File]::WriteAllText((Resolve-Path 'backend\.env').Path, ((Get-Content 'backend\.env' -Raw) -replace 'WEBHOOK_URL=.*', 'WEBHOOK_URL=%NGROK_URL%/webhook'))"
echo Updated .env with new webhook URL.

:: Start FastAPI backend in a new window
start "FastAPI Backend" cmd /k "cd backend && ..\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend to start
echo Waiting for backend to start...
timeout /t 8 /nobreak >nul

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
