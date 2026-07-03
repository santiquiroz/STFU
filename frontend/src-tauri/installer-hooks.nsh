; Hooks NSIS de STFU: garantizan una instalación limpia sin restos de la
; versión anterior. Sin esto, el backend/UI corriendo bloquea archivos y deja
; una mezcla de binarios viejos y nuevos (fuente de inestabilidad al probar).

!macro NSIS_HOOK_PREINSTALL
  ; matar UI y backend de cualquier versión previa antes de copiar archivos
  nsExec::Exec 'taskkill /F /IM STFU.exe /T'
  nsExec::Exec 'taskkill /F /IM stfu-backend.exe /T'
  Sleep 500
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /IM STFU.exe /T'
  nsExec::Exec 'taskkill /F /IM stfu-backend.exe /T'
  Sleep 500
!macroend
