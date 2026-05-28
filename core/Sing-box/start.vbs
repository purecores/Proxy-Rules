' =========================
' Sing-box Manager (Start/Stop)
' Reference: mihomo toggle vbs pattern
' Modified: use absolute config path on Windows 11
' =========================

Option Explicit

' --- Initialize Objects ---
Dim UAC, WshShell, objWMIService
Set UAC = CreateObject("Shell.Application")
Set WshShell = CreateObject("WScript.Shell")
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")

' --- Configurable Settings ---
Dim exeNamePrimary, exeNameAlt, configFile
exeNamePrimary = "sing-box.exe"
exeNameAlt     = "singbox.exe"

' 使用绝对路径配置文件（注意：VBS 字符串中反斜杠无需额外转义）
configFile     = "D:\Code\Nikki\Config\config.json"

' --- Step 1: Handle Administrator Privileges ---
' Check if the script is running with the /elevate argument
If Not WScript.Arguments.Named.Exists("elevate") Then
    UAC.ShellExecute "wscript.exe", Chr(34) & WScript.ScriptFullName & Chr(34) & " /elevate", "", "runas", 1
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

' sing-box 参数使用最终的 configPath，并确保加引号
startArgs = "run -c " & Chr(34) & configPath & Chr(34)

' --- Step 3: Check if Sing-box is Running ---
Dim colProcesses
Set colProcesses = objWMIService.ExecQuery( _
    "Select * from Win32_Process Where Name = '" & exeNamePrimary & "' OR Name = '" & exeNameAlt & "'" _
)

Dim userChoice
Dim runningExeName
runningExeName = ""

If colProcesses.Count > 0 Then
    ' Determine which exe name is running (for messaging only)
    Dim p
    For Each p In colProcesses
        runningExeName = p.Name
        Exit For
    Next

    ' ================= CASE: ALREADY RUNNING =================
    userChoice = MsgBox( _
        "Sing-box is currently [ RUNNING ]." & vbCrLf & vbCrLf & _
        "Process: " & runningExeName & vbCrLf & vbCrLf & _
        "Do you want to STOP it?", _
        4 + 48 + 256, "Sing-box Manager - Status: Active" _
    )

    If userChoice = 6 Then ' Yes
        ' Kill both possible process names to be safe
        WshShell.Run "taskkill /f /t /im " & exeNamePrimary, 0, True
        WshShell.Run "taskkill /f /t /im " & exeNameAlt, 0, True
        MsgBox "Sing-box has been stopped.", 64, "Success"
    End If

Else
    ' ================= CASE: NOT RUNNING =================
    userChoice = MsgBox( _
        "Sing-box is currently [ STOPPED ]." & vbCrLf & vbCrLf & _
        "Do you want to START it?", _
        4 + 32, "Sing-box Manager - Status: Inactive" _
    )

    If userChoice = 6 Then ' Yes
        ' Choose which exe exists (primary preferred)
        Dim fso, exeToRun
        Set fso = CreateObject("Scripting.FileSystemObject")

        If fso.FileExists(strPath & exeNamePrimary) Then
            exeToRun = exeNamePrimary
        ElseIf fso.FileExists(strPath & exeNameAlt) Then
            exeToRun = exeNameAlt
        Else
            MsgBox "Cannot find sing-box executable in:" & vbCrLf & strPath & vbCrLf & vbCrLf & _
                   "Expected: " & exeNamePrimary & " or " & exeNameAlt, _
                   16, "Error"
            WScript.Quit
        End If

        ' Validate config file
        If Not fso.FileExists(configPath) Then
            MsgBox "Cannot find config file:" & vbCrLf & configPath, 16, "Error"
            WScript.Quit
        End If

        ' Start the process hidden (background)
        ' Use cmd /c with quotes to handle paths safely
        WshShell.Run "cmd /c " & Chr(34) & Chr(34) & exeToRun & Chr(34) & " " & startArgs & Chr(34), 0, False

        MsgBox "Sing-box started in the background." & vbCrLf & vbCrLf & _
               "Executable: " & exeToRun & vbCrLf & _
               "Config: " & configPath, _
               64, "Success"
    End If
End If

' --- Helper: detect absolute path (drive letter or UNC) ---
Function IsAbsolutePath(ByVal p)
    IsAbsolutePath = False
    If Len(p) >= 2 Then
        ' e.g. D:\...
        If Mid(p, 2, 1) = ":" Then IsAbsolutePath = True
    End If
    ' e.g. \\server\share\...
    If Left(p, 2) = "\\" Then IsAbsolutePath = True
End Function
