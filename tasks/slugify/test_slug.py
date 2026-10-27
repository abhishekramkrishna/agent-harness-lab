import unittest

from slug import slugify


class TestSlugify(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(slugify("Agentic Loops"), "agentic-loops")

    def test_punctuation(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_runs_of_spaces(self):
        self.assertEqual(slugify("  Graphs   for   Harnesses "), "graphs-for-harnesses")

    def test_mixed_symbols(self):
        self.assertEqual(slugify("Evals -- why pass^k matters"), "evals-why-pass-k-matters")


if __name__ == "__main__":
    unittest.main()
