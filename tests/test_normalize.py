"""Tests for stage 2 (normalize): dedupe, claim merging, determinism.

Pure logic — no network, no stage-1 output files needed.
"""

from __future__ import annotations

import json
import unittest

from yuel.normalize import normalize_proxies


def make_proxy(**overrides) -> dict:
    fields = {
        "host": "1.2.3.4",
        "port": 8080,
        "username": "",
        "password": "",
        "claimed_type": None,
        "claimed_country": None,
        "claimed_anonymity": None,
        "source": "src-a",
        "identity": "1.2.3.4|8080||",
    }
    fields.update(overrides)
    if "identity" not in overrides:
        fields["identity"] = (
            f"{fields['host']}|{fields['port']}|"
            f"{fields['username']}|{fields['password']}"
        )
    return fields


class DedupeTests(unittest.TestCase):
    def test_same_target_merges_sources(self):
        proxies = [
            make_proxy(source="src-a", claimed_type="socks5"),
            make_proxy(source="src-b"),
            make_proxy(source="src-c", claimed_type="socks5"),
        ]
        normalized, report = normalize_proxies(proxies)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["sources"], ["src-a", "src-b", "src-c"])
        self.assertEqual(report["output"]["duplicates_collapsed"], 2)
        self.assertEqual(report["input"]["proxies_in"], 3)

    def test_different_creds_are_separate_targets(self):
        proxies = [
            make_proxy(source="src-a"),
            make_proxy(source="src-b", username="alice"),
        ]
        normalized, _ = normalize_proxies(proxies)
        self.assertEqual(len(normalized), 2)
        identities = {entry["identity"] for entry in normalized}
        self.assertEqual(identities, {"1.2.3.4|8080||", "1.2.3.4|8080|alice|"})

    def test_output_sorted_by_identity(self):
        proxies = [make_proxy(host="9.9.9.9"), make_proxy(host="1.1.1.1")]
        normalized, _ = normalize_proxies(proxies)
        self.assertEqual(
            [entry["host"] for entry in normalized], ["1.1.1.1", "9.9.9.9"]
        )


class ClaimMergeTests(unittest.TestCase):
    def test_agreed_claim_kept(self):
        proxies = [
            make_proxy(source="a", claimed_type="socks5", claimed_country="DE"),
            make_proxy(source="b", claimed_type="socks5"),
        ]
        normalized, _ = normalize_proxies(proxies)
        self.assertEqual(normalized[0]["claimed_type"], "socks5")
        self.assertEqual(normalized[0]["claimed_country"], "DE")
        self.assertEqual(normalized[0]["claim_conflicts"], [])

    def test_conflicting_type_claim_nulled_and_flagged(self):
        proxies = [
            make_proxy(source="a", claimed_type="socks5"),
            make_proxy(source="b", claimed_type="http"),
        ]
        normalized, report = normalize_proxies(proxies)
        self.assertIsNone(normalized[0]["claimed_type"])
        self.assertEqual(normalized[0]["claim_conflicts"], ["type"])
        self.assertEqual(report["output"]["claim_conflicts"], 1)

    def test_real_claim_beats_null_claim(self):
        proxies = [
            make_proxy(source="a", claimed_type=None),
            make_proxy(source="b", claimed_type="http"),
        ]
        normalized, _ = normalize_proxies(proxies)
        self.assertEqual(normalized[0]["claimed_type"], "http")
        self.assertEqual(normalized[0]["claim_conflicts"], [])

    def test_anonymity_conflict_flagged(self):
        proxies = [
            make_proxy(source="a", claimed_anonymity="elite"),
            make_proxy(source="b", claimed_anonymity="transparent"),
        ]
        normalized, _ = normalize_proxies(proxies)
        self.assertIsNone(normalized[0]["claimed_anonymity"])
        self.assertIn("anonymity", normalized[0]["claim_conflicts"])


class RepresentativeTests(unittest.TestCase):
    def test_richest_member_is_representative(self):
        proxies = [
            make_proxy(source="poor"),
            make_proxy(source="rich", claimed_type="socks5",
                       claimed_country="US", claimed_anonymity="elite"),
        ]
        normalized, _ = normalize_proxies(proxies)
        self.assertEqual(normalized[0]["claimed_country"], "US")
        self.assertEqual(normalized[0]["sources"], ["poor", "rich"])


class InvalidRowTests(unittest.TestCase):
    def test_malformed_rows_dropped_and_sampled(self):
        proxies = [
            make_proxy(),
            "not-a-dict",
            {"port": 8080},  # missing host
            {"host": "1.2.3.999", "port": 80},  # bad IPv4
        ]
        normalized, report = normalize_proxies(proxies)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(report["input"]["invalid_dropped"], 3)
        self.assertTrue(report["invalid_samples"])

    def test_never_raises_on_garbage(self):
        normalized, report = normalize_proxies([None, 42, {}, make_proxy()])
        self.assertEqual(len(normalized), 1)
        self.assertEqual(report["input"]["invalid_dropped"], 3)


class ReportTests(unittest.TestCase):
    def test_counts(self):
        proxies = [
            make_proxy(source="a", claimed_type="socks5"),
            make_proxy(host="5.5.5.5", source="a", claimed_type="http",
                       username="u"),
            make_proxy(host="6.6.6.6", source="a"),  # unknown claim
        ]
        normalized, report = normalize_proxies(proxies)
        self.assertEqual(
            report["by_claimed_type"], {"http": 1, "socks5": 1, "unknown": 1}
        )
        self.assertEqual(report["output"]["with_credentials"], 1)
        self.assertEqual(report["output"]["proxies_out"], 3)

    def test_deterministic_output(self):
        proxies = [make_proxy(source=f"src-{i}") for i in range(5)]
        proxies.append(make_proxy(source="z-extra", claimed_country="US"))
        run1 = json.dumps(normalize_proxies(proxies)[0], sort_keys=True)
        run2 = json.dumps(normalize_proxies(list(reversed(proxies)))[0], sort_keys=True)
        self.assertEqual(run1, run2)


if __name__ == "__main__":
    unittest.main()
