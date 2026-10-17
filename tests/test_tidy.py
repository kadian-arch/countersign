import unittest

from countersign import tidy


class TidyTests(unittest.TestCase):
    def test_odd_spaces_become_plain_ones_and_a_lone_ellipsis_goes(self):
        raw = "Please allow … the usual time for the amount to appear."
        self.assertEqual(tidy.reply(raw), "Please allow the usual time for the amount to appear.")

    def test_paragraphs_and_real_ellipses_are_left_alone(self):
        raw = "Hi Dana,\n\nWell... that is odd.  Thanks,\nMill Street"
        self.assertEqual(tidy.reply(raw), "Hi Dana,\n\nWell... that is odd. Thanks,\nMill Street")


if __name__ == "__main__":
    unittest.main()
