import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
script = root / "scripts" / "fix_tun_stack.py"

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "profile.json"
    p.write_text(json.dumps({"inbounds": [
        {"type": "tun", "tag": "tun-in", "stack": "mixed", "auto_route": True},
        {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7890}
    ]}), encoding="utf-8")
    subprocess.check_call([sys.executable, str(script), str(p)])
    d = json.loads(p.read_text(encoding="utf-8"))
    tun = next(x for x in d["inbounds"] if x["type"] == "tun")
    assert tun["stack"] == "system"
    assert p.with_suffix(".json.bak-tun-stack").exists()
print("OK")
