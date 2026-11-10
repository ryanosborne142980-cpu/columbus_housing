# Registers the weekly job for the current user: Mondays at 7:00, or as soon as the laptop is next on
# and online if it was off or asleep. It runs only while this user is logged on, so no password is stored.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\register_weekly_task.ps1
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $python -Argument 'scripts\weekly.py' -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 7:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'ColumbusHousingWeekly' -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'Columbus housing weekly load, backup and Databricks landing' -Force
