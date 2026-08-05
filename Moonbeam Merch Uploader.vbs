' Moonbeam Merch Uploader — Windows silent launcher
' Launches the GUI without showing a terminal/console window.
' To create a Taskbar shortcut:
'   1. Right-click this file → "Create shortcut"
'   2. Right-click the shortcut → Properties → Change Icon → browse to AppIcon.ico
'   3. Drag the shortcut to the Taskbar (pin to taskbar)

Option Explicit

Dim WshShell, fso, scriptDir, pyExe, guiScript

Set WshShell = WScript.CreateObject("WScript.Shell")
Set fso = WScript.CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' --- Locate pythonw.exe (runs without a console window) --------------------
Function FindPython()
  Dim candidates, candidate
  candidates = Array( _
    WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
    WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"), _
    WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"), _
    WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"), _
    "pythonw.exe", _
    "python.exe" _
  )
  For Each candidate In candidates
    On Error Resume Next
    If fso.FileExists(candidate) Then
      FindPython = candidate
      Exit Function
    End If
    On Error GoTo 0
  Next
  FindPython = "pythonw.exe"
End Function

pyExe    = FindPython()
guiScript = scriptDir & "\shopify_uploader_gui.py"

If Not fso.FileExists(guiScript) Then
  MsgBox "Could not find shopify_uploader_gui.py next to this launcher." & vbCrLf & _
         "Expected: " & guiScript, vbCritical, "Moonbeam Merch Uploader"
  WScript.Quit 1
End If

WshShell.CurrentDirectory = scriptDir
' 0 = hidden window; False = don't wait for it to finish
WshShell.Run Chr(34) & pyExe & Chr(34) & " " & Chr(34) & guiScript & Chr(34), 0, False
