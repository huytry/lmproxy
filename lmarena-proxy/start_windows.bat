@echo off
start "" python "%~dp0proxy_server.py"
start "" "https://lmarena.ai"
start "" "http://localhost:9080/monitor"
exit