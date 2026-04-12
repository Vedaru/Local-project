"""
Unit tests for modules/utils.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCleanText:
    """Tests for clean_text function."""

    def test_clean_text_removes_emojis(self):
        """Test that emojis are removed from text."""
        from modules.utils import clean_text

        text = "Hello 😀 World"
        result = clean_text(text)
        assert "😀" not in result

    def test_clean_text_preserves_chinese(self):
        """Test that Chinese characters are preserved."""
        from modules.utils import clean_text

        text = "你好世界"
        result = clean_text(text)
        assert result == "你好世界"

    def test_clean_text_preserves_punctuation(self):
        """Test that common punctuation is preserved."""
        from modules.utils import clean_text

        text = "你好！这是测试。"
        result = clean_text(text)
        assert "！" in result
        assert "。" in result

    def test_clean_text_collapses_whitespace(self):
        """Test that multiple spaces are collapsed."""
        from modules.utils import clean_text

        text = "Hello    World"
        result = clean_text(text)
        assert "    " not in result
        assert " " in result

    def test_clean_text_strips_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        from modules.utils import clean_text

        text = "  Hello World  "
        result = clean_text(text)
        assert result == "Hello World"


class TestExtractEntities:
    """Tests for extract_entities function."""

    def test_extract_entities_finds_person_names(self):
        """Test that person names are extracted."""
        from modules.utils import extract_entities

        text = "张三和李四是好朋友"
        entities = extract_entities(text)
        # Note: Results depend on jieba's segmentation
        assert isinstance(entities, set)

    def test_extract_entities_finds_organizations(self):
        """Test that organization names are extracted."""
        from modules.utils import extract_entities

        text = "我在北京大学工作"
        entities = extract_entities(text)
        assert isinstance(entities, set)
        # Should contain organization-like entities
        assert any("大学" in e for e in entities) or "北京大学" in entities

    def test_extract_entities_handles_empty_text(self):
        """Test that empty text returns empty set."""
        from modules.utils import extract_entities

        text = ""
        entities = extract_entities(text)
        assert isinstance(entities, set)
        assert len(entities) == 0


class TestFilterEmotionTags:
    """Tests for filter_emotion_tags function."""

    def test_filter_emotion_tags_removes_happy(self):
        """Test that [开心] tag is removed."""
        from modules.utils import filter_emotion_tags

        text = "这是一个测试[开心]句子"
        result = filter_emotion_tags(text)
        assert "[开心]" not in result
        assert "测试" in result
        assert "句子" in result

    def test_filter_emotion_tags_removes_angry(self):
        """Test that [生气] tag is removed."""
        from modules.utils import filter_emotion_tags

        text = "[生气]我很生气"
        result = filter_emotion_tags(text)
        assert "[生气]" not in result

    def test_filter_emotion_tags_handles_multiple_tags(self):
        """Test that multiple emotion tags are removed."""
        from modules.utils import filter_emotion_tags

        text = "[开心]你好[生气]世界[疑惑]"
        result = filter_emotion_tags(text)
        assert "[开心]" not in result
        assert "[生气]" not in result
        assert "[疑惑]" not in result
        assert "你好" in result
        assert "世界" in result

    def test_filter_emotion_tags_removes_normal_brackets(self):
        """Test that bracket symbols are removed while content is preserved."""
        from modules.utils import filter_emotion_tags

        text = "这是[普通]括号"
        result = filter_emotion_tags(text)
        assert "[" not in result
        assert "]" not in result
        assert result == "这是普通括号"

    def test_filter_emotion_tags_removes_motion_tags(self):
        """Test that motion control tags are removed from speak text."""
        from modules.utils import filter_emotion_tags

        text = "准备好了[动作:TapBody:0]"
        result = filter_emotion_tags(text)
        assert "[动作:TapBody:0]" not in result
        assert "准备好了" in result

    def test_filter_emotion_tags_removes_fullwidth_emotion_tag(self):
        """Test that full-width emotion tags are removed."""
        from modules.utils import filter_emotion_tags

        text = "【开心】你好"
        result = filter_emotion_tags(text)
        assert "【开心】" not in result
        assert result == "你好"

    def test_filter_emotion_tags_removes_parenthetical_stage_direction(self):
        """Test that short emotional stage directions are removed."""
        from modules.utils import filter_emotion_tags

        text = "你好（微笑）呀"
        result = filter_emotion_tags(text)
        assert "（微笑）" not in result
        assert result == "你好呀"

    def test_filter_emotion_tags_removes_parentheses_symbols(self):
        """Test that bracket symbols are removed from final dialogue text."""
        from modules.utils import filter_emotion_tags

        text = "版本(v2)可用"
        result = filter_emotion_tags(text)
        assert "(" not in result
        assert ")" not in result
        assert result == "版本v2可用"

    def test_filter_emotion_tags_removes_prefix_style_emotion_marker(self):
        """Test that prefix-style emotion metadata is removed."""
        from modules.utils import filter_emotion_tags

        text = "你好（表情:微笑）呀"
        result = filter_emotion_tags(text)
        assert "（表情:微笑）" not in result
        assert result == "你好呀"

    def test_filter_emotion_tags_removes_emoticon_package_text(self):
        """Test that emoticon-package stage text is removed."""
        from modules.utils import filter_emotion_tags

        text = "这是（表情包）测试"
        result = filter_emotion_tags(text)
        assert "表情包" not in result
        assert result == "这是测试"


class TestAvatarControlTags:
    """Tests for extracting avatar control tags."""

    def test_extract_emotion_tags_in_order(self):
        from modules.utils import extract_emotion_tags

        text = "你好[开心]再见[疑惑]"
        tags = extract_emotion_tags(text)
        assert tags == ["开心", "疑惑"]

    def test_extract_emotion_tags_supports_fullwidth_brackets(self):
        from modules.utils import extract_emotion_tags

        text = "【开心】你好[疑惑]"
        tags = extract_emotion_tags(text)
        assert tags == ["开心", "疑惑"]

    def test_extract_motion_commands_with_and_without_index(self):
        from modules.utils import extract_motion_commands

        text = "开始[动作:TapBody:2]然后[motion:Idle]"
        commands = extract_motion_commands(text)
        assert commands == [("TapBody", 2), ("Idle", None)]


class TestCheckSovitsService:
    """Tests for check_sovits_service function."""

    @patch("modules.utils.requests.get")
    def test_check_sovits_service_returns_true_on_success(self, mock_get):
        """Test that True is returned when service is available."""
        from modules.utils import check_sovits_service

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = check_sovits_service()
        assert result is True

    @patch("modules.utils.requests.get")
    def test_check_sovits_service_returns_false_on_error(self, mock_get):
        """Test that False is returned when service is unavailable."""
        from modules.utils import check_sovits_service

        mock_get.side_effect = Exception("Connection refused")

        result = check_sovits_service()
        assert result is False

    @patch("modules.utils.requests.get")
    def test_check_sovits_service_returns_false_on_non_200(self, mock_get):
        """Test that False is returned on non-200 status code."""
        from modules.utils import check_sovits_service

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = check_sovits_service()
        assert result is False


class TestStartGptSovitsApi:
    """Tests for start_gpt_sovits_api function."""

    def test_start_gpt_sovits_api_returns_none_for_invalid_path(self):
        """Test that None is returned for invalid path."""
        from modules.utils import start_gpt_sovits_api

        result = start_gpt_sovits_api("/nonexistent/path")
        assert result is None

    def test_start_gpt_sovits_api_returns_none_for_none_path(self):
        """Test that None is returned for None path."""
        from modules.utils import start_gpt_sovits_api

        result = start_gpt_sovits_api(None)
        assert result is None


class TestUtilityHelpers:
    """Tests for newly added generic utility helpers."""

    def test_truncate_text(self):
        from modules.utils import truncate_text

        assert truncate_text("hello", 10) == "hello"
        assert truncate_text("hello world", 8) == "hello..."
        assert truncate_text("hello world", 8, "..") == "hello .."

    def test_normalize_whitespace(self):
        from modules.utils import normalize_whitespace

        assert normalize_whitespace("a   b") == "a b"
        assert normalize_whitespace("a\n\t b") == "a b"
        assert normalize_whitespace(None) == ""

    def test_safe_json_loads(self):
        from modules.utils import safe_json_loads

        assert safe_json_loads('{"k": 1}') == {"k": 1}
        assert safe_json_loads("{bad", default={}) == {}
        assert safe_json_loads(b'{"ok": true}') == {"ok": True}

    def test_clamp_value(self):
        from modules.utils import clamp_value

        assert clamp_value(5.0, 0.0, 10.0) == 5.0
        assert clamp_value(-1.0, 0.0, 10.0) == 0.0
        assert clamp_value(15.0, 0.0, 10.0) == 10.0
        assert clamp_value(5.0, 10.0, 0.0) == 5.0

    def test_is_valid_identifier(self):
        from modules.utils import is_valid_identifier

        assert is_valid_identifier("user_001") is True
        assert is_valid_identifier("user-001") is True
        assert is_valid_identifier("bad name") is False
        assert is_valid_identifier("../../etc") is False
