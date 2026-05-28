' =========================
' Sing-box Silent Stopper
' - Silently kills sing-box core process (sing-box.exe / singbox.exe)
' - Auto-elevates to admin (UAC prompt may appear)
' - No message boxes, no visible console window
' =========================

Option Explicit

Dim UAC, WshShell, objWMIService
Set UAC = CreateObject("Shell.Application")
Set WshShell = CreateObject("WScript.Shell")
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")

Dim exeNamePrimary, exeNameAlt
exeNamePrimary = "sing-box.exe"
exeNameAlt     = "singbox.exe"

' --- Step 1: Handle Administrator Privileges ---
If Not WScript.Arguments.Named.Exists("elevate") Then
    ' 0 = hidden window; runas triggers UAC prompt when needed
    UAC.ShellExecute "wscript.exe", Chr(34) & WScript.ScriptFullName & Chr(34) & " /elevate", "", "runas", 0
    WScript.Quit
End If

' --- Step 2: Check if Sing-box is Running (optional, for clean exit) ---
Dim colProcesses
Set colProcesses = objWMIService.ExecQuery( _
    "Select * from Win32_Process Where Name = '" & exeNamePrimary & "' OR Name = '" & exeNameAlt & "'" _
)

If colProcesses.Count = 0 Then
    ' Not running: exit silently
    WScript.Quit
End If

' --- Step 3: Force kill both possible names (silent) ---
' /f = force, /t = kill child processes, /im = by image name
WshShell.Run "taskkill /f /t /im " & exeNamePrimary, 0, True
WshShell.Run "taskkill /f /t /im " & exeNameAlt, 0, True

' Exit silently
WScript.Quit
