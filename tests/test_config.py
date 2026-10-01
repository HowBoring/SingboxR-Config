"""Synthetic configuration tests, NOT a replacement for sing-box check/live traffic tests."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manage", ROOT / "scripts/manage.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

_MODULE_TEMP = None
_ORIGINAL_MANAGE_ROOT = None
_ORIGINAL_PRIVATE_FILES = None

def setUpModule():
    """Run structural/policy tests against a clean-clone-style temporary checkout."""
    global _MODULE_TEMP, _ORIGINAL_MANAGE_ROOT, _ORIGINAL_PRIVATE_FILES
    _MODULE_TEMP = tempfile.TemporaryDirectory()
    _ORIGINAL_MANAGE_ROOT = m.ROOT
    _ORIGINAL_PRIVATE_FILES = m.PRIVATE_FILES
    m.ROOT = Path(_MODULE_TEMP.name) / "config"
    shutil.copytree(ROOT, m.ROOT, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    m.PRIVATE_FILES = [m.ROOT / "private/providers.json", m.ROOT / "private/api.json"]
    m.initialize()

def tearDownModule():
    global _MODULE_TEMP
    m.ROOT = _ORIGINAL_MANAGE_ROOT
    m.PRIVATE_FILES = _ORIGINAL_PRIVATE_FILES
    if _MODULE_TEMP is not None:
        _MODULE_TEMP.cleanup()
        _MODULE_TEMP = None

def match(rule, facts):
    if rule.get("type") == "logical":
        result = (all if rule["mode"] == "and" else any)(match(r, facts) for r in rule["rules"])
    else:
        checks = []
        for key in ["inbound", "protocol", "port", "query_type"]:
            if key in rule:
                checks.append(facts.get(key) in m.as_list(rule[key]))
        if "ip_is_private" in rule:
            checks.append(facts.get("ip_is_private", False) == rule["ip_is_private"])
        if "rule_set" in rule:
            checks.append(bool(set(m.as_list(rule["rule_set"])) & set(facts.get("members", []))))
        result = all(checks)
    return not result if rule.get("invert") else result

def route(config, members=(), **extra):
    facts = {"members": members, "inbound": "mixed-in", "port": 443, "protocol": "tls", **extra}
    for r in config["route"]["rules"]:
        if r.get("action") in ["sniff", "resolve"]:
            continue
        if match(r, facts):
            return r.get("outbound", r["action"])
    return config["route"]["final"]

def dns_route(config, members=(), **extra):
    facts = {"members": members, "inbound": "mixed-in", "query_type": "A", **extra}
    for r in config["dns"]["rules"]:
        if match(r, facts):
            return r.get("server", r["action"])
    return config["dns"]["final"]

class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = m.load_config()
    def test_strict_json(self):
        for path in ROOT.rglob("*.json"):
            if "__pycache__" not in str(path):
                m.read_json(path)
    def test_mixed_lint(self):
        self.assertEqual(m.lint(self.c, template=True), {"outbounds":15,"providers":3,"rulesets":35})
    def test_tun_lint(self):
        m.lint(m.load_config("tun"), template=True)
    def test_native_profiles_exclusive(self):
        self.assertNotIn("tun-in", [x["tag"] for x in self.c["inbounds"]])
        self.assertIn("tun-in", [x["tag"] for x in m.load_config("tun")["inbounds"]])
    def test_placeholders_block_ready(self):
        with self.assertRaises(m.ConfigError):
            m.lint(self.c)
    def test_normal_isolation(self):
        for g in self.c["outbounds"]:
            if g["tag"] != "CLAUDE":
                self.assertNotIn("Claude-Dedicated", g.get("providers", []))
    def test_failsafe_outbound(self):
        for g in self.c["outbounds"]:
            if g["type"] == "urltest" or g["tag"] == "CLAUDE":
                self.assertEqual(g["outbounds"], ["REJECT"])
    def test_seeds_not_mixed_with_path(self):
        for rs in m.expand_rulesets(self.c):
            if rs["type"] == "remote":
                self.assertIn("initial_path",rs)
                self.assertNotIn("path",rs)
                self.assertNotIn("{tag}",rs["url"])
    def test_egress_cycle_rejected(self):
        c=copy.deepcopy(self.c)
        next(x for x in c["outbounds"] if x["tag"]=="MANUAL")["outbounds"].append("PROXY")
        with self.assertRaises(m.ConfigError):m.lint(c,template=True)
    def test_provider_reference_rejected(self):
        c=copy.deepcopy(self.c);c["providers"].pop(0)
        with self.assertRaises(m.ConfigError):m.lint(c,template=True)
    def test_loopback_binding(self):
        self.assertTrue(all(i["listen"] == "127.0.0.1" for i in self.c["inbounds"]))
        self.assertEqual(self.c["experimental"]["clash_api"]["external_controller"],"127.0.0.1:9090")
    def test_region_filters(self):
        pats={x["tag"]:x["include"] for x in self.c["outbounds"] if "include"in x}
        for region,sample in [("US","Airport-A/US01"),("US","Airport-A/美国 01"),("HK","Airport-A/Hong Kong 02"),("JP","Airport-B/JP 01"),("SG","Airport-B/Singapore"),("TW","Airport-B/台湾01")]:
            self.assertRegex(sample,pats[region])
        self.assertNotRegex("Airport-A/Australia 01",pats["US"])
    def test_claude_snapshot(self):
        c=m.read_json(ROOT/"rules/local/ai-claude.json")["rules"][0]
        self.assertEqual(len(c["domain_suffix"]),7)
        self.assertIn("claudemcpcontent.com",c["domain_suffix"])
        self.assertEqual(c["domain"],["servd-anthropic-website.b-cdn.net"])

    def test_runtime_bootstrap_defaults(self):
        c=m.windows_profile_config(template=True)
        clients=m.tag_map(c["http_clients"], "client")
        self.assertEqual(clients["provider-download"]["domain_resolver"], "dns-bootstrap")
        self.assertEqual(clients["provider-download"]["headers"]["User-Agent"], "clash.meta")
        self.assertNotIn("detour", clients["provider-download"])
        self.assertEqual(clients["ruleset-download"]["detour"], "RULESET-BOOTSTRAP")
        self.assertEqual(next(x for x in c["dns"]["servers"] if x["tag"]=="dns-bootstrap"), {"type":"local","tag":"dns-bootstrap"})
        self.assertFalse(any(x.get("detour")=="DIRECT" for x in c["dns"]["servers"]))
        self.assertFalse(any("user_agent" in x and "http_client" in x for x in c["providers"]))
        self.assertEqual(next(x for x in c["inbounds"] if x["type"]=="tun")["stack"], "system")

    def test_windows_keep_rule_seed_paths(self):
        c=m.windows_profile_config(template=True, keep_seed_paths=True)
        self.assertTrue(all("initial_path" in x for x in c["route"]["rule_set"] if x["type"]=="remote"))

    def test_windows_profile_is_single_file_ready(self):
        w=m.windows_profile_config(template=True)
        self.assertIn("tun-in", [x["tag"] for x in w["inbounds"]])
        self.assertIn("mixed-in", [x["tag"] for x in w["inbounds"]])
        self.assertTrue(all(x["type"] != "local" for x in w["route"]["rule_set"]))
        self.assertTrue(any(x["type"] == "inline" and x["tag"] == "local-ai-claude" for x in w["route"]["rule_set"]))
        self.assertTrue(all(x.get("rules") for x in w["route"]["rule_set"] if x["type"] == "inline"))
        for x in w["route"]["rule_set"]:
            self.assertNotIn("initial_path", x)
            if x["type"] == "inline":
                self.assertNotIn("path", x)
        for provider in w["providers"]:
            if provider["type"] == "remote":
                self.assertNotIn("path", provider)
                self.assertNotIn("initial_path", provider)
        self.assertNotIn("path", w["experimental"]["cache_file"])
        clash=w["experimental"]["clash_api"]
        self.assertNotIn("external_ui", clash)
        self.assertNotIn("external_ui_download_url", clash)
        self.assertEqual(clash["secret"], "REPLACE_WITH_RANDOM_SECRET_RUN_INIT")
        self.assertEqual(w["route"]["final"], "PROXY")
        m.lint(w, template=True)

    def test_windows_profile_has_no_project_local_paths(self):
        w=m.windows_profile_config(template=True)
        text=json.dumps(w, ensure_ascii=False)
        for prefix in ["./state/", "./rules/", "./private/"]:
            self.assertNotIn(prefix, text)

class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=m.load_config()
    def test_claude_before_ai(self):
        self.assertEqual(route(self.c,["local-ai-claude","ai","proxy","ads"]),"CLAUDE")
    def test_ai_before_domestic_vendor(self):
        self.assertEqual(route(self.c,["ai","google-cn","microsoft-cn","cn"]),"AI")
    def test_ai_before_process(self):
        self.assertEqual(route(self.c,["ai","applications","cn"]),"AI")
    def test_process_not_blanket_direct(self):
        self.assertEqual(route(self.c,["applications","proxy"]),"PROXY")
        self.assertEqual(route(self.c,["applications"]),"PROXY")
    def test_game_cn_before_games(self):
        self.assertEqual(route(self.c,["games-cn","games"]),"DIRECT")
    def test_media_aggregation(self):
        for tag in ["netflix","disney","youtube","spotify","mediaip"]:
            self.assertEqual(route(self.c,[tag,"proxy"]),"MEDIA")
    def test_ads(self):self.assertEqual(route(self.c,["ads"]),"reject")
    def test_explicit_override(self):
        self.assertEqual(route(self.c,["local-direct","ads"]),"DIRECT")
        self.assertEqual(route(self.c,["local-proxy","cn"]),"PROXY")
    def test_utilities(self):
        for tag in ["telegramip","networktest"]:self.assertEqual(route(self.c,[tag]),"PROXY")
    def test_unknown_and_domestic(self):
        self.assertEqual(route(self.c,[]),"PROXY")
        self.assertEqual(route(self.c,["cnip"]),"DIRECT")
        self.assertEqual(route(self.c,["cn"]),"DIRECT")
    def test_explicit_dns_listener(self):
        self.assertEqual(route(self.c,[],inbound="dns-in",protocol="unknown",port=1053),"hijack-dns")
    def test_tun_dns_capture(self):
        self.assertEqual(route(self.c,[],inbound="tun-in",protocol="unknown",port=53),"hijack-dns")
    def test_mixed_never_fakeip(self):
        self.assertEqual(dns_route(self.c,["ai"]),"dns-ai")
        self.assertEqual(dns_route(self.c,["local-ai-claude","ai"]),"dns-claude")
        self.assertEqual(dns_route(self.c,["proxy"]),"dns-proxy")
    def test_tun_known_fakeip(self):
        self.assertEqual(dns_route(self.c,["local-ai-claude","ai"],inbound="tun-in"),"dns-fake")
        self.assertEqual(dns_route(self.c,["proxy"],inbound="tun-in",query_type="AAAA"),"dns-fake")
    def test_fakeip_exception_not_direct(self):
        for tag in ["fakeip-filter","trackerslist","local-realip"]:
            self.assertEqual(dns_route(self.c,["proxy",tag],inbound="tun-in"),"dns-proxy")
            self.assertEqual(dns_route(self.c,["local-ai-claude",tag],inbound="tun-in"),"dns-claude")
    def test_unknown_tun_realip(self):
        self.assertEqual(dns_route(self.c,[],inbound="tun-in"),"dns-proxy")
    def test_dns_ai_before_cn(self):
        self.assertEqual(dns_route(self.c,["ai","google-cn"]),"dns-ai")
    def test_non_address_dns_not_fake(self):
        self.assertEqual(dns_route(self.c,["ai"],inbound="tun-in",query_type="TXT"),"dns-ai")

class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.previous=m.ROOT
        m.ROOT=Path(self.temp.name)/"config"
        shutil.copytree(ROOT,m.ROOT,ignore=shutil.ignore_patterns("__pycache__"))
        self.previous_files=m.PRIVATE_FILES
        m.PRIVATE_FILES=[m.ROOT/"private/providers.json",m.ROOT/"private/api.json"]
        m.initialize()
    def tearDown(self):
        m.ROOT=self.previous;m.PRIVATE_FILES=self.previous_files;self.temp.cleanup()
    def test_init_idempotent(self):
        before=m.PRIVATE_FILES[0].read_bytes();m.initialize()
        secret=m.read_json(m.PRIVATE_FILES[1])["experimental"]["clash_api"]["secret"]
        self.assertGreaterEqual(len(secret),32)
        m.initialize()
        self.assertEqual(secret,m.read_json(m.PRIVATE_FILES[1])["experimental"]["clash_api"]["secret"])
        self.assertEqual(before,m.PRIVATE_FILES[0].read_bytes())
    def test_sync_added_provider(self):
        d=m.read_json(m.PRIVATE_FILES[0]);new=copy.deepcopy(d["providers"][0]);new["tag"]="Airport-C";d["providers"].append(new)
        m.write_json(m.PRIVATE_FILES[0],d)
        m.sync_providers()
        c=m.load_config()
        for g in c["outbounds"]:
            if g["tag"] in ["AUTO","MANUAL","HK","TW","JP","SG","US"]:
                self.assertIn("Airport-C",g["providers"])
        m.lint(c,template=True)
    def test_ready_without_network(self):
        m.initialize();d=m.read_json(m.PRIVATE_FILES[0])
        for p in d["providers"]:p["url"]="https://subscriptions.example.org/"+p["tag"]
        m.write_json(m.PRIVATE_FILES[0],d)
        m.lint(m.load_config())
        with self.assertRaises(m.ConfigError):m.lint(m.load_config(),require_seeds=True)
    def test_native_command_paths(self):
        c=m.core_command("sing-box","check","tun")
        self.assertEqual(c[:2],["sing-box","check"])
        self.assertEqual(c.count("-c"),len(m.config_files("tun")))
        self.assertIn(str(m.ROOT/"profiles/tun/20-inbounds.json"),c)
        self.assertNotIn(str(m.ROOT/"profiles/mixed/20-inbounds.json"),c)

    def test_windows_build_template(self):
        output=m.write_windows_profile(template=True)
        self.assertTrue(output.is_file())
        built=m.read_json(output)
        self.assertIn("$schema",built)
        self.assertIn("tun-in",[x["tag"] for x in built["inbounds"]])

    def test_windows_local_native_provider_inline(self):
        d=m.read_json(m.PRIVATE_FILES[0])
        claude=next(x for x in d["providers"] if x["tag"]=="Claude-Dedicated")
        claude.clear();claude.update({"type":"local","tag":"Claude-Dedicated","path":"./private/claude-native.json","health_check":{"enabled":False}})
        m.write_json(m.PRIVATE_FILES[0],d)
        m.write_json(m.ROOT/"private/claude-native.json",{"outbounds":[{"type":"trojan","tag":"Claude-Primary","server":"example.com","server_port":443,"password":"secret","tls":{"enabled":True}}]})
        w=m.windows_profile_config(template=True)
        cp=next(x for x in w["providers"] if x["tag"]=="Claude-Dedicated")
        self.assertEqual(cp["type"],"inline")
        self.assertEqual(cp["outbounds"][0]["tag"],"Claude-Primary")

if __name__=="__main__":unittest.main(verbosity=2)
