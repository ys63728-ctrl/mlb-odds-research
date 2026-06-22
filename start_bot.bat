@echo off
title MLB-NPB Odds Bot (auto-restart) - DO NOT CLOSE
cd /d "C:\Users\user\Desktop\mlb-odds-research"

echo ============================================================
echo  MLB/NPB Odds Bot - auto-restart launcher
echo  Keep this window open. Closing it stops the bot.
echo ============================================================

:loop
echo.
echo [%date% %time%] Starting bot...
"C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe" scripts\run_bot.py
echo [%date% %time%] Bot exited. Restarting in 20 seconds...
ping -n 21 127.0.0.1 >nul
goto loop
