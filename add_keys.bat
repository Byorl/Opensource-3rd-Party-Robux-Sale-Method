@echo off
title ByorlHub Key Manager
color 0b
cls

:menu
echo.
echo  ========================================
echo           ByorlHub Key Manager        
echo  ========================================
echo.
echo  [1] Check Stock Status
echo  [2] Add 7-Day Keys
echo  [3] Add 30-Day Keys
echo  [4] Exit
echo.
set /p choice="Select an option (1-4): "

if "%choice%"=="1" goto status
if "%choice%"=="2" goto add7day
if "%choice%"=="3" goto add30day
if "%choice%"=="4" goto exit
echo Invalid choice. Please try again.
pause
cls
goto menu

:status
cls
echo.
echo ========================================
echo           Current Stock Status       
echo ========================================
echo.
python github_key_generator.py status
echo.
pause
cls
goto menu

:add7day
cls
echo.
echo ========================================
echo           Add 7-Day Keys             
echo ========================================
echo.
set /p count="How many 7-day keys to generate? "
if "%count%"=="" (
    echo No number entered. Returning to menu...
    pause
    cls
    goto menu
)
echo.
echo Do you want to generate a custom amount or use the default?
echo [1] Use entered amount (%count%)
echo [2] Enter custom amount
echo.
set /p custom_choice="Select option (1-2): "

if "%custom_choice%"=="2" (
    set /p count="Enter custom amount for 7-day keys: "
    if "%count%"=="" (
        echo No number entered. Returning to menu...
        pause
        cls
        goto menu
    )
)

echo.
echo Generating %count% 7-day keys...
python github_key_generator.py %count% 7d
echo.
pause
cls
goto menu

:add30day
cls
echo.
echo ========================================
echo           Add 30-Day Keys            
echo ========================================
echo.
set /p count="How many 30-day keys to generate? "
if "%count%"=="" (
    echo No number entered. Returning to menu...
    pause
    cls
    goto menu
)
echo.
echo Do you want to generate a custom amount or use the default?
echo [1] Use entered amount (%count%)
echo [2] Enter custom amount
echo.
set /p custom_choice="Select option (1-2): "

if "%custom_choice%"=="2" (
    set /p count="Enter custom amount for 30-day keys: "
    if "%count%"=="" (
        echo No number entered. Returning to menu...
        pause
        cls
        goto menu
    )
)

echo.
echo Generating %count% 30-day keys...
python github_key_generator.py %count% 30d
echo.
pause
cls
goto menu

:exit
cls
echo.
echo Thanks for using ByorlHub Key Manager!
echo.
timeout /t 2 /nobreak >nul
exit
