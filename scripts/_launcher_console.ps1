# Retorna 10 apenas se este cmd /c for dono de um console interativo novo.
# Usa APIs nativas do Windows; nao depende de Python nem de pacotes do projeto.
$ErrorActionPreference = 'Stop'
if ($env:AGENTSCLOUD_NO_PAUSE -eq '1') { exit 0 }
if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) { exit 0 }

try {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AgentsCloudConsole {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern uint GetConsoleProcessList(uint[] ids, uint count);
}
'@
    $launcherSelf = Get-CimInstance Win32_Process -Filter "ProcessId = $PID"
    $launcherParentId = $launcherSelf.ParentProcessId
    $launcherParent = Get-CimInstance Win32_Process -Filter "ProcessId = $launcherParentId"
    if ($launcherParent.Name -ine 'cmd.exe') { exit 0 }
    $launcherCapacity = 16
    do {
        $launcherIds = New-Object uint32[] $launcherCapacity
        $launcherCount = [AgentsCloudConsole]::GetConsoleProcessList($launcherIds, $launcherCapacity)
        if ($launcherCount -eq 0) { exit 0 }
        if ($launcherCount -le $launcherCapacity) { break }
        $launcherCapacity = $launcherCount
    } while ($true)
    foreach ($launcherId in $launcherIds[0..($launcherCount - 1)]) {
        if ($launcherId -ne $PID -and $launcherId -ne $launcherParentId) { exit 0 }
    }
    # Examina as opcoes de inicializacao do cmd, antes do comando/arquivo.
    # Um cmd interativo, inclusive /k, nao deve ganhar pausa do lancador.
    $launcherTokens = [regex]::Matches($launcherParent.CommandLine, '"[^"]*"|\S+')
    for ($launcherIndex = 1; $launcherIndex -lt $launcherTokens.Count; $launcherIndex++) {
        $launcherToken = $launcherTokens[$launcherIndex].Value
        if ($launcherToken -match '^/[kK]') { exit 0 }
        if ($launcherToken -match '^/[cC]') { exit 10 }
        if (-not $launcherToken.StartsWith('/')) { exit 0 }
    }
} catch {
    # Falha fechada: nunca bloqueia automacao quando o console nao pode ser identificado.
    exit 0
}
exit 0
