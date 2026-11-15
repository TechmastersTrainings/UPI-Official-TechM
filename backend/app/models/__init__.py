"""Import every model so Base.metadata is complete (Alembic and tests rely on this)."""

from app.models.identity import Role, User, UserSession
from app.models.logs import ApiRequestLog, AuditLog
from app.models.merchant import (
    ApiCredential,
    Merchant,
    MerchantBankAccount,
    MerchantProfile,
    PaymentProvider,
    ProviderConfiguration,
    WebhookConfiguration,
)
from app.models.payment import (
    Payment,
    PaymentAttempt,
    PaymentEvent,
    ProviderCallback,
    Refund,
    Transaction,
    WebhookDelivery,
)
from app.models.settlement import ReconciliationRecord, Settlement

__all__ = [
    "ApiCredential",
    "ApiRequestLog",
    "AuditLog",
    "Merchant",
    "MerchantBankAccount",
    "MerchantProfile",
    "Payment",
    "PaymentAttempt",
    "PaymentEvent",
    "PaymentProvider",
    "ProviderCallback",
    "ProviderConfiguration",
    "ReconciliationRecord",
    "Refund",
    "Role",
    "Settlement",
    "Transaction",
    "User",
    "UserSession",
    "WebhookConfiguration",
    "WebhookDelivery",
]
