' =========================
' Sing-box Silent Starter (Windows 11)
' - If mihomo or sing-box is running, kill both (silent)
' - Then start sing-box silently
' - Auto-elevates to admin (may show UAC prompt)
' - No message boxes, no visible console window
' =========================

Option Explicit

' --- Initialize Objects ---
Dim UAC, WshShell, objWMIService
Set UAC = CreateObject("Shell.Application")
Set WshShell = CreateObject("WScript.Shell")
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")

' --- Configurable Settings ---
Dim exeMihomo, exeSingPrimary, exeSingAlt, configFile
exeMihomo      = "mihomo.exe"
exeSingPrimary = "sing-box.exe"
exeSingAlt     = "singbox.exe"

' 参考你现有 start.vbs：这里使用绝对路径配置文件
configFile = "D:\Code\Nikki\Config\config.json"

' --- Step 1: Handle Administrator Privileges ---
If Not WScript.Arguments.Named.Exists("elevate") Then
    ' 0 = hidden window
    UAC.ShellExecute "wscript.exe", Chr(34) & WScript.ScriptFullName & Chr(34) & " /elevate", "", "runas", 0
    WScript.Quit
End If

' --- Step 2: Set Working Directory ---
Dim strPath
strPath = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
WshShell.CurrentDirectory = strPath

' --- Step 2.1: Resolve config path (absolute/relative safe handling) ---
Dim configPath, startArgs
If IsAbsolutePath(configFile) Then
    configPath = configFile
Else
    configPath = strPath & configFile
End If

startArgs = "run -c " & Chr(34) & configPath & Chr(34)

' --- Step 3: Detect running processes (mihomo or sing-box) ---
Dim q, col
q = "Select * from Win32_Process Where Name='" & exeMihomo & "'" & _
    " OR Name='" & exeSingPrimary & "'" & _
    " OR Name='" & exeSingAlt & "'"

Set col = objWMIService.ExecQuery(q)

' --- Step 4: If any is running, kill all of them (silent) ---
If col.Count > 0 Then
    ' Kill both sing-box names (in case you have different builds)
    WshShell.Run "taskkill /f /t /im " & exeSingPrimary, 0, True
    WshShell.Run "taskkill /f /t /im " & exeSingAlt, 0, True
    ' Kill mihomo
    WshShell.Run "taskkill /f /t /im " & exeMihomo, 0, True
End If

' --- Step 5: Choose sing-box executable to run (primary preferred) ---
Dim fso, exeToRun
Set fso = CreateObject("Scripting.FileSystemObject")

If fso.FileExists(strPath & exeSingPrimary) Then
    exeToRun = exeSingPrimary
ElseIf fso.FileExists(strPath & exeSingAlt) Then
    exeToRun = exeSingAlt
Else
    ' Silent exit if not found (no MsgBox per requirement)
    WScript.Quit
End If

' --- Step 6: Validate config file (silent exit if missing) ---
If Not fso.FileExists(configPath) Then
    WScript.Quit
End If

' --- Step 7: Start sing-box hidden (background) ---
' Use cmd /c with quotes to handle paths safely
WshShell.Run "cmd /c " & Chr(34) & Chr(34) & exeToRun & Chr(34) & " " & startArgs & Chr(34), 0, False

WScript.Quit

' --- Helper: detect absolute path (drive letter or UNC) ---
Function IsAbsolutePath(ByVal p)
    IsAbsolutePath = False
    If Len(p) >= 2 Then
        If Mid(p, 2, 1) = ":" Then IsAbsolutePath = True
    End If
    If Left(p, 2) = "\\" Then IsAbsolutePath = True
End Function
