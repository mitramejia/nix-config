@echo off
echo Read guest-awake.ps1 on this read-only disc before running it.
echo Opening the official Xbox Accessories Store listing; install is your choice.
start "" "ms-windows-store://pdp/?ProductId=9NBLGGH30XJ3"
echo Run this in Windows PowerShell when ready, then keep that window open:
echo powershell -NoProfile -File "%~dp0guest-awake.ps1"
echo No script runs automatically. Do not bypass execution policy.
pause
