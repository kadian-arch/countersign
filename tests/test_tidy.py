import unittest

from countersign import tidy

CLEAN = ("Hi Dana,\n\nThanks for letting us know about order #10471. A refund of $9.50 has been issued, e.g. to the card you used. "
         "Our support page is https://example.com/help.html and the owner is on owner@example.com.\n\nBest regards,\nMill Street Coffee Roasters")


class TidyTests(unittest.TestCase):
    def test_ordinary_text_is_left_exactly_as_it_is(self):
        self.assertEqual(tidy.reply(CLEAN), CLEAN)

    def test_it_is_the_same_if_cleaned_twice(self):
        messy = "Hi Dana , **thanks**​ ,, for  waiting … the  the usual   time !\n\n\n\n* one\n• two"
        once = tidy.reply(messy)
        self.assertEqual(tidy.reply(once), once)

    def test_spacing_characters_of_every_kind_become_plain_spaces(self):
        for space in (" ", " ", " ", " ", "　", " "):
            self.assertEqual(tidy.reply(f"Please{space}allow{space}time."), "Please allow time.", repr(space))

    def test_invisible_characters_inside_words_vanish(self):
        self.assertEqual(tidy.reply("re​fund­ ed ﻿now⁠."), "refund ed now.")
        self.assertEqual(tidy.reply("a\x00b\x07c"), "abc")

    def test_markdown_a_mail_client_will_not_render_is_flattened(self):
        raw = "## Update\n**Your refund** is `done`.\n* first\n• second\nSee [our page](https://example.com/help)."
        self.assertEqual(tidy.reply(raw), "Update\nYour refund is done.\n- first\n- second\nSee our page.")

    def test_stray_punctuation_and_ellipses_are_cleaned_in_general(self):
        self.assertEqual(tidy.reply("Please allow … the usual time."), "Please allow the usual time.")
        self.assertEqual(tidy.reply("Please allow ... the usual time."), "Please allow the usual time.")
        self.assertEqual(tidy.reply("... Thanks for waiting."), "Thanks for waiting.")
        self.assertEqual(tidy.reply("Hello , there ,, friend!!"), "Hello, there, friend!")
        self.assertEqual(tidy.reply("Yes,thank you;ok"), "Yes, thank you; ok")

    def test_real_ellipses_and_decimals_and_domains_survive(self):
        self.assertEqual(tidy.reply("Well... that is odd. It cost $9.50 at example.com."), "Well... that is odd. It cost $9.50 at example.com.")

    def test_a_word_said_twice_is_said_once_but_numbers_are_kept(self):
        self.assertEqual(tidy.reply("Thank you you for the the order 10 10 times."), "Thank you for the order 10 10 times.")

    def test_dashes_that_read_like_a_template_become_plain_hyphens(self):
        self.assertEqual(tidy.reply("Your refund — all of it — is done."), "Your refund - all of it - is done.")

    def test_html_entities_are_decoded(self):
        self.assertEqual(tidy.reply("Tom &amp; Jerry&nbsp;said it&#39;s fine."), "Tom & Jerry said it's fine.")

    def test_a_line_of_noise_is_dropped_but_lines_with_numbers_stay(self):
        noise = "<<<<>>>> ~~~~ #### @@@@ %%%% ^^^^ &&&& ****"
        self.assertEqual(tidy.reply(f"Hi,\n{noise}\nThanks."), "Hi,\nThanks.")
        self.assertEqual(tidy.reply("Order #10471: $9.50 refunded 2026-10-17"), "Order #10471: $9.50 refunded 2026-10-17")
        self.assertEqual(tidy.reply("Hi Dana,\n" + "x" * 50 + "\nThanks for your order, we hope you enjoy it."),
                         "Hi Dana,\nThanks for your order, we hope you enjoy it.")

    def test_if_almost_nothing_readable_is_left_it_says_so_instead_of_sending_scraps(self):
        self.assertEqual(tidy.reply("Thank you for your order " + " ".join(["%%%%%%%%%%%%%%%%%%%%%%%%%%%%"] * 3)), "Thank you for your order")
        self.assertEqual(tidy.reply("----------\nThanks for waiting.\n=========="), "Thanks for waiting.")
        self.assertEqual(tidy.reply("x" * 60 + "\n" + "y" * 60), "Thanks for your message. The owner will follow up shortly.")


if __name__ == "__main__":
    unittest.main()
