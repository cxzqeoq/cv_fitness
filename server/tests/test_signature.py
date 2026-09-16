import unittest

from app.workers import signature as sig


def _window(t, value):
    return {"tMid": t, "sig": {"lElbow": {"vel": value}}}


class SignaturePostProcessingTests(unittest.TestCase):
    def test_segment_signature_and_similar_merge(self):
        windows = [
            _window(2, 1), _window(6, 2),
            _window(10, 1), _window(14, 2),
            _window(18, 1), _window(22, 2),
            _window(26, 10), _window(30, 11),
        ]
        norms = sig.mad_normalize(windows)
        segments = sig.segments_from_candidates([
            {"boundary": 8, "conf": 2, "Dm": 1, "Dp": 1},
            {"boundary": 16, "conf": 2, "Dm": 1, "Dp": 1},
            {"boundary": 24, "conf": 2, "Dm": 1, "Dp": 1},
        ], 32)

        self.assertEqual(sig.segment_signature(windows, 0, 8)["lElbow"]["vel"], 1.5)
        merged = sig.merge_similar_segments(segments, windows, norms, merge_thr=0.3)
        self.assertLess(len(merged), len(segments))
        self.assertTrue(any(segment["boundary"] == 24 for segment in merged))

    def test_refine_candidates_filters_degenerate_and_nearby_peaks(self):
        signal = [{"t": t, "comb": 0.2, "Dm": 0, "Dp": 0} for t in range(61)]
        for t in range(18, 27):
            signal[t]["comb"] = 0.2 + (t - 18) * 0.5
        for t in range(26, 31):
            signal[t]["comb"] = 2.2 - (t - 26) * 0.4
        signal[26]["comb"] = 2.2
        candidates = [
            {"boundary": 5, "peakT": 5, "peak": 0.5, "conf": 0, "Dm": 1, "Dp": 1},
            {"boundary": 22, "peakT": 22, "peak": 1, "conf": 0.8, "Dm": 1, "Dp": 1},
            {"boundary": 26, "peakT": 26, "peak": 2.2, "conf": 2, "Dm": 1, "Dp": 1},
        ]

        refined = sig.refine_candidates(candidates, signal)
        self.assertEqual([candidate["boundary"] for candidate in refined], [26])

    def test_short_segment_drops_weaker_adjacent_boundary(self):
        candidates = [
            {"boundary": 20, "conf": 0.9, "Dm": 1, "Dp": 1},
            {"boundary": 24, "conf": 0.2, "Dm": 1, "Dp": 1},
            {"boundary": 60, "conf": 1, "Dm": 1, "Dp": 1},
        ]

        segments = sig.segments_from_candidates(candidates, 80, min_seg_sec=8)
        self.assertTrue(any(segment["start"] == 20 and segment["end"] == 60 for segment in segments))
        self.assertFalse(any(segment["boundary"] == 24 for segment in segments))

        tail = sig.segments_from_candidates([
            {"boundary": 20, "conf": 0.9, "Dm": 1, "Dp": 1},
            {"boundary": 74, "conf": 0.2, "Dm": 1, "Dp": 1},
        ], 80, min_seg_sec=8)
        self.assertTrue(any(segment["start"] == 20 and segment["end"] == 80 for segment in tail))
        self.assertFalse(any(segment["boundary"] == 74 for segment in tail))


if __name__ == "__main__":
    unittest.main()
