@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo == 文隐 TextVeil · 打包 Windows 版 ==
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo 没有找到 Python。请先安装 https://www.python.org/downloads/windows/ ，安装时勾选 Add Python to PATH & pause & exit /b 1)
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt || (echo 依赖安装失败，请检查网络 & pause & exit /b 1)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --noconfirm --clean --windowed --name "TextVeil" --icon assets\icon.ico --add-data "ui;ui" --paths .. --collect-submodules textveil --version-file version_info.txt textveil_desktop.py || (echo 打包失败 & pause & exit /b 1)
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\TextVeil\*' -DestinationPath 'dist\TextVeil-win-x64-portable.zip'"
where iscc >nul 2>nul && (iscc /Q installer.iss && echo 已生成安装包 dist\TextVeil-1.0.0-win-x64-setup.exe)
echo.
echo 完成：%CD%\dist\TextVeil\TextVeil.exe
echo 首次运行如出现“Windows 已保护你的电脑”，点“更多信息”→“仍要运行”（程序没有代码签名）。
explorer dist
pause
