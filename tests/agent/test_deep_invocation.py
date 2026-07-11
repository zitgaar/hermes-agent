from agent.deep_invocation import (
    DeepInvocation,
    detect_deep_invocation,
    is_deep_skill_invocation_scaffold,
)


def test_detects_leading_ascii_deep_prefix() -> None:
    invocation = detect_deep_invocation("deep: explain this")

    assert invocation == DeepInvocation(
        source="prefix",
        mode="deep",
        raw_text="deep: explain this",
        user_instruction="explain this",
    )


def test_detects_leading_fullwidth_deep_prefix() -> None:
    invocation = detect_deep_invocation("deep：解释一下")

    assert invocation is not None
    assert invocation.source == "prefix"
    assert invocation.mode == "deep"
    assert invocation.user_instruction == "解释一下"


def test_ignores_mid_sentence_deep_literal() -> None:
    assert detect_deep_invocation("please discuss the literal deep: token") is None


def test_ignores_empty_deep_prefix() -> None:
    assert detect_deep_invocation("deep:") is None


def test_detects_generated_textual_deep_skill_scaffold() -> None:
    assert is_deep_skill_invocation_scaffold(
        '[IMPORTANT: The user has invoked the "deep" skill, indicating they want you to follow its instructions.]\n'
        "# deep\n"
    ) is True
    assert is_deep_skill_invocation_scaffold("deep: not a generated scaffold") is False
