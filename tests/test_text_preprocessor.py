import importlib.util
import os
import sys
import types

import pytest
import torch

# create minimal stubs for modules referenced by TextPreprocessor
sys.modules.setdefault("text", types.ModuleType("text"))
# stub cleaner submodule
cleaner = types.ModuleType("text.cleaner")


def clean_text(t, language, version):
    # return text, empty word2ph, normalized text equal input
    return t, [], t


def cleaned_text_to_sequence(phones, version):
    return []


cleaner.clean_text = clean_text
sys.modules["text.cleaner"] = cleaner
sys.modules["text"].cleaner = cleaner
sys.modules["text"].cleaned_text_to_sequence = cleaned_text_to_sequence
# stub chinese module
sys.modules["text.chinese"] = types.ModuleType("text.chinese")
# stub LangSegmenter
langseg = types.ModuleType("text.LangSegmenter")


class LangSegmenter:
    @staticmethod
    def getTexts(text, lang=None):
        return []


langseg.LangSegmenter = LangSegmenter
sys.modules["text.LangSegmenter"] = langseg
sys.modules["text"].LangSegmenter = LangSegmenter

# stub segmentation package
segmod = types.ModuleType("TTS_infer_pack.text_segmentation_method")
segmod.split_big_text = lambda x: [x]
segmod.splits = ""
segmod.get_method = lambda m: (lambda t: t)
sys.modules["TTS_infer_pack.text_segmentation_method"] = segmod

# stub tools.i18n.i18n module
sys.modules.setdefault("tools", types.ModuleType("tools"))
sys.modules.setdefault("tools.i18n", types.ModuleType("tools.i18n"))
i18nmod = types.ModuleType("tools.i18n.i18n")


def I18nAuto(language=None):
    class C:
        def __call__(self, s):
            return s

    return C()


def scan_language_list():
    return []


i18nmod.I18nAuto = I18nAuto
i18nmod.scan_language_list = scan_language_list
sys.modules["tools.i18n.i18n"] = i18nmod
sys.modules["tools.i18n"].__dict__["i18n"] = i18nmod

# load TextPreprocessor as a standalone module to avoid importing TTS (which requires torchaudio)
_text_preprocessor_path = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    "modules",
    "gpt_sovits",
    "GPT_SoVITS",
    "TTS_infer_pack",
    "TextPreprocessor.py",
)
_text_preprocessor_path = os.path.normpath(_text_preprocessor_path)
spec = importlib.util.spec_from_file_location("TextPreprocessor", _text_preprocessor_path)
_text_preprocessor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_text_preprocessor)
TextPreprocessor = _text_preprocessor.TextPreprocessor


class DummyModel:
    def __init__(self, hidden_dim=8):
        self.hidden_dim = hidden_dim
        # callers may tweak this before each test
        self.expected_seq_len = 2

    def __call__(self, **inputs):
        # ignore inputs; build a fake hidden_states list
        seq = self.expected_seq_len
        # simple values are not important, only shape matters
        base = torch.zeros((1, seq, self.hidden_dim), dtype=torch.float32)
        # return a list with at least 3 entries so slicing [-3:-2] works
        return {"hidden_states": [base, base, base]}


class DummyTokenizer:
    def __call__(self, text, return_tensors="pt"):
        # generate a dummy tensor so the code can call .to(device)
        length = len(text) + 2
        return {"input_ids": torch.zeros((1, length), dtype=torch.long)}


@pytest.fixture
def preprocessor():
    model = DummyModel(hidden_dim=4)
    tokenizer = DummyTokenizer()
    return TextPreprocessor(model, tokenizer, torch.device("cpu"))


def test_empty_word2ph_returns_empty(preprocessor, capsys):
    # model will create seq_len=2 -> res after [1:-1] is zero-length
    preprocessor.bert_model.expected_seq_len = 2
    feat = preprocessor.get_bert_feature("", [])
    assert feat.shape == (4, 0)
    captured = capsys.readouterr()
    assert "warning: no phone-level features" in captured.out


def test_nonzero_text_all_zero_word2ph(preprocessor):
    preprocessor.bert_model.expected_seq_len = 5
    feat = preprocessor.get_bert_feature("abc", [0, 0, 0])
    assert feat.shape == (4, 0)


def test_normal_case(preprocessor):
    preprocessor.bert_model.expected_seq_len = 5
    feat = preprocessor.get_bert_feature("abc", [1, 1, 1])
    # expected feature dimension matches hidden_dim and number of phones
    assert feat.shape == (4, 3)


def test_assert_length_mismatch(preprocessor):
    with pytest.raises(AssertionError):
        preprocessor.get_bert_feature("a", [])


def test_get_phones_and_bert_skips_empty_segment(preprocessor):
    # calling with completely empty text should yield no phones and blank norm_text
    phones, bert, norm = preprocessor.get_phones_and_bert("", "en", "v1")
    # because of recursion the returned normalized text may include a dot prefix
    assert isinstance(norm, str)
    assert bert.shape == (1024, 0)
    # since phones length < 6 and final=False the method will recall with prefix '.'
    # ensure recursion stops and does not crash
    phones2, bert2, norm2 = preprocessor.get_phones_and_bert("a", "en", "v1")
    # phones2 may be nonempty after recursion (should not raise)
    assert isinstance(phones2, list)
    assert isinstance(norm2, str)
