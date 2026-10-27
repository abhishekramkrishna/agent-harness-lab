import unittest

from version import is_newer, parse


class TestVersion(unittest.TestCase):
    def test_double_digit_minor_is_newer(self):
        self.assertTrue(is_newer("1.10.0", "1.9.0"))

    def test_double_digit_patch_is_not_older(self):
        self.assertFalse(is_newer("1.2.3", "1.2.10"))

    def test_equal_versions(self):
        self.assertFalse(is_newer("2.0.0", "2.0.0"))

    def test_leading_v(self):
        self.assertEqual(parse("v3.1.4"), (3, 1, 4))


if __name__ == "__main__":
    unittest.main()
