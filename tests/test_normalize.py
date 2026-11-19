"""Tests for stage 2 (normalize): dedupe, merge policy, determinism.

Pure logic — no network, no stage-1 output files needed.
"""

from __future__ import annotations

import unittest

from yuel import normalize

UUID = "550e8400-e29b-41d4-a716-446655440000"


def make_endpoint(**overrides) -> dict:
    endpoint = {
        "scheme": "vless",
        "host": "v.example.com",
        "port": 443,
        "secret": UUID,
        "params": {"security": "tls", "sni": "v.example.com"},
        "name": "node",
        "extra": {},
        "identity": f"vless|v.example.com|443|{UUID}",
        "source": "src-a",
    }
    endpoint.update(overrides)
    return endpoint


class NormalizeTests(unittest.TestCase):
    def test_duplicates_merge_with_sources_list(self):
        a = make_endpoint(source="src-a")
        b = make_endpoint(
            params={"sni": "v.example.com", "security": "tls"},  # different order
            name="same node elsewhere",
            source="src-b",
        )
        normalized, report = normalize.normalize_endpoints([a, b])
        self.assertEqual(len(normalized), 1)
        entry = normalized[0]
        self.assertEqual(entry["identity"], f"vless|v.example.com|443|{UUID}")
        self.assertEqual(entry["sources"], ["src-a", "src-b"])
        self.assertEqual(report["input"]["endpoints_in"], 2)
        self.assertEqual(report["output"]["endpoints_out"], 1)
        self.assertEqual(report["output"]["duplicates_collapsed"], 1)
        self.assertEqual(report["top_duplicates"][0]["count"], 2)

    def test_param_order_and_tag_do_not_split_identity(self):
        a = make_endpoint(params={"security": "reality", "sni": "x.com", "pbk": "K1"})
        b = make_endpoint(params={"pbk": "K1", "security": "reality", "sni": "x.com"})
        c = make_endpoint(name="completely different tag")
        normalized, report = normalize.normalize_endpoints([a, b, c])
        self.assertEqual(len(normalized), 1)
        self.assertEqual(report["output"]["duplicates_collapsed"], 2)

    def test_different_secret_is_not_merged(self):
        other_uuid = UUID.replace("5", "6", 1)
        a = make_endpoint()
        b = make_endpoint(secret=other_uuid, identity=f"vless|v.example.com|443|{other_uuid}")
        normalized, _ = normalize.normalize_endpoints([a, b])
        self.assertEqual(len(normalized), 2)
        identities = [e["identity"] for e in normalized]
        self.assertEqual(identities, sorted(identities))

    def test_scheme_is_part_of_identity(self):
        a = make_endpoint(scheme="vless")
        b = make_endpoint(scheme="trojan", identity="trojan|v.example.com|443|" + UUID)
        normalized, _ = normalize.normalize_endpoints([a, b])
        self.assertEqual(len(normalized), 2)

    def test_representative_is_richest_entry(self):
        poor = make_endpoint(params={}, name="x", source="src-a")
        rich = make_endpoint(
            params={"security": "reality", "sni": "x.com", "pbk": "K1", "fp": "chrome"},
            name="richer",
            source="src-b",
        )
        normalized, _ = normalize.normalize_endpoints([poor, rich])
        self.assertEqual(normalized[0]["params"]["fp"], "chrome")
        self.assertEqual(normalized[0]["name"], "richer")

    def test_representative_choice_is_deterministic(self):
        a = make_endpoint(name="tag-a", source="src-a")
        b = make_endpoint(name="tag-b", source="src-b")
        run1, _ = normalize.normalize_endpoints([a, b])
        run2, _ = normalize.normalize_endpoints([b, a])
        self.assertEqual(run1, run2)

    def test_output_sorted_by_identity(self):
        ids = [
            "vless|zzz.example.com|443|" + UUID,
            "vless|aaa.example.com|443|" + UUID,
            "vmess|mmm.example.com|443|" + UUID,
        ]
        endpoints = [make_endpoint(identity=i, host=i.split("|")[1]) for i in ids]
        normalized, _ = normalize.normalize_endpoints(endpoints)
        self.assertEqual([e["identity"] for e in normalized], sorted(ids))

    def test_invalid_rows_dropped_with_samples(self):
        endpoints = [
            make_endpoint(),
            {"scheme": "vless", "host": "v.example.com"},  # missing port
            {"host": "v.example.com", "port": 443},  # missing scheme
            "not even a dict",
            make_endpoint(port=0),  # fails validation
        ]
        normalized, report = normalize.normalize_endpoints(endpoints)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(report["input"]["invalid_dropped"], 4)
        self.assertTrue(report["invalid_samples"])
        self.assertLessEqual(len(report["invalid_samples"]), 5)

    def test_source_field_removed_from_output(self):
        normalized, _ = normalize.normalize_endpoints([make_endpoint()])
        self.assertNotIn("source", normalized[0])
        self.assertEqual(normalized[0]["sources"], ["src-a"])

    def test_duplicate_source_ids_deduped(self):
        a = make_endpoint(source="src-a")
        b = make_endpoint(name="second copy", source="src-a")
        normalized, _ = normalize.normalize_endpoints([a, b])
        self.assertEqual(normalized[0]["sources"], ["src-a"])

    def test_missing_source_field_tolerated(self):
        endpoint = make_endpoint()
        del endpoint["source"]
        normalized, _ = normalize.normalize_endpoints([endpoint])
        self.assertEqual(normalized[0]["sources"], [])

    def test_by_scheme_counts(self):
        endpoints = [
            make_endpoint(),
            make_endpoint(scheme="ss", identity="ss|v.example.com|443|pw",
                          secret="pw", extra={"method": "aes-256-gcm"}),
            make_endpoint(scheme="ss", identity="ss|v.example.com|443|pw",
                          secret="pw", extra={"method": "aes-256-gcm"}),
        ]
        normalized, report = normalize.normalize_endpoints(endpoints)
        self.assertEqual(report["by_scheme"], {"ss": 1, "vless": 1})
        self.assertEqual(len(normalized), 2)

    def test_empty_input(self):
        normalized, report = normalize.normalize_endpoints([])
        self.assertEqual(normalized, [])
        self.assertEqual(report["output"]["endpoints_out"], 0)
        self.assertEqual(report["output"]["duplicates_collapsed"], 0)


if __name__ == "__main__":
    unittest.main()
