def is_prompt_sane_and_valid(text: str, min_tokens: int = 2, min_chars: int = 5, min_unique_tokens: int = 2) -> bool:
    """
    Validate that a recognized speech utterance is substantive enough to process.

    Filters out ASR noise: breathing sounds, filler words, accidental single words, repetition.

    Args:
        text: Raw or punctuation-restored ASR text.
        min_tokens: Minimum number of words required. Default 2.
        min_chars: Minimum total character count. Default 5.
        min_unique_tokens: Minimum number of distinct words (catches "go go go"). Default 2.

    Returns:
        True if the utterance should be processed, False if it should be discarded.
    """
    if not text or not text.strip():
        return False
    tokens = text.strip().split()
    if len(tokens) < min_tokens:
        return False
    if len(text.strip()) < min_chars:
        return False
    if len(set(tokens)) < min_unique_tokens:
        return False
    return True
