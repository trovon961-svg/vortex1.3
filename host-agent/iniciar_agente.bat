@echo off
chcp 65001 >nul
REM Roda como administrador: necessario para jogos que exigem elevacao e para os controles funcionarem neles
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
REM Vortex - agente do PC (gerado pelo site). Nao compartilhe este arquivo.
set "VORTEX_SITE=https://game-vortex--2kdpwp6t.preview.emergentagent.com"
set "VORTEX_EMAIL=admin@vortex.gg"
set "VORTEX_PASS=vortex123"
REM Usuario e senha da interface web do Sunshine (https://localhost:47990)
set "SUNSHINE_USER=felp"
set "SUNSHINE_PASS=Felp#0818"
REM janela = transmite SO a janela do jogo (recomendado) | tela = tela inteira
set "VORTEX_CAPTURA=janela"
REM Opcional: dispositivo de audio a transmitir (ex.: Mixagem estereo)
set "VORTEX_AUDIO="
REM Segundos sem ninguem jogando ate fechar o jogo no PC
set "VORTEX_FECHAR_APOS=60"
cd /d "%~dp0"
python -m pip install --disable-pip-version-check -q websockets pillow vgamepad
python vortex_agent.py
pause
