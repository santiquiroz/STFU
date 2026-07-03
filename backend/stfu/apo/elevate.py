"""Relanza el propio proceso elevado (UAC) para operaciones APO en HKLM."""
import logging
import re
import subprocess
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

# Los args interpolan en una línea de PowerShell que corre ELEVADA: solo
# tokens de forma conocida (ops, flows, GUIDs, --flags, módulos con puntos).
_SAFE_ARG = re.compile(r"^[A-Za-z0-9{}.\-_]+$")


def _quote_arg(a: str) -> str:
    if not _SAFE_ARG.fullmatch(a):
        raise ValueError(f"argumento inválido para operación elevada: {a!r}")
    return "'" + a.replace("'", "''") + "'"


def _helper_command(op_args: list[str]) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        # binario PyInstaller: el mismo exe con --apo-admin
        return sys.executable, ["--apo-admin", *op_args]
    return sys.executable, ["-m", "stfu.apo.admin_cli", *op_args]


def run_elevated(op_args: list[str]) -> None:
    """Ejecuta la operación APO con UAC y espera. Lanza RuntimeError si falla
    o el usuario cancela el prompt."""
    exe, args = _helper_command(op_args)
    arg_list = ",".join(_quote_arg(a) for a in args)
    # -WindowStyle es incompatible con -Verb (parameter sets distintos)
    ps = (
        f"$p = Start-Process -FilePath '{exe}' -ArgumentList {arg_list} "
        f"-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
    )
    _log.info("elevando operación APO: %s %s", Path(exe).name, " ".join(args))
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"operación elevada falló (código {result.returncode}) — "
            "¿se canceló el UAC?"
        )
