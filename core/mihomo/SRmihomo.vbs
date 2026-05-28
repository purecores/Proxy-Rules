' =========================
' Silent Restart (mihomo + sing-box)
' - Detects if mihomo or sing-box core is running
' - If running: kills ALL (mihomo.exe / sing-box.exe / singbox.exe)
' - Then silently starts mihomo core
' - Auto-elevates to admin (UAC prompt may appear)
' - No message boxes, no visible console window
' =========================

Option Explicit

' ================== 可配置项 ==================
Const MIHOMO_EXE  = "mihomo.exe"   ' 也可以写全路径：C:\Tools\mihomo\mihomo.exe
Const CONFIG_PATH = "D:\Code\Nikki\Config\config.yaml"  ' 按需修改
Const WAIT_TIMEOUT_MS = 12000      ' 等待停止的超时时间（毫秒）
' ==============================================

Dim UAC, WshShell, objWMIService
Set UAC = CreateObject("Shell.Application")
Set WshShell = CreateObject("WScript.Shell")
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")

' --- 提权（静默自提权；UAC弹窗无法避免）---
If Not WScript.Arguments.Named.Exists("elevate") Then
    UAC.ShellExecute "wscript.exe", Chr(34) & WScript.ScriptFullName & Chr(34) & " /elevate", "", "runas", 0
    WScript.Quit
End If

' --- 工作目录设为脚本目录（便于同目录启动 mihomo.exe）---
WshShell.CurrentDirectory = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

' --- 需要检测/处理的内核进程名 ---
Dim pMihomo, pSingPrimary, pSingAlt
pMihomo = "mihomo.exe"
pSingPrimary = "sing-box.exe"
pSingAlt = "singbox.exe"

' --- Step 1: 检测是否有任一内核正在运行 ---
If IsProcessRunning(objWMIService, pMihomo) Or _
   IsProcessRunning(objWMIService, pSingPrimary) Or _
   IsProcessRunning(objWMIService, pSingAlt) Then

    ' --- Step 2: 如运行，则全部杀死（防止端口/规则占用）---
    ' 用 cmd /c 包裹以避免命令窗口，且忽略不存在的进程错误输出
    WshShell.Run "cmd /c taskkill /f /t /im " & pMihomo & " >nul 2>&1", 0, True
    WshShell.Run "cmd /c taskkill /f /t /im " & pSingPrimary & " >nul 2>&1", 0, True
    WshShell.Run "cmd /c taskkill /f /t /im " & pSingAlt & " >nul 2>&1", 0, True

    ' --- Step 3: 等待它们确实退出（避免重启时端口仍被占用）---
    WaitUntilAllStopped objWMIService, pMihomo, pSingPrimary, pSingAlt, WAIT_TIMEOUT_MS
End If

' --- Step 4: 启动 mihomo（隐藏窗口，非阻塞）---
' 说明：若 MIHOMO_EXE 不是全路径，请确保 mihomo.exe 在脚本目录或 PATH 中
WshShell.Run "cmd /c " & QuoteIfNeeded(MIHOMO_EXE) & " -f " & Chr(34) & CONFIG_PATH & Chr(34), 0, False

WScript.Quit


' ================== 函数区 ==================

Function IsProcessRunning(wmiSvc, exeName)
    Dim col, q
    q = "SELECT * FROM Win32_Process WHERE Name='" & exeName & "'"
    Set col = wmiSvc.ExecQuery(q)
    IsProcessRunning = (col.Count > 0)
End Function

Sub WaitUntilAllStopped(wmiSvc, exe1, exe2, exe3, timeoutMs)
    Dim t0
    t0 = Timer

    Do
        If (Not IsProcessRunning(wmiSvc, exe1)) And _
           (Not IsProcessRunning(wmiSvc, exe2)) And _
           (Not IsProcessRunning(wmiSvc, exe3)) Then
            Exit Do
        End If

        WScript.Sleep 200

        If ElapsedMs(t0) >= timeoutMs Then
            Exit Do
        End If
    Loop
End Sub

Function ElapsedMs(tStart)
    Dim tNow, dt
    tNow = Timer
    dt = tNow - tStart
    If dt < 0 Then dt = dt + 86400 ' 跨午夜回绕
    ElapsedMs = CLng(dt * 1000)
End Function

Function QuoteIfNeeded(s)
    ' 如果是全路径且包含空格，则加引号；纯文件名则不强制加引号也可
    If InStr(s, " ") > 0 And Left(s, 1) <> Chr(34) Then
        QuoteIfNeeded = Chr(34) & s & Chr(34)
    Else
        QuoteIfNeeded = s
    End If
End Function
