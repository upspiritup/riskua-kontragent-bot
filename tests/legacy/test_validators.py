import unittest


class EdrpouValidatorTests(unittest.TestCase):
    def test_accepts_exactly_eight_digits(self):
        from app.utils.validators import is_valid_edrpou

        self.assertTrue(is_valid_edrpou("12345678"))

    def test_trims_outer_whitespace(self):
        from app.utils.validators import is_valid_edrpou

        self.assertTrue(is_valid_edrpou(" 12345678 "))

    def test_rejects_anything_other_than_exactly_eight_digits(self):
        from app.utils.validators import is_valid_edrpou

        invalid_values = [
            "1234567",
            "123456789",
            "1234 5678",
            "1234-5678",
            "abcdefgh",
            "１２３４５６７８",
            "",
        ]

        for value in invalid_values:
            with self.subTest(value=value):
                self.assertFalse(is_valid_edrpou(value))


if __name__ == "__main__":
    unittest.main()
