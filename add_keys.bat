@echo off
echo ByorlHub Key Generator
echo =====================
echo.
echo Usage: add_keys.bat [count] [type]
echo Examples:
echo   add_keys.bat 50     (adds 50 keys to 7-day stock)
echo   add_keys.bat 25 30d (adds 25 keys to 30-day stock)
echo.

if "%1"=="" (
    echo Please specify number of keys to generate
    echo Example: add_keys.bat 50
    pause
    exit /b
)

if "%2"=="" (
    python github_key_generator.py %1
) else (
    python github_key_generator.py %1 %2
)

pause
