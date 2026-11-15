from app.models.enums import RoleName


class Perm:
    DASHBOARD_VIEW = "dashboard:view"
    AUDIT_VIEW = "audit:view"
    PLATFORM_USERS_VIEW = "platform_users:view"
    PLATFORM_USERS_MANAGE = "platform_users:manage"


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    RoleName.SUPER_ADMIN: frozenset(
        {Perm.DASHBOARD_VIEW, Perm.AUDIT_VIEW, Perm.PLATFORM_USERS_VIEW, Perm.PLATFORM_USERS_MANAGE}
    ),
    RoleName.PLATFORM_ADMIN: frozenset({Perm.DASHBOARD_VIEW, Perm.AUDIT_VIEW, Perm.PLATFORM_USERS_VIEW}),
    RoleName.PLATFORM_SUPPORT: frozenset({Perm.DASHBOARD_VIEW}),
    RoleName.MERCHANT_ADMIN: frozenset(),
    RoleName.MERCHANT_DEVELOPER: frozenset(),
    RoleName.MERCHANT_VIEWER: frozenset(),
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
