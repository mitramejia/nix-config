# Optional: inspect, then run in Windows PowerShell on the guest before Update.
# Keep THIS SAME window/thread alive until the official update is finished.
# No persistent power policy or execution-policy changes.
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class XboxFirmwareAwake {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern uint SetThreadExecutionState(uint flags);
}
'@
try {
    $previous = [XboxFirmwareAwake]::SetThreadExecutionState([uint32]2147483651)
    if ($previous -eq 0) { throw 'Sleep inhibition failed; do not start the update.' }
    Write-Host 'Guest awake. Leave this window running. After verified completion press Ctrl+C.'
    while ($true) { Start-Sleep -Seconds 1 }
} finally {
    [void][XboxFirmwareAwake]::SetThreadExecutionState([uint32]2147483648)
}
