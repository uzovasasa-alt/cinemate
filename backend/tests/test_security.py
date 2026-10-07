import os
import unittest

os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-0123456789"

from app.security import (CODE_ALPHABET, check_internal_token, create_session_token, generate_link_code,
                          hash_link_code, normalize_link_code, read_session_token)


class LinkCodes(unittest.TestCase):
    def test_format(self):
        for _ in range(200):
            c = generate_link_code()
            self.assertTrue(c.startswith("LINK-"))
            self.assertEqual(len(c), 13)
            self.assertTrue(all(ch in CODE_ALPHABET for ch in c[5:]))
            self.assertEqual(normalize_link_code(c), c)

    def test_codes_are_unique(self):
        self.assertEqual(len({generate_link_code() for _ in range(2000)}), 2000)

    def test_normalize_user_input(self):
        self.assertEqual(normalize_link_code(" link-7f3a9c2k "), "LINK-7F3A9C2K")
        self.assertEqual(normalize_link_code("7F3A9C2K"), "LINK-7F3A9C2K")

    def test_normalize_rejects_garbage(self):
        for bad in ("", "LINK-", "LINK-123", "LINK-0O1I1L11", "hello", "LINK-7F3A9C2K9", None):
            self.assertIsNone(normalize_link_code(bad), bad)

    def test_hash_is_stable_and_not_plain(self):
        h = hash_link_code("LINK-7F3A9C2K")
        self.assertEqual(h, hash_link_code("LINK-7F3A9C2K"))
        self.assertEqual(len(h), 64)
        self.assertNotIn("7F3A9C2K", h)
        self.assertNotEqual(h, hash_link_code("LINK-7F3A9C2L"))


class Session(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(read_session_token(create_session_token(42)), 42)

    def test_tampered(self):
        t = create_session_token(1)
        self.assertIsNone(read_session_token(t[:-2] + "xx"))
        self.assertIsNone(read_session_token("garbage"))


class Internal(unittest.TestCase):
    def test_token(self):
        os.environ["INTERNAL_API_TOKEN"] = "dev-internal-token"
        from app.config import get_settings
        get_settings.cache_clear()
        self.assertTrue(check_internal_token("dev-internal-token"))
        self.assertFalse(check_internal_token("nope"))
        self.assertFalse(check_internal_token(None))


if __name__ == "__main__":
    unittest.main()
