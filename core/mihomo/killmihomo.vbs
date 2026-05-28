' =========================
' Mihomo Silent Stopper
' - Silently kills mihomo.exe if running
' - Auto-elevates to admin (may show UAC prompt)
' - No message boxes, no visible console window
' =========================

Option Explicit

Dim UAC, WshShell, objWMIService
Set UAC = CreateObject("Shell.Application")
Set WshShell = CreateObject("WScript.Shell")
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")

Dim exeName
exeName = "mihomo.exe"

' --- Step 1: Handle Administrator Privileges ---
If Not WScript.Arguments.Named.Exists("elevate") Then
    ' 0 = hidden window
    UAC.ShellExecute "wscript.exe", Chr(34) & WScript.ScriptFullName & Chr(34) & " /elevate", "", "runas", 0
    WScript.Quit
End If

' --- Step 2: Set Working Directory (optional, aligns with start.vbs style) ---
Dim strPath
strPath = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
WshShell.CurrentDirectory = strPath

' --- Step 3: Check if Mihomo is Running ---
Dim colProcesses
Set colProcesses = objWMIService.ExecQuery("Select * from Win32_Process Where Name = '" & exeName & "'")

If colProcesses.Count = 0 Then
    ' Not running: exit silently
    WScript.Quit
End If

' --- Step 4: Force kill (silent) ---
WshShell.Run "taskkill /f /t /im " & exeName, 0, True

WScript.Quit
