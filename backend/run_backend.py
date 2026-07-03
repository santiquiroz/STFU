"""Entry point para el binario empaquetado (PyInstaller)."""
import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--apo-admin":
        # modo helper elevado: operación APO en HKLM y salir
        from stfu.apo.admin_cli import main as admin_main
        sys.exit(admin_main(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        from stfu.apo.register import _bundled_apo_dll
        p = _bundled_apo_dll()
        print("frozen:", getattr(sys, "frozen", False))
        print("_MEIPASS:", getattr(sys, "_MEIPASS", None))
        print("executable:", sys.executable)
        print("apo_dll:", p, "exists:", p.exists())
        sys.exit(0)

    import uvicorn
    from stfu.main import app
    uvicorn.run(app, host="127.0.0.1", port=8765, log_config=None)


if __name__ == "__main__":
    main()
