from __future__ import annotations

from dataclasses import dataclass


class ProviderPolicyDenied(RuntimeError):
    """External model egress is not permitted for this document/context."""


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    provider: str
    allow_public_documents: bool = True
    allow_private_documents: bool = False
    require_redaction_for_private: bool = True
    permitted_document_classes: frozenset[str] = frozenset()

    def permits(
        self,
        *,
        document_class: str,
        is_public: bool,
        redacted: bool,
    ) -> bool:
        if (
            self.permitted_document_classes
            and document_class not in self.permitted_document_classes
        ):
            return False
        if is_public:
            return self.allow_public_documents
        if not self.allow_private_documents:
            return False
        return not self.require_redaction_for_private or redacted


def enforce_provider_policy(
    policy: ProviderPolicy,
    *,
    document_class: str,
    is_public: bool,
    redacted: bool,
) -> None:
    if not policy.permits(
        document_class=document_class,
        is_public=is_public,
        redacted=redacted,
    ):
        raise ProviderPolicyDenied(
            f"provider {policy.provider!r} is not approved for this document context"
        )
