' --- Initialize Objects ---
Set UAC = CreateObject("Shell.Application")
Set WshShell = CreateObject("WScript.Shell")
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")

' --- Step 1: Handle Administrator Privileges ---
' Check if the script is running with the /elevate argument
If Not WScript.Arguments.Named.Exists("elevate") Then
    UAC.ShellExecute "wscript.exe", Chr(34) & WScript.ScriptFullName & Chr(34) & " /elevate", "", "runas", 1
    WScript.Quit
End If

' --- Step 2: Set Working Directory ---
' Essential for Mihomo to find config.yaml
strPath = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
WshShell.CurrentDirectory = strPath

' --- Step 3: Check if Mihomo is Running ---
' Query the list of running processes for mihomo.exe
Set colProcesses = objWMIService.ExecQuery("Select * from Win32_Process Where Name = 'mihomo.exe'")

Dim userChoice

' --- Step 4: Logic based on Process Status ---
If colProcesses.Count > 0 Then
    ' ================= CASE: ALREADY RUNNING =================
    ' 4 = vbYesNo
    ' 48 = vbExclamation (Warning icon)
    ' 256 = Default button is "No" (to prevent accidental stopping)
    userChoice = MsgBox("Mihomo is currently [ RUNNING ]." & vbCrLf & vbCrLf & _
                        "Do you want to STOP it?", _
                        4 + 48 + 256, "Mihomo Manager - Status: Active")

    If userChoice = 6 Then ' 6 = Yes
        ' Kill the process
        WshShell.Run "taskkill /f /t /im mihomo.exe", 0, True
        MsgBox "Mihomo has been stopped.", 64, "Success"
    End If

Else
    ' ================= CASE: NOT RUNNING =================
    ' 4 = vbYesNo
    ' 32 = vbQuestion (Question icon)
    userChoice = MsgBox("Mihomo is currently [ STOPPED ]." & vbCrLf & vbCrLf & _
                        "Do you want to START it?", _
                        4 + 32, "Mihomo Manager - Status: Inactive")

    If userChoice = 6 Then ' 6 = Yes
        ' Start the process hidden
        WshShell.Run "cmd /c mihomo.exe -f ""D:\Code\Nikki\Config\config.yaml""", 0, False
        MsgBox "Mihomo started in the background.", 64, "Success"
    End If

End If