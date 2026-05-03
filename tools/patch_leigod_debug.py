"""Patch LeiGod app.asar to enable Electron DevTools/CDP on 127.0.0.1.

Usage:
  python patch_leigod_debug.py          # patch, default port 9222
  python patch_leigod_debug.py --port 9333
  python patch_leigod_debug.py --restore

Requires Node.js/npm because it uses: npx asar extract/pack
Run in an elevated terminal if Program Files is not writable.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ASAR = Path(r"C:\Program Files (x86)\LeiGod_Acc\resources\app.asar")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def kill_leigod() -> None:
    for image in ("leigod.exe", "leigod_launcher.exe", "leishenSdk.exe"):
        subprocess.run(["taskkill", "/IM", image, "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch LeiGod app.asar to enable CDP remote debugging")
    ap.add_argument("--asar", default=str(DEFAULT_ASAR), help="Path to app.asar")
    ap.add_argument("--port", default="9222", help="DevTools port")
    ap.add_argument("--restore", action="store_true", help="Restore app.asar.bak")
    ap.add_argument("--no-kill", action="store_true", help="Do not kill LeiGod processes first")
    args = ap.parse_args()

    asar = Path(args.asar)
    backup = asar.with_suffix(asar.suffix + ".bak")
    work = Path(__file__).resolve().parent / "patch_app"

    if not asar.exists():
        print(f"not found: {asar}")
        return 1

    if not args.no_kill:
        print("[*] closing LeiGod processes...")
        kill_leigod()

    if args.restore:
        if not backup.exists():
            print(f"backup not found: {backup}")
            return 1
        shutil.copy2(backup, asar)
        print(f"[+] restored: {asar}")
        return 0

    if not backup.exists():
        shutil.copy2(asar, backup)
        print(f"[+] backup: {backup}")
    else:
        print(f"[*] backup exists: {backup}")

    if work.exists():
        shutil.rmtree(work)
    run(["npx", "asar", "extract", str(asar), str(work)])

    main_js = work / "dist" / "main" / "main.js"
    if not main_js.exists():
        print(f"main.js not found in asar: {main_js}")
        return 1

    code = f'''try{{"use strict";
try {{
  const {{ app }} = require("electron");
  app.commandLine.appendSwitch("remote-debugging-port", process.env.LEIGOD_DEBUG_PORT || "{args.port}");
  app.commandLine.appendSwitch("remote-allow-origins", "*");
}} catch (_) {{}}
require("bytenode");
require("./main.jsc");
}}catch(e){{console.error('leigod-appmain.js error:',e);require('electron').dialog.showErrorBox('leigod-appmain.js',e+''+e.stack);process.exit(1)}}
'''
    main_js.write_text(code, encoding="utf-8")
    run(["npx", "asar", "pack", str(work), str(asar)])
    print(f"[+] patched: {asar}")
    print(f"[+] start LeiGod normally, then open http://127.0.0.1:{args.port}/json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
