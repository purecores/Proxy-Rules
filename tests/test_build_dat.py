import importlib.util
import ipaddress
import time
import unittest
from unittest import mock
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_dat.py"
SPEC = importlib.util.spec_from_file_location("build_dat", MODULE_PATH)
build_dat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_dat)


class RuleParserTests(unittest.TestCase):
    def test_domain_types_are_preserved_during_deduplication(self):
        self.assertEqual(build_dat.parse_domain_rule("DOMAIN,Example.com"), (build_dat.FULL, "example.com"))
        self.assertEqual(build_dat.parse_domain_rule("DOMAIN-SUFFIX,example.com"), (build_dat.DOMAIN, "example.com"))
        self.assertNotEqual(
            build_dat.parse_domain_rule("DOMAIN,Example.com"),
            build_dat.parse_domain_rule("DOMAIN-SUFFIX,example.com"),
        )

    def test_mihomo_suffix_syntax(self):
        self.assertEqual(build_dat.parse_domain_rule("+.Example.COM"), (build_dat.DOMAIN, "example.com"))

    def test_ip_cidr_normalization(self):
        self.assertEqual(
            build_dat.parse_ip_rule("IP-CIDR,192.0.2.3/24,no-resolve"),
            (ipaddress.ip_address("192.0.2.0").packed, 24),
        )

    def test_invalid_payload_fails(self):
        with self.assertRaises(ValueError):
            build_dat.load_payload("payload: not-a-list")

    def test_domain_dedup_key_keeps_type(self):
        values = [
            build_dat.parse_domain_rule("DOMAIN,example.com"),
            build_dat.parse_domain_rule("DOMAIN-SUFFIX,example.com"),
        ]
        self.assertEqual(len(set(values)), 2)

    def test_malformed_rule_item_fails(self):
        with self.assertRaises(ValueError):
            build_dat.load_payload("payload:\n  - example.com\n  - 7\n")

    def test_protobuf_builders_emit_data(self):
        site = build_dat.encode_geosite_list([("TEST", [(build_dat.DOMAIN, "example.com")])])
        geoip = build_dat.encode_geoip_list([("TEST", [(ipaddress.ip_address("192.0.2.0").packed, 24)])])
        self.assertTrue(site.startswith(b"\x0a"))
        self.assertTrue(geoip.startswith(b"\x0a"))


class FetchManyTests(unittest.TestCase):
    def test_preserves_configured_order(self):
        urls = ["https://a/x.yaml", "https://b/x.yaml", "https://c/x.yaml"]
        with mock.patch.object(
                build_dat, "fetch",
                side_effect=lambda url, retries=3: f"body:{url}"):
            self.assertEqual(build_dat.fetch_many(urls), [f"body:{u}" for u in urls])

    def test_downloads_concurrently(self):
        def slow(url, retries=3):
            time.sleep(0.2)
            return url

        with mock.patch.object(build_dat, "fetch", side_effect=slow):
            started = time.monotonic()
            build_dat.fetch_many([f"https://example.test/{i}" for i in range(4)])
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.7, "fetch_many should overlap downloads")

    def test_single_url_skips_the_pool(self):
        with mock.patch.object(build_dat, "fetch", return_value="body") as patched:
            self.assertEqual(build_dat.fetch_many(["https://example.test/a"]), ["body"])
        patched.assert_called_once()


if __name__ == "__main__":
    unittest.main()
