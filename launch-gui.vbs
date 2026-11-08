' Start the archive window with no console. Double-click this file, or let run.bat call it.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("Wscript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
On Error Resume Next
code = sh.Run("pyw -3 -m discord_archiver gui", 0, True)
If Err.Number <> 0 Then
  MsgBox "Could not start Python." & vbCrLf & vbCrLf & "Install Python 3.10 or newer from python.org and check Add python.exe to PATH." & vbCrLf & Err.Description, 16, "Discord archiver"
  WScript.Quit 1
End If
On Error GoTo 0
If code <> 0 Then
  MsgBox "Discord archiver could not start (exit " & code & ")." & vbCrLf & vbCrLf & "From this folder, run:" & vbCrLf & "py -3 -m discord_archiver gui", 16, "Discord archiver"
End If
