import unittest
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


if __name__ == "__main__":
    unittest.main()
