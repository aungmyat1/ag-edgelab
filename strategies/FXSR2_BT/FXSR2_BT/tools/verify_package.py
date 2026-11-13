#!/usr/bin/env python3
"""Verify frozen V2 artifacts against pinned hashes. Usage: python verify_package.py <FX_SweepRetest_V2_Research dir>"""
import hashlib, sys, pathlib
PINNED = {
 "Experts/FX_SweepRetest_Research.mq5": "be1695b387a7da825d1077f2a6adb63d7c9df5b1c8616f56e6e55207bf3639b1",
 "Presets/FX_SweepRetest_Research.set": "45ca412ee2275fb726bdff891a03883d4f3ac4f442e92fe259dc0ea559760d07",
 "Tester/FX_SweepRetest_Research.ini": "470cf8c32f245061f32f689a40229b44224504588c75baa7d9821eb2971c30bd",
}
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
ok = True
for rel, want in PINNED.items():
    p = root / rel
    got = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"
    ok &= got == want
    print(("OK  " if got == want else "BAD ") + rel, got)
sys.exit(0 if ok else 1)
