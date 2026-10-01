"""Regression checks for membership, packaging, migrations and failure behavior."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import config_io
import config_model
import desktop
import downloads
import fetch_provider_seed
import fix_provider_bootstrap
import fix_ruleset_bootstrap
import fix_windows_profile
import manage
import provider_policy
import seed_rulesets
import validation


def public_config():
    return config_model.load_config(ROOT, "tun", [ROOT / "examples/providers.example.json",
                                                  ROOT / "examples/api.example.json"])


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.config = public_config()

    def lint(self):
        return validation.lint(self.config, ROOT, template=True)

    def test_dedicated_pool_only_in_manual_and_claude(self):
        for tag in ("AUTO", "HK", "PROXY", "RULESET-BOOTSTRAP"):
            with self.subTest(tag=tag):
                original = copy.deepcopy(self.config)
                group = next(g for g in self.config["outbounds"] if g["tag"] == tag)
                group.setdefault("providers", []).append("Claude-Dedicated")
                with self.assertRaises(config_io.ConfigError):
                    self.lint()
                self.config = original

    def test_manual_must_remain_a_selector(self):
        next(g for g in self.config["outbounds"] if g["tag"] == "MANUAL")["type"] = "urltest"
        with self.assertRaises(config_io.ConfigError):
            self.lint()

    def test_missing_resolver_caught_in_string_and_object(self):
        for resolver in ("missing", {"server": "missing", "strategy": "ipv4_only"}):
            with self.subTest(resolver=resolver):
                self.config["http_clients"][0]["domain_resolver"] = resolver
                with self.assertRaises(config_io.ConfigError):
                    self.lint()

    def test_provider_ua_client_conflict(self):
        self.config["providers"][0]["user_agent"] = "different-ua"
        with self.assertRaises(config_io.ConfigError):
            self.lint()

    def test_seed_path_conflict_and_cache_required(self):
        self.config["providers"][0]["initial_path"] = "seed"
        with self.assertRaises(config_io.ConfigError):
            self.lint()
        self.config["providers"][0].pop("path")
        self.config["experimental"]["cache_file"]["enabled"] = False
        with self.assertRaises(config_io.ConfigError):
            self.lint()

    def test_dns_empty_direct_rejected(self):
        self.config["dns"]["servers"][1]["detour"] = "DIRECT"
        with self.assertRaises(config_io.ConfigError):
            self.lint()

    def test_outbound_dialer_cycle_rejected(self):
        next(g for g in self.config["outbounds"] if g["tag"] == "DIRECT")["detour"] = "GAME"
        with self.assertRaises(config_io.ConfigError):
            self.lint()

    def test_empty_inline_rule_set_rejected(self):
        self.config["route"]["rule_set"].append({"type": "inline", "tag": "empty", "rules": []})
        with self.assertRaises(config_io.ConfigError):
            self.lint()

    def test_sync_removed_provider_repairs_bootstrap_and_manual(self):
        providers = {"Airport-C": {}, "Claude-Dedicated": {}}
        provider_policy.sync_memberships(self.config["outbounds"], providers)
        groups = config_model.tag_map(self.config["outbounds"], "group")
        self.assertEqual(groups["MANUAL"]["providers"], ["Airport-C", "Claude-Dedicated"])
        self.assertEqual(groups["RULESET-BOOTSTRAP"]["providers"], ["Airport-C"])
        for tag in provider_policy.ORDINARY_GROUPS:
            self.assertEqual(groups[tag]["providers"], ["Airport-C"])


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(
            ".git", "private", "dist", "state", "bin", "__pycache__", "*.pyc"))
        self.old_root, self.old_files = manage.ROOT, manage.PRIVATE_FILES
        manage.ROOT = self.root
        manage.PRIVATE_FILES = [self.root / "private/providers.json", self.root / "private/api.json"]

    def tearDown(self):
        manage.ROOT, manage.PRIVATE_FILES = self.old_root, self.old_files
        self.temp.cleanup()

    def ready(self):
        manage.initialize()
        providers = manage.read_json(manage.PRIVATE_FILES[0])
        for provider in providers["providers"]:
            provider["url"] = "https://subscriptions.example.org/test-only-" + provider["tag"]
        manage.write_json(manage.PRIVATE_FILES[0], providers, private=True)

    def test_public_template_does_not_read_private_files(self):
        expected = manage.windows_profile_config(template=True)
        self.ready()
        self.assertEqual(expected, manage.windows_profile_config(template=True))
        manage.PRIVATE_FILES[0].write_text("broken private JSON", encoding="utf-8")
        self.assertEqual(expected, manage.windows_profile_config(template=True))

    def test_clean_clone_template_cli_needs_no_init(self):
        output = self.root / "preview.json"
        command = [sys.executable, str(self.root / "scripts/build.py"), "windows", "--template", "--output", str(output)]
        subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        self.assertFalse((self.root / "private").exists())
        validation.lint(config_io.read_json(output), self.root, template=True)

    def test_template_cli_handles_legacy_redirected_encoding(self):
        command = [sys.executable, str(self.root / "scripts/build.py"), "windows", "--template"]
        environment = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp1252")
        result = subprocess.run(command, env=environment, check=True, capture_output=True, encoding="utf-8")
        self.assertIn("已生成", result.stdout)

    def test_empty_local_rules_pack_to_inert_rule(self):
        config_io.write_json(self.root / "rules/local/direct.json", {"version": 3, "rules": []})
        result = manage.windows_profile_config(template=True)
        local = next(r for r in result["route"]["rule_set"] if r["tag"] == "local-direct")
        self.assertEqual(local["rules"], [{"domain": ["ref1nd-empty-rule-set.invalid"]}])

    def test_inline_provider_build_is_ready_and_nodes_not_shared_with_auto(self):
        self.ready()
        providers = config_io.read_json(manage.PRIVATE_FILES[0])
        claude = providers["providers"][-1]
        claude.clear()
        claude.update({"type": "inline", "tag": "Claude-Dedicated", "outbounds": [
            {"type": "trojan", "tag": "dedicated", "server": "example.org", "server_port": 443,
             "password": "test-only-password", "tls": {"enabled": True}}]})
        config_io.write_json(manage.PRIVATE_FILES[0], providers, private=True)
        result = manage.windows_profile_config()
        validation.lint(result, self.root)
        manual = next(g for g in result["outbounds"] if g["tag"] == "MANUAL")
        self.assertIn("Claude-Dedicated", manual["providers"])

    def test_local_overrides_not_silently_dropped(self):
        provider = {"type": "local", "tag": "test", "path": "./nodes.json", "override_tls": {"server_name": "example.org"}}
        config_io.write_json(self.root / "nodes.json", {"outbounds": [{"type": "trojan", "tag": "node"}]})
        with self.assertRaises(config_io.ConfigError):
            desktop._inline_local_provider(provider, self.root)

    def test_build_checks_transformed_result(self):
        self.ready()
        with patch.object(desktop, "_inline_local_provider", return_value={"type": "inline", "tag": "Claude-Dedicated", "outbounds": []}):
            c = manage.load_config("tun")
            config_io.write_json(self.root / "nodes.json", {"outbounds": [{"type": "trojan", "tag": "node"}]})
            c["providers"][-1] = {"type": "local", "tag": "Claude-Dedicated", "path": "./nodes.json"}
            with self.assertRaises(config_io.ConfigError):
                desktop.pack_windows_profile(c, self.root)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "profile.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_backups_preserved_and_noop_does_not_rewrite(self):
        config_io.write_json(self.path, {"version": 1})
        first = config_io.save_profile(self.path, {"version": 2})
        second = config_io.save_profile(self.path, {"version": 3})
        self.assertEqual(config_io.read_json(first), {"version": 1})
        self.assertEqual(config_io.read_json(second), {"version": 2})
        self.assertIsNone(config_io.save_profile(self.path, {"version": 3}))
        self.assertEqual(len(list(self.path.parent.glob("*.bak*"))), 2)

    def test_failed_atomic_write_keeps_original(self):
        config_io.write_json(self.path, {"version": 1})
        with patch.object(config_io.os, "replace", side_effect=OSError("test failure")):
            with self.assertRaises(OSError):
                config_io.save_profile(self.path, {"version": 2})
        self.assertEqual(config_io.read_json(self.path), {"version": 1})
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_duplicate_keys_rejected_without_echoing_contents(self):
        self.path.write_text('{"url":"test-only-value", "url":"another"}', encoding="utf-8")
        with self.assertRaises(config_io.ConfigError) as raised:
            config_io.read_json(self.path)
        self.assertNotIn("test-only-value", str(raised.exception))

    def test_conflicting_shared_user_agents_migrate_and_repeat_safely(self):
        config_io.write_json(self.path, {"providers": [
            {"type": "remote", "tag": "A", "http_client": "shared", "user_agent": "first"},
            {"type": "remote", "tag": "B", "http_client": "shared", "user_agent": "second"}],
            "http_clients": [{"tag": "shared", "headers": {"user-agent": "first"}, "detour": "DIRECT"}]})
        fix_windows_profile.patch(self.path)
        result = config_io.read_json(self.path)
        self.assertEqual([provider_policy.effective_ua(p, result["http_clients"]) for p in result["providers"]], ["first", "second"])
        fix_windows_profile.patch(self.path)
        self.assertEqual(result, config_io.read_json(self.path))
        self.assertEqual(len(list(self.path.parent.glob("*.bak*"))), 1)

    def test_missing_refresh_detour_does_not_modify_profile(self):
        config_io.write_json(self.path, {"providers": [{"type": "remote", "tag": "A"}], "outbounds": []})
        original = self.path.read_bytes()
        with self.assertRaises(config_io.ConfigError):
            fix_provider_bootstrap.patch(self.path, "A", "irrelevant", "missing")
        self.assertEqual(self.path.read_bytes(), original)

    def test_bootstrap_cannot_take_dedicated_provider(self):
        config_io.write_json(self.path, {"providers": [{"type": "local", "tag": "Claude-Dedicated"}]})
        with self.assertRaises(config_io.ConfigError):
            fix_ruleset_bootstrap.patch(self.path, "Claude-Dedicated")

    def test_client_tags_do_not_collide_after_sanitizing(self):
        self.assertNotEqual(provider_policy.safe_tag("A B"), provider_policy.safe_tag("A-B"))
        self.assertNotEqual(provider_policy.safe_tag("机场甲"), provider_policy.safe_tag("机场乙"))

    def test_ruleset_seed_path_traversal_rejected(self):
        for tag in ("../escape", "sub/path", "..\\escape"):
            with self.subTest(tag=tag), self.assertRaises(config_io.ConfigError):
                list(seed_rulesets.expand_remote([{"type": "remote", "tag": tag, "url": "https://example.org/rules"}]))

    def test_subscription_failure_does_not_leak_url_or_replace_seed(self):
        config_io.write_json(self.path, {"providers": [{"type": "remote", "tag": "A", "url": "https://example.org/test-only-subscription"}]})
        seed = self.path.parent / "A.seed"
        seed.write_bytes(b"previous seed")
        error = urllib.error.URLError("https://example.org/test-only-subscription")
        with patch("downloads.urllib.request.OpenerDirector.open", side_effect=error):
            with self.assertRaises(config_io.ConfigError) as raised:
                fetch_provider_seed.fetch(self.path, "A", seed)
        self.assertNotIn("test-only-subscription", str(raised.exception))
        self.assertEqual(seed.read_bytes(), b"previous seed")

    def test_inline_headers_used_when_fetching_seed(self):
        config_io.write_json(self.path, {"providers": [{"type": "remote", "tag": "A", "url": "https://example.org/sub", "http_client": {
            "headers": {"user-agent": ["custom-ua"], "X-Test": "test-header"}}}]})
        with patch.object(fetch_provider_seed, "fetch_bytes", return_value=b"seed") as fetched:
            seed = fetch_provider_seed.fetch(self.path, "A", self.path.parent / "A.seed")
        self.assertEqual(fetched.call_args.kwargs["headers"], {"User-Agent": "custom-ua", "X-Test": "test-header"})
        self.assertEqual(seed.read_bytes(), b"seed")
        if os.name == "posix":
            self.assertEqual(seed.stat().st_mode & 0o777, 0o600)


class SelectionTests(unittest.TestCase):
    def test_manual_can_select_dedicated_node(self):
        node = "Claude-Dedicated/node"
        with patch.object(manage, "api_request", side_effect=[{"all": [node]}, None]) as api:
            manage.select_group(public_config(), "MANUAL", node)
        self.assertEqual(api.call_args.args[1:], ("/proxies/MANUAL", {"name": node}))

    def test_claude_rejects_ordinary_node_even_if_api_reports_it(self):
        with patch.object(manage, "api_request", return_value={"all": ["Airport-A/node"]}) as api:
            with self.assertRaises(config_io.ConfigError):
                manage.select_group(public_config(), "CLAUDE", "Airport-A/node")
        self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
