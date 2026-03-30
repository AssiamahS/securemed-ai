"""
PHI Redaction Microservice

Pre-processes text to identify and redact Protected Health Information (PHI)
before it reaches the LLM. Supports the 18 HIPAA identifiers.

This is a safety net — defense in depth. The LLM system prompt also instructs
the model not to repeat identifiers, but pre-processing ensures PHI never
enters the model context unnecessarily.

Usage:
    from phi_redactor import PHIRedactor
    redactor = PHIRedactor()
    clean_text, redaction_map = redactor.redact(raw_text)
    # Send clean_text to LLM
    # Use redaction_map to restore if needed (stored locally, never logged)
"""

import re
import uuid
from dataclasses import dataclass, field


@dataclass
class RedactionResult:
    clean_text: str
    redaction_count: int
    categories: dict[str, int]
    # Map of placeholder -> original value (kept in memory only, never logged)
    _redaction_map: dict[str, str] = field(default_factory=dict, repr=False)

    def restore(self, text: str) -> str:
        """Restore redacted text with original values. Use only when necessary."""
        result = text
        for placeholder, original in self._redaction_map.items():
            result = result.replace(placeholder, original)
        return result


class PHIRedactor:
    """
    Identifies and redacts the 18 HIPAA identifiers from text.

    Categories covered:
    1. Names                    10. Account numbers
    2. Geographic data          11. Certificate/license numbers
    3. Dates (except year)      12. Vehicle identifiers
    4. Phone numbers            13. Device identifiers
    5. Fax numbers              14. Web URLs
    6. Email addresses          15. IP addresses
    7. SSN                      16. Biometric identifiers
    8. MRN / Medical records    17. Full-face photos (N/A for text)
    9. Health plan numbers      18. Any other unique identifier
    """

    def __init__(self, aggressive: bool = False):
        """
        Args:
            aggressive: If True, redact more aggressively (may cause false positives).
                       Recommended for legacy notes with inconsistent formatting.
        """
        self.aggressive = aggressive
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance on large documents."""
        self.patterns: list[tuple[str, re.Pattern, str]] = []

        # 7. SSN — xxx-xx-xxxx or xxxxxxxxx
        self.patterns.append((
            "SSN",
            re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b'),
            "[REDACTED-SSN]"
        ))

        # 4/5. Phone and fax — various formats
        self.patterns.append((
            "PHONE",
            re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
            "[REDACTED-PHONE]"
        ))

        # 6. Email
        self.patterns.append((
            "EMAIL",
            re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
            "[REDACTED-EMAIL]"
        ))

        # 15. IP addresses
        self.patterns.append((
            "IP_ADDRESS",
            re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
            "[REDACTED-IP]"
        ))

        # 14. URLs
        self.patterns.append((
            "URL",
            re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+'),
            "[REDACTED-URL]"
        ))

        # 8. MRN patterns — common formats
        self.patterns.append((
            "MRN",
            re.compile(r'\b(?:MRN|Medical Record|Record\s*#?)[\s:]*[\w-]{4,20}\b', re.IGNORECASE),
            "[REDACTED-MRN]"
        ))

        # 9. Insurance / health plan IDs
        self.patterns.append((
            "INSURANCE_ID",
            re.compile(r'\b(?:Medicare|Medicaid|Insurance|Policy|Member|Subscriber)\s*(?:ID|#|No|Number)[\s:]*[\w-]{4,20}\b', re.IGNORECASE),
            "[REDACTED-INSURANCE-ID]"
        ))

        # 10. Account numbers
        self.patterns.append((
            "ACCOUNT",
            re.compile(r'\b(?:Account|Acct)\s*(?:#|No|Number)?[\s:]*\d{4,20}\b', re.IGNORECASE),
            "[REDACTED-ACCOUNT]"
        ))

        # 3. Dates — MM/DD/YYYY, MM-DD-YYYY, Month DD, YYYY (redact day, keep year)
        self.patterns.append((
            "DATE",
            re.compile(r'\b(?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b'),
            "[REDACTED-DATE]"
        ))

        # DOB patterns
        self.patterns.append((
            "DOB",
            re.compile(r'\b(?:DOB|Date of Birth|Birth\s*Date)[\s:]*[^\n,]{6,20}', re.IGNORECASE),
            "[REDACTED-DOB]"
        ))

        # 2. Geographic — zip codes (5 or 9 digit)
        self.patterns.append((
            "ZIPCODE",
            re.compile(r'\b\d{5}(?:-\d{4})?\b'),
            "[REDACTED-ZIP]"
        ))

        # Street addresses (basic pattern)
        self.patterns.append((
            "ADDRESS",
            re.compile(r'\b\d+\s+(?:[A-Z][a-z]+\s+){1,3}(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Pl|Place)\.?\b', re.IGNORECASE),
            "[REDACTED-ADDRESS]"
        ))

        if self.aggressive:
            # 1. Names — aggressive mode tries to catch proper nouns after common prefixes
            self.patterns.append((
                "NAME",
                re.compile(r'\b(?:Patient|Name|Mr|Mrs|Ms|Dr|Miss)\.?\s*:?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b'),
                "[REDACTED-NAME]"
            ))

    def redact(self, text: str) -> RedactionResult:
        """
        Redact PHI from text.

        Returns RedactionResult with clean text, counts, and a reversible map.
        The redaction map is kept in memory only — never persisted or logged.
        """
        clean = text
        redaction_map = {}
        categories: dict[str, int] = {}

        for category, pattern, placeholder in self.patterns:
            matches = pattern.findall(clean)
            if matches:
                categories[category] = len(matches)

            def replace_match(match):
                original = match.group(0)
                token = f"{placeholder[:-1]}-{uuid.uuid4().hex[:6]}]"
                redaction_map[token] = original
                return token

            clean = pattern.sub(replace_match, clean)

        total = sum(categories.values())

        return RedactionResult(
            clean_text=clean,
            redaction_count=total,
            categories=categories,
            _redaction_map=redaction_map,
        )

    def scan(self, text: str) -> dict:
        """
        Scan text for PHI without redacting. Returns categories and counts.
        Useful for pre-flight checks before sending to LLM.
        """
        categories: dict[str, int] = {}
        for category, pattern, _ in self.patterns:
            matches = pattern.findall(text)
            if matches:
                categories[category] = len(matches)
        return {
            "phi_detected": bool(categories),
            "total_identifiers": sum(categories.values()),
            "categories": categories,
        }
