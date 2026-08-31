import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import llm_utils


class GenerateImageSyncProviderRoutingTests(unittest.TestCase):
    """generate_image_sync's own logic is just provider selection/fallback
    ordering plus a shrink pass on whatever a provider returns -- the raw
    HTTP calls inside _generate_image_huggingface/_generate_image_openai
    aren't unit-tested here, matching this project's convention of not
    unit-testing the httpx layer inside shared infra modules
    (llm_utils.py/mcp_client.py/mcp/*.py). _shrink_data_uri is patched to
    the identity function so these tests only exercise routing, not
    shrinking (covered separately by ShrinkDataUriTests below)."""

    def setUp(self):
        patcher = patch.object(llm_utils, "_shrink_data_uri", side_effect=lambda uri, *a, **k: uri)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_auto_prefers_huggingface_when_configured_and_it_succeeds(self):
        with patch.object(llm_utils, "HF_API_KEY", "hf_token"), \
                patch.object(llm_utils, "IMAGE_PROVIDER", "auto"), \
                patch.object(llm_utils, "_generate_image_huggingface", return_value="data:image/png;base64,AAA") as hf, \
                patch.object(llm_utils, "_generate_image_openai") as openai:
            result = llm_utils.generate_image_sync("a nice salad")

        self.assertEqual(result, "data:image/png;base64,AAA")
        hf.assert_called_once_with("a nice salad")
        openai.assert_not_called()

    def test_auto_falls_back_to_openai_when_huggingface_fails(self):
        with patch.object(llm_utils, "HF_API_KEY", "hf_token"), \
                patch.object(llm_utils, "IMAGE_PROVIDER", "auto"), \
                patch.object(llm_utils, "_generate_image_huggingface", return_value=""), \
                patch.object(llm_utils, "_generate_image_openai", return_value="data:image/png;base64,BBB") as openai:
            result = llm_utils.generate_image_sync("a nice salad")

        self.assertEqual(result, "data:image/png;base64,BBB")
        openai.assert_called_once()

    def test_auto_with_no_huggingface_key_goes_straight_to_openai(self):
        with patch.object(llm_utils, "HF_API_KEY", ""), \
                patch.object(llm_utils, "IMAGE_PROVIDER", "auto"), \
                patch.object(llm_utils, "_generate_image_huggingface") as hf, \
                patch.object(llm_utils, "_generate_image_openai", return_value="data:image/png;base64,CCC"):
            result = llm_utils.generate_image_sync("a nice salad")

        self.assertEqual(result, "data:image/png;base64,CCC")
        hf.assert_not_called()

    def test_huggingface_only_never_falls_back_to_openai(self):
        with patch.object(llm_utils, "HF_API_KEY", "hf_token"), \
                patch.object(llm_utils, "IMAGE_PROVIDER", "huggingface"), \
                patch.object(llm_utils, "_generate_image_huggingface", return_value=""), \
                patch.object(llm_utils, "_generate_image_openai") as openai:
            result = llm_utils.generate_image_sync("a nice salad")

        self.assertEqual(result, "")
        openai.assert_not_called()

    def test_openai_only_never_tries_huggingface_even_if_configured(self):
        with patch.object(llm_utils, "HF_API_KEY", "hf_token"), \
                patch.object(llm_utils, "IMAGE_PROVIDER", "openai"), \
                patch.object(llm_utils, "_generate_image_huggingface") as hf, \
                patch.object(llm_utils, "_generate_image_openai", return_value="data:image/png;base64,DDD") as openai:
            result = llm_utils.generate_image_sync("a nice salad")

        self.assertEqual(result, "data:image/png;base64,DDD")
        hf.assert_not_called()
        openai.assert_called_once()


def _make_test_png_data_uri(width: int, height: int) -> str:
    """A real (tiny, solid-color) PNG data URI for exercising the actual
    Pillow decode/resize/re-encode path in _shrink_data_uri, rather than
    a fake base64 string."""
    import base64
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 180, 90)).save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


class ShrinkDataUriTests(unittest.TestCase):
    def test_large_image_is_downscaled_and_recompressed_as_jpeg(self):
        original = _make_test_png_data_uri(800, 800)
        shrunk = llm_utils._shrink_data_uri(original, max_dimension=200, quality=80)

        self.assertTrue(shrunk.startswith("data:image/jpeg;base64,"))
        self.assertLess(len(shrunk), len(original))

    def test_shrunk_image_actually_fits_within_max_dimension(self):
        import base64
        from PIL import Image

        original = _make_test_png_data_uri(800, 600)
        shrunk = llm_utils._shrink_data_uri(original, max_dimension=200, quality=80)

        _, b64_data = shrunk.split(";base64,", 1)
        image = Image.open(io.BytesIO(base64.b64decode(b64_data)))
        self.assertLessEqual(max(image.size), 200)

    def test_image_already_within_max_dimension_is_still_recompressed(self):
        original = _make_test_png_data_uri(100, 100)
        shrunk = llm_utils._shrink_data_uri(original, max_dimension=200, quality=80)

        self.assertTrue(shrunk.startswith("data:image/jpeg;base64,"))

    def test_non_data_uri_input_is_returned_unchanged(self):
        self.assertEqual(llm_utils._shrink_data_uri("https://example.com/foo.png"), "https://example.com/foo.png")

    def test_empty_string_is_returned_unchanged(self):
        self.assertEqual(llm_utils._shrink_data_uri(""), "")

    def test_malformed_base64_falls_back_to_the_original_input(self):
        malformed = "data:image/png;base64,not-valid-base64!!"
        self.assertEqual(llm_utils._shrink_data_uri(malformed), malformed)


if __name__ == "__main__":
    unittest.main()
