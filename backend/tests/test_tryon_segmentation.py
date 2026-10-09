"""The old outfit must be erased before the new garment goes on."""
import sys
import types
import unittest
from unittest import mock

from backend import config, virtual_tryon


class _Client:
    def __init__(self):
        self.kwargs = None

    def submit(self, api_name=None, **kwargs):
        self.kwargs = kwargs
        return object()


class SegmentationFreeTests(unittest.TestCase):
    def _submit(self, declared, setting):
        client = _Client()
        fake_gradio = types.ModuleType("gradio_client")
        fake_gradio.handle_file = lambda path: path
        provider = virtual_tryon.HuggingFaceSpaceProvider()
        with mock.patch.dict(sys.modules, {"gradio_client": fake_gradio}), \
                mock.patch.object(provider, "available", return_value=True), \
                mock.patch.object(provider, "_client", return_value=client), \
                mock.patch.object(virtual_tryon, "_endpoint_parameters", return_value=declared), \
                mock.patch.object(config, "TRYON_SEGMENTATION_FREE", setting, create=True):
            provider.submit(b"person", b"garment", "tops")
        return client.kwargs

    def test_original_clothes_are_erased_by_default(self):
        self.assertFalse(config.TRYON_SEGMENTATION_FREE)
        args = self._submit({"garment_photo_type", "segmentation_free"}, False)
        self.assertIs(args["segmentation_free"], False)

    def test_setting_can_switch_it_back(self):
        args = self._submit({"segmentation_free"}, True)
        self.assertIs(args["segmentation_free"], True)

    def test_hosts_without_the_option_are_not_sent_it(self):
        args = self._submit({"garment_photo_type"}, False)
        self.assertNotIn("segmentation_free", args)


if __name__ == "__main__":
    unittest.main()
