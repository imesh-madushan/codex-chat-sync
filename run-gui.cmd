@echo off
setlocal
if defined CHATSYNC_PYTHON goto custom_python
if exist "%~dp0.venv\Scripts\pythonw.exe" goto project_python
if exist "%LOCALAPPDATA%\Python\bin\pythonw.exe" goto installed_python
where pyw >nul 2>nul
if errorlevel 1 goto missing_python
start "" pyw -3 -X utf8 "%~dp0chat_sync_gui.py" %*
exit /b %errorlevel%

:installed_python
start "" "%LOCALAPPDATA%\Python\bin\pythonw.exe" -X utf8 "%~dp0chat_sync_gui.py" %*
exit /b %errorlevel%

:custom_python
for %%I in ("%CHATSYNC_PYTHON%") do set "CHATSYNC_GUI_PYTHON=%%~dpIpythonw.exe"
if not exist "%CHATSYNC_GUI_PYTHON%" goto missing_python
start "" "%CHATSYNC_GUI_PYTHON%" -X utf8 "%~dp0chat_sync_gui.py" %*
exit /b %errorlevel%

:project_python
start "" "%~dp0.venv\Scripts\pythonw.exe" -X utf8 "%~dp0chat_sync_gui.py" %*
exit /b %errorlevel%

:missing_python
echo Cannot find a windowless Python interpreter. Install Python with pythonw.exe or use python chat_sync_gui.py for diagnostics.
exit /b 1
