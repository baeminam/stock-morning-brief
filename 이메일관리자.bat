@echo off
REM 일일 종목 분석 리포트 - 수신자 관리 앱 실행기
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0tools\email_manager.py"
