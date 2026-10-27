import unittest

from invoice import invoice_total


class TestInvoice(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(invoice_total([(2, "3.50"), (1, "1.25")]), "8.25")

    def test_float_drift(self):
        self.assertEqual(invoice_total([(3, "0.10")]), "0.30")

    def test_half_cent_rounds_up(self):
        self.assertEqual(invoice_total([(1, "2.675")]), "2.68")

    def test_many_small_lines(self):
        self.assertEqual(invoice_total([(1, "0.01")] * 100), "1.00")


if __name__ == "__main__":
    unittest.main()
