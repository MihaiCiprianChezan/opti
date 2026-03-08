import re

# Precompiled regex patterns for performance
NON_ALPHANUMERIC_REGEX = re.compile(r"[^a-zA-Z0-9\s]")
ALL_SPACES_REGEX = re.compile(r"\s+")
MULTIPLE_SPACES_REGEX = re.compile(r"\s{2,}")
EMOJIS_REGEX = re.compile(r"[\U0001F600-\U0001FBFF]+|[\U0000200B-\U0000200D]")
CHINESE_CHARACTERS_REGEX = re.compile(r"[\u4E00-\u9FFF]+")
JAPANESE_CHARACTERS_REGEX = re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF\uFF65-\uFF9F]+")
KOREAN_CHARACTERS_REGEX = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF]+") 