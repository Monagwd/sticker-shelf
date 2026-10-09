@echo off
chcp 65001 >nul
cd /d %~dp0
py -3 server.py 2>nul || python server.py
pause
