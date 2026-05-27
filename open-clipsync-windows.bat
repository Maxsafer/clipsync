@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -Command "$p=((Get-Content .env -EA SilentlyContinue | Select-String '^CLIPSYNC_PORT=') -split '=',2)[1]; if($p){$p=$p.Trim().Trim([char]34).Trim([char]39)}; if(-not $p){$p=8080}; $ip=(Find-NetRoute -RemoteIPAddress 8.8.8.8)[0].IPAddress; $u='http://'+$ip+':'+$p; Write-Host ('Opening ' + $u); Start-Process $u"
