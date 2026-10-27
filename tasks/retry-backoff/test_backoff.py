import unittest

from backoff import delay


class TestBackoff(unittest.TestCase):
    def test_first_retry_waits_base(self):
        self.assertEqual(delay(0), 0.5)

    def test_doubles(self):
        self.assertEqual([delay(i) for i in range(4)], [0.5, 1.0, 2.0, 4.0])

    def test_capped(self):
        self.assertEqual(delay(10), 8.0)


if __name__ == "__main__":
    unittest.main()
