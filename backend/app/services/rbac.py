from app.models.enums import RoleName


class Perm:
    # Platform (TechMasters staff)
    DASHBOARD_VIEW = "dashboard:view"
    AUDIT_VIEW = "audit:view"
    PLATFORM_USERS_VIEW = "platform_users:view"
    PLATFORM_USERS_MANAGE = "platform_users:manage"
    MERCHANTS_VIEW = "merchants:view"
    MERCHANTS_MANAGE = "merchants:manage"  # approve/suspend, verify bank accounts, approve provider onboarding
    MERCHANTS_LIVE = "merchants:live"  # switch a merchant's live mode on/off
    SENSITIVE_REVEAL = "sensitive:reveal"  # unmask bank account numbers (audited)
    PAYMENTS_VIEW = "payments:view"  # all merchants' payments

    # Merchant console (always scoped to the user's own merchant)
    M_VIEW = "merchant:view"
    M_PROFILE_EDIT = "merchant:profile_edit"
    M_BANK_VIEW = "merchant:bank_view"
    M_BANK_MANAGE = "merchant:bank_manage"
    M_BANK_REVEAL = "merchant:bank_reveal"
    M_PROVIDERS_MANAGE = "merchant:providers_manage"
    M_KEYS_MANAGE = "merchant:keys_manage"
    M_WEBHOOKS_MANAGE = "merchant:webhooks_manage"
    M_LOGS_VIEW = "merchant:logs_view"
    M_PAYMENTS_VIEW = "merchant:payments_view"
    M_PAYMENTS_MANAGE = "merchant:payments_manage"  # cancel unpaid payments from the console


_SUPER = {
    Perm.DASHBOARD_VIEW, Perm.AUDIT_VIEW, Perm.PLATFORM_USERS_VIEW, Perm.PLATFORM_USERS_MANAGE,
    Perm.MERCHANTS_VIEW, Perm.MERCHANTS_MANAGE, Perm.MERCHANTS_LIVE, Perm.SENSITIVE_REVEAL, Perm.PAYMENTS_VIEW,
}
_MERCHANT_ADMIN = {
    Perm.M_VIEW, Perm.M_PROFILE_EDIT, Perm.M_BANK_VIEW, Perm.M_BANK_MANAGE, Perm.M_BANK_REVEAL,
    Perm.M_PROVIDERS_MANAGE, Perm.M_KEYS_MANAGE, Perm.M_WEBHOOKS_MANAGE, Perm.M_LOGS_VIEW,
    Perm.M_PAYMENTS_VIEW, Perm.M_PAYMENTS_MANAGE,
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    RoleName.SUPER_ADMIN: frozenset(_SUPER),
    RoleName.PLATFORM_ADMIN: frozenset(
        {Perm.DASHBOARD_VIEW, Perm.AUDIT_VIEW, Perm.PLATFORM_USERS_VIEW, Perm.MERCHANTS_VIEW, Perm.MERCHANTS_MANAGE,
         Perm.PAYMENTS_VIEW}
    ),
    RoleName.PLATFORM_SUPPORT: frozenset({Perm.DASHBOARD_VIEW, Perm.MERCHANTS_VIEW, Perm.PAYMENTS_VIEW}),
    RoleName.MERCHANT_ADMIN: frozenset(_MERCHANT_ADMIN),
    RoleName.MERCHANT_DEVELOPER: frozenset(
        {Perm.M_VIEW, Perm.M_BANK_VIEW, Perm.M_KEYS_MANAGE, Perm.M_WEBHOOKS_MANAGE, Perm.M_LOGS_VIEW,
         Perm.M_PAYMENTS_VIEW}
    ),
    RoleName.MERCHANT_VIEWER: frozenset({Perm.M_VIEW, Perm.M_BANK_VIEW, Perm.M_LOGS_VIEW, Perm.M_PAYMENTS_VIEW}),
}

ROLE_DESCRIPTIONS = {
    RoleName.SUPER_ADMIN: "TechMasters super administrator with full platform control",
    RoleName.PLATFORM_ADMIN: "TechMasters operations administrator",
    RoleName.PLATFORM_SUPPORT: "TechMasters support staff (read-mostly)",
    RoleName.MERCHANT_ADMIN: "Merchant account owner/administrator",
    RoleName.MERCHANT_DEVELOPER: "Merchant developer (API keys, webhooks)",
    RoleName.MERCHANT_VIEWER: "Merchant read-only user",
}


def permissions_for(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())
