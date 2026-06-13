"""Data Anonymizer Service

Service for anonymizing personally identifiable information (PII)
in knowledge entries and other data.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class AnonymizationResult:
    """Result of anonymization operation."""

    original_text: str
    anonymized_text: str
    entities_found: int
    entities_removed: list[str] = field(default_factory=list)
    replacements_made: dict[str, str] = field(default_factory=dict)


class DataAnonymizer:
    """Service for anonymizing PII in text content.

    Supports common PII types:
    - Email addresses
    - Phone numbers
    - ID numbers (Chinese citizen ID, etc.)
    - Bank card numbers
    - IP addresses
    - Personal names (basic patterns)
    """

    # Regex patterns for common PII types
    EMAIL_PATTERN = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE,
    )

    # Chinese phone numbers (mobile)
    PHONE_CN_PATTERN = re.compile(
        r"1[3-9]\d{9}",
    )

    # US phone numbers
    PHONE_US_PATTERN = re.compile(
        r"(\+1)?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
    )

    # Chinese citizen ID (18 digits)
    ID_CN_PATTERN = re.compile(
        r"\d{17}[\dXx]",
    )

    # Credit card numbers (13-19 digits)
    CARD_PATTERN = re.compile(
        r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{1,7}",
    )

    # IP addresses (IPv4)
    IP_PATTERN = re.compile(
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    )

    # Bank account patterns
    BANK_ACCOUNT_PATTERN = re.compile(
        r"\d{10,20}",
    )

    def __init__(self, salt: str = ""):
        """Initialize the anonymizer.

        Args:
            salt: Optional salt for hashing (enhances privacy)
        """
        self.salt = salt

    def anonymize(
        self,
        text: str,
        pii_types: list[str] | None = None,
        preserve_format: bool = True,
    ) -> AnonymizationResult:
        """Anonymize PII in text.

        Args:
            text: Input text to anonymize
            pii_types: List of PII types to detect (default: all)
            preserve_format: If True, preserve format (e.g., ***@***.com)

        Returns:
            AnonymizationResult with original and anonymized text
        """
        pii_types = pii_types or [
            "email",
            "phone",
            "id",
            "card",
            "ip",
        ]

        anonymized = text
        entities_removed = []
        replacements_made = {}

        for pii_type in pii_types:
            if pii_type == "email":
                anonymized, found = self._anonymize_emails(
                    anonymized, preserve_format
                )
                entities_removed.extend(found)
            elif pii_type == "phone":
                anonymized, found = self._anonymize_phones(
                    anonymized, preserve_format
                )
                entities_removed.extend(found)
            elif pii_type == "id":
                anonymized, found = self._anonymize_ids(
                    anonymized, preserve_format
                )
                entities_removed.extend(found)
            elif pii_type == "card":
                anonymized, found = self._anonymize_cards(
                    anonymized, preserve_format
                )
                entities_removed.extend(found)
            elif pii_type == "ip":
                anonymized, found = self._anonymize_ips(
                    anonymized, preserve_format
                )
                entities_removed.extend(found)

        return AnonymizationResult(
            original_text=text,
            anonymized_text=anonymized,
            entities_found=len(entities_removed),
            entities_removed=entities_removed,
            replacements_made=replacements_made,
        )

    def _anonymize_emails(
        self, text: str, preserve_format: bool
    ) -> tuple[str, list[str]]:
        """Anonymize email addresses.

        Args:
            text: Input text
            preserve_format: Preserve email format

        Returns:
            Tuple of (anonymized text, list of found emails)
        """
        found = []

        def replace_email(match):
            email = match.group(0)
            found.append(email)
            if preserve_format:
                parts = email.split("@")
                return f"{parts[0][:2]}***@***.{parts[1].split('.')[-1]}"
            return self._hash_value(email)

        result = self.EMAIL_PATTERN.sub(replace_email, text)
        return result, found

    def _anonymize_phones(
        self, text: str, preserve_format: bool
    ) -> tuple[str, list[str]]:
        """Anonymize phone numbers.

        Args:
            text: Input text
            preserve_format: Preserve phone format

        Returns:
            Tuple of (anonymized text, list of found phones)
        """
        found = []

        # Chinese phones
        def replace_phone_cn(match):
            phone = match.group(0)
            found.append(phone)
            if preserve_format:
                return f"{phone[:3]}****{phone[-4:]}"
            return self._hash_value(phone)

        result = self.PHONE_CN_PATTERN.sub(replace_phone_cn, text)
        result = self.PHONE_US_PATTERN.sub(replace_phone_cn, result)
        return result, found

    def _anonymize_ids(
        self, text: str, preserve_format: bool
    ) -> tuple[str, list[str]]:
        """Anonymize ID numbers.

        Args:
            text: Input text
            preserve_format: Preserve ID format

        Returns:
            Tuple of (anonymized text, list of found IDs)
        """
        found = []

        def replace_id(match):
            id_num = match.group(0)
            found.append(id_num)
            if preserve_format:
                return f"{id_num[:6]}********{id_num[-4:]}"
            return self._hash_value(id_num)

        result = self.ID_CN_PATTERN.sub(replace_id, text)
        return result, found

    def _anonymize_cards(
        self, text: str, preserve_format: bool
    ) -> tuple[str, list[str]]:
        """Anonymize card numbers.

        Args:
            text: Input text
            preserve_format: Preserve card format

        Returns:
            Tuple of (anonymized text, list of found cards)
        """
        found = []

        def replace_card(match):
            card = match.group(0)
            # Validate likely card number (Luhn-like check)
            digits = card.replace("-", "").replace(" ", "")
            if len(digits) >= 13 and len(digits) <= 19 and digits.isdigit():
                found.append(card)
                if preserve_format:
                    return f"****-****-****-{digits[-4:]}"
                return self._hash_value(card)
            return card

        result = self.CARD_PATTERN.sub(replace_card, text)
        return result, found

    def _anonymize_ips(
        self, text: str, preserve_format: bool
    ) -> tuple[str, list[str]]:
        """Anonymize IP addresses.

        Args:
            text: Input text
            preserve_format: Preserve IP format

        Returns:
            Tuple of (anonymized text, list of found IPs)
        """
        found = []

        def replace_ip(match):
            ip = match.group(0)
            found.append(ip)
            if preserve_format:
                parts = ip.split(".")
                return f"{parts[0]}.***.***.{parts[-1]}"
            return self._hash_value(ip)

        result = self.IP_PATTERN.sub(replace_ip, text)
        return result, found

    def _hash_value(self, value: str) -> str:
        """Create a hashed replacement for a value.

        Args:
            value: Value to hash

        Returns:
            Hashed replacement string
        """
        composite = f"{value}:{self.salt}"
        hash_digest = hashlib.sha256(composite.encode()).hexdigest()
        return f"[HASH:{hash_digest[:16]}]"

    async def anonymize_knowledge_entry(
        self,
        content: str,
        entry_id: UUID | None = None,
    ) -> AnonymizationResult:
        """Anonymize a knowledge entry content.

        Args:
            content: Knowledge entry content
            entry_id: Optional entry ID for logging

        Returns:
            AnonymizationResult with anonymized content
        """
        # Add entry ID to salt for uniqueness
        salt = f"{self.salt}:{entry_id}" if entry_id else self.salt
        anonymizer = DataAnonymizer(salt=salt)

        result = anonymizer.anonymize(
            content,
            pii_types=["email", "phone", "id", "card", "ip"],
            preserve_format=True,
        )

        return result

    async def anonymize_batch(
        self,
        texts: list[str],
        entry_ids: list[UUID] | None = None,
    ) -> list[AnonymizationResult]:
        """Anonymize multiple texts.

        Args:
            texts: List of texts to anonymize
            entry_ids: Optional list of entry IDs for logging

        Returns:
            List of AnonymizationResult
        """
        results = []
        for i, text in enumerate(texts):
            entry_id = entry_ids[i] if entry_ids and i < len(entry_ids) else None
            result = await self.anonymize_knowledge_entry(text, entry_id)
            results.append(result)

        return results