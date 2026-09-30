from __future__ import annotations

import unittest

from learning_mcp.official_sources import validate_official_sources


class OfficialSourcesTests(unittest.TestCase):
    def test_validates_and_deduplicates_public_official_urls(self) -> None:
        source = {
            "topic_key": "dev.swift-concurrency",
            "title": "Concurrency",
            "url": "https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/",
            "publisher": "Swift.org",
            "source_type": "official-documentation",
            "reason": "Swift 동시성의 공식 언어 참조다.",
        }
        result = validate_official_sources({"sources": [source, source]}, {"dev.swift-concurrency"})
        self.assertEqual(result, [source])

    def test_rejects_unknown_topics_and_private_urls(self) -> None:
        source = {
            "topic_key": "unknown",
            "title": "Internal",
            "url": "http://127.0.0.1/docs",
            "publisher": "Internal",
            "source_type": "official-documentation",
            "reason": "Not public",
        }
        with self.assertRaisesRegex(ValueError, "unknown official source topic"):
            validate_official_sources({"sources": [source]}, {"allowed"})
        source["topic_key"] = "allowed"
        with self.assertRaisesRegex(ValueError, "private address"):
            validate_official_sources({"sources": [source]}, {"allowed"})


if __name__ == "__main__":
    unittest.main()
