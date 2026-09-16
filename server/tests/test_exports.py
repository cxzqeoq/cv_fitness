import unittest
from types import SimpleNamespace

from app.exports import build_srt


class SrtExportTests(unittest.TestCase):
    def test_uses_text_fallbacks_and_compact_cue_numbers(self):
        segments = [
            SimpleNamespace(
                start_sec=0,
                end_sec=59.9996,
                subtitle=" Явный субтитр ",
                description="Описание не должно использоваться",
                label="Первый",
            ),
            SimpleNamespace(
                start_sec=59.9996,
                end_sec=3661.2,
                subtitle=None,
                description="Описание второго сегмента",
                label="Второй",
            ),
            SimpleNamespace(
                start_sec=3661.2,
                end_sec=3662,
                subtitle="",
                description=None,
                label=None,
            ),
        ]

        self.assertEqual(
            build_srt(segments),
            "1\r\n"
            "00:00:00,000 --> 00:01:00,000\r\n"
            "Явный субтитр\r\n\r\n"
            "2\r\n"
            "00:01:00,000 --> 01:01:01,200\r\n"
            "Описание второго сегмента\r\n",
        )


if __name__ == "__main__":
    unittest.main()
