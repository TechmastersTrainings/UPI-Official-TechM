"""Maps provider codes to adapters. Refuses any adapter that is not live-capable for LIVE, checking
both the adapter class and the database flag, so a misconfigured row can't route live money to a
simulator."""

from app.core.crypto import decrypt_json
from app.core.errors import AppError
from app.models import ProviderConfiguration
from app.models.enums import Environment
from app.providers.base import PaymentProvider, ProviderContext
from app.providers.sandbox import SandboxProvider

_ADAPTERS: dict[str, type] = {
    SandboxProvider.code: SandboxProvider,
    # Real adapters are registered here once a provider agreement and API documentation exist.
}


class ProviderUnavailable(AppError):
    status_code = 409
    code = "PROVIDER_UNAVAILABLE"


def get_adapter(code: str, environment: str, *, db_live_capable: bool) -> PaymentProvider:
    cls = _ADAPTERS.get(code)
    if cls is None:
        raise ProviderUnavailable(f"No adapter is installed for provider '{code}'")
    if environment == Environment.LIVE and not (cls.live_capable and db_live_capable):
        raise ProviderUnavailable(f"Provider '{code}' cannot be used for live payments")
    return cls(environment)


def context_for(config: ProviderConfiguration) -> ProviderContext:
    return ProviderContext(
        provider_code=config.provider.code,
        environment=config.environment,
        provider_merchant_id=config.provider_merchant_id,
        credentials=decrypt_json(config.credentials_enc) if config.credentials_enc else {},
    )
