import time
import unittest
from unittest import mock

from scripts import build_shadowrocket
from scripts.build_shadowrocket import check_source_drift, normalize_rule


class ShadowrocketRuleTests(unittest.TestCase):
    def test_mihomo_suffix_prefix_is_removed(self):
        self.assertEqual(normalize_rule("+.example.com", "DOMAIN-SUFFIX"), "DOMAIN-SUFFIX,example.com")

    def test_geoip_cidr_type_is_inferred(self):
        self.assertEqual(normalize_rule("2001:db8::1/32", "IP-CIDR"), "IP-CIDR6,2001:db8::/32")

    def test_rule_type_is_inferred_from_cidr(self):
        self.assertEqual(normalize_rule("IP-CIDR,2001:db8::1/32,no-resolve", "DOMAIN-SUFFIX"), "IP-CIDR6,2001:db8::/32,no-resolve")

    def test_specific_domain_rule_keeps_type(self):
        self.assertEqual(normalize_rule("DOMAIN,example.com", "DOMAIN-SUFFIX"), "DOMAIN,example.com")

    def test_source_size_drift_fails_closed(self):
        previous = {"sources": [{"category": "Test", "url": "https://example.test/rules", "source_rules": 100}]}
        current = [{"category": "Test", "url": "https://example.test/rules", "source_rules": 20}]
        with self.assertRaises(ValueError):
            check_source_drift(previous, current, "shadowrocket")

    def test_small_source_size_drift_is_allowed(self):
        previous = {"sources": [{"category": "Test", "url": "https://example.test/rules", "source_rules": 100}]}
        current = [{"category": "Test", "url": "https://example.test/rules", "source_rules": 110}]
        check_source_drift(previous, current, "shadowrocket")

    def test_invalid_ip_fails(self):
        with self.assertRaises(ValueError):
            normalize_rule("invalid-cidr", "IP-CIDR")


class FetchManyTests(unittest.TestCase):
    def test_preserves_configured_order(self):
        urls = ["https://a/x.yaml", "https://b/x.yaml", "https://c/x.yaml"]
        with mock.patch.object(
                build_shadowrocket, "fetch",
                side_effect=lambda url, retries=3: f"body:{url}".encode()):
            self.assertEqual(
                build_shadowrocket.fetch_many(urls),
                [f"body:{u}".encode() for u in urls],
            )

    def test_downloads_concurrently(self):
        def slow(url, retries=3):
            time.sleep(0.2)
            return url.encode()

        with mock.patch.object(build_shadowrocket, "fetch", side_effect=slow):
            started = time.monotonic()
            build_shadowrocket.fetch_many([f"https://example.test/{i}" for i in range(4)])
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.7, "fetch_many should overlap downloads")


if __name__ == "__main__":
    unittest.main()
