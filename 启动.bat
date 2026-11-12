@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 球队近况
where python >nul 2>nul
if errorlevel 1 (
  echo 没找到 Python，请先安装 Python 3（安装时勾选 Add to PATH）
  pause
  exit /b
)
python app.py
pause
