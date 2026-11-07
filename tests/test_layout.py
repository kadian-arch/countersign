import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "countersign" / "static"
PAGE = (STATIC / "index.html").read_text(encoding="utf-8")


class PhoneLayoutTests(unittest.TestCase):
    """The page must fit a 320 pixel wide phone. A column or a field that insists on a fixed width wider than the screen makes the
    whole page scroll sideways, so a minimum width has to give way to the space there is: min(280px, 100%)."""

    def test_no_grid_column_has_a_fixed_pixel_minimum(self):
        bad = re.findall(r"minmax\((\d{3,})px", PAGE)
        self.assertEqual(bad, [], "write minmax(min(Npx, 100%), 1fr) so the column can shrink on a phone")

    def test_no_element_has_a_fixed_minimum_width_over_one_hundred_pixels(self):
        bad = [m for m in re.findall(r"min-width:\s*(\d{3,})px", PAGE) if int(m) > 120]
        self.assertEqual(bad, [], "write min-width: min(Npx, 100%)")

    def test_the_top_bar_has_a_phone_layout(self):
        self.assertRegex(PAGE, r"@media \(max-width: 640px\) \{\s*nav \.wrap \{ flex-wrap: wrap")

    def test_the_page_scales_to_the_device(self):
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', PAGE)


if __name__ == "__main__":
    unittest.main()
