@echo off
setlocal
if defined CHATSYNC_PYTHON goto custom_python
if exist "%~dp0.venv\Scripts\python.exe" goto project_python
if exist "%LOCALAPPDATA%\Python\bin\python.exe" goto installed_python
py -3 -X utf8 "%~dp0chat_sync.py" %*
exit /b %errorlevel%
:installed_python
"%LOCALAPPDATA%\Python\bin\python.exe" -X utf8 "%~dp0chat_sync.py" %*
exit /b %errorlevel%
:custom_python
"%CHATSYNC_PYTHON%" -X utf8 "%~dp0chat_sync.py" %*
exit /b %errorlevel%

:project_python
"%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0chat_sync.py" %*
exit /b %errorlevel%
