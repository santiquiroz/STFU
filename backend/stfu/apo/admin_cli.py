"""CLI para operaciones APO que requieren admin — se ejecuta ELEVADO vía UAC.

El backend (sin privilegios) relanza su propio ejecutable con estos flags
usando ShellExecute 'runas'; este proceso corto hace la escritura en HKLM
y termina. Exit code 0 = ok.
"""
import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stfu-apo-admin")
    sub = parser.add_subparsers(dest="op", required=True)

    sub.add_parser("enable-unsigned")

    reg = sub.add_parser("register")
    reg.add_argument("endpoint_guid")
    reg.add_argument("flow", choices=["Capture", "Render"])
    reg.add_argument("apo_clsid")

    unreg = sub.add_parser("unregister")
    unreg.add_argument("endpoint_guid")
    unreg.add_argument("flow", choices=["Capture", "Render"])

    args = parser.parse_args(argv)
    from stfu.apo import register as reg_mod

    try:
        if args.op == "enable-unsigned":
            reg_mod.enable_unsigned_apos()
        elif args.op == "register":
            reg_mod.register_apo(args.endpoint_guid, args.flow, args.apo_clsid)
        elif args.op == "unregister":
            reg_mod.unregister_apo(args.endpoint_guid, args.flow)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
