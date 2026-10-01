import json
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fix_ruleset_bootstrap as f

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    profile = td / "profile.json"
    profile.write_text(json.dumps({
        "providers": [{
            "type":"remote", "tag":"YunTu", "url":"https://provider.example/sub",
            "initial_path": str(td / "YunTu.seed"), "http_client":"provider-update-YunTu"
        }],
        "http_clients": [
            {"tag":"ruleset-download", "detour":"PROXY", "domain_resolver":"dns-bootstrap"},
            {"tag":"provider-update-YunTu", "detour":"PROXY"}
        ],
        "outbounds": [
            {"type":"selector","tag":"PROXY","outbounds":["AUTO"],"default":"AUTO"},
            {"type":"urltest","tag":"AUTO","outbounds":["REJECT"],"providers":["YunTu"]},
            {"type":"block","tag":"REJECT"}
        ],
        "route": {"rule_set": [
            {"type":"remote","tag":["private","cn"],"format":"binary",
             "url":"https://github.com/x/{tag}.srs","http_client":"ruleset-download"},
            {"type":"inline","tag":"local-test","rules":[{"domain":["x.invalid"]}]}
        ]}
    }, indent=2), encoding="utf-8")
    (td / "YunTu.seed").write_text("dummy", encoding="utf-8")
    f.patch(profile, "YunTu")
    d = json.loads(profile.read_text(encoding="utf-8"))
    b = next(x for x in d["outbounds"] if x.get("tag") == f.BOOTSTRAP_TAG)
    assert b == {
        "type":"selector", "tag":"RULESET-BOOTSTRAP",
        "providers":["YunTu"], "interrupt_exist_connections":False
    }
    rc = next(x for x in d["http_clients"] if x.get("tag") == "ruleset-download")
    assert rc["detour"] == "RULESET-BOOTSTRAP"
    assert "domain_resolver" not in rc
    assert all(rs.get("http_client") == "ruleset-download" for rs in d["route"]["rule_set"] if rs.get("type") == "remote")
    auto = next(x for x in d["outbounds"] if x.get("tag") == "AUTO")
    assert auto["outbounds"] == ["REJECT"]  # normal traffic remains fail-closed
    assert profile.with_suffix(".json.bak").exists()
print("OK")
