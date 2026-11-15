"""Merchant bank accounts. Account numbers are encrypted at rest and returned masked; revealing the
full number is a separately permissioned, audited action.

Verification is currently a manual review by TechMasters operations (documents / cancelled cheque).
Automated penny-drop verification will plug in through the provider interface when a live provider
that offers it is integrated."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_str, encrypt_str, keyed_hash
from app.core.errors import AppError, Conflict, NotFound
from app.db.types import utcnow
from app.models import MerchantBankAccount, User
from app.models.enums import VerificationStatus
from app.schemas.merchant import BankAccountCreate, BankAccountOut, BankAccountUpdate
from app.services import audit
from app.services.audit import RequestMeta

MAX_ACCOUNTS_PER_ENV = 10


def to_out(a: MerchantBankAccount) -> BankAccountOut:
    return BankAccountOut(
        id=a.id, merchant_id=a.merchant_id, environment=a.environment, account_holder_name=a.account_holder_name,
        bank_name=a.bank_name, account_number_masked="XXXX" + a.account_number_last4, ifsc=a.ifsc, upi_vpa=a.upi_vpa,
        is_default=a.is_default, is_active=a.is_active, verification_status=a.verification_status,
        verification_note=a.verification_note, verified_at=a.verified_at, created_at=a.created_at, updated_at=a.updated_at,
    )


def _fingerprint(ifsc: str, number: str) -> str:
    return keyed_hash(f"bank:{ifsc}:{number}")


def list_for(db: Session, merchant_id: str, environment: str | None = None) -> list[MerchantBankAccount]:
    conds = [MerchantBankAccount.merchant_id == merchant_id]
    if environment:
        conds.append(MerchantBankAccount.environment == environment)
    return list(db.scalars(select(MerchantBankAccount).where(*conds).order_by(MerchantBankAccount.created_at)))


def get_owned(db: Session, merchant_id: str | None, account_id: str) -> MerchantBankAccount:
    a = db.get(MerchantBankAccount, account_id)
    if a is None or (merchant_id is not None and a.merchant_id != merchant_id):
        raise NotFound("Bank account not found")
    return a


def _ensure_unique(db: Session, merchant_id: str, env: str, fp: str, exclude_id: str | None = None) -> None:
    conds = [
        MerchantBankAccount.merchant_id == merchant_id,
        MerchantBankAccount.environment == env,
        MerchantBankAccount.account_fingerprint == fp,
    ]
    if exclude_id:
        conds.append(MerchantBankAccount.id != exclude_id)
    if db.scalar(select(func.count()).select_from(MerchantBankAccount).where(*conds)):
        raise Conflict("This bank account is already added", code="DUPLICATE_BANK_ACCOUNT")


def _clear_default(db: Session, merchant_id: str, env: str) -> None:
    db.execute(
        update(MerchantBankAccount)
        .where(MerchantBankAccount.merchant_id == merchant_id, MerchantBankAccount.environment == env)
        .values(is_default=False)
    )


def create(db: Session, merchant_id: str, body: BankAccountCreate, actor: User, meta: RequestMeta) -> MerchantBankAccount:
    existing = list_for(db, merchant_id, body.environment)
    if len(existing) >= MAX_ACCOUNTS_PER_ENV:
        raise AppError(f"At most {MAX_ACCOUNTS_PER_ENV} bank accounts per environment", code="LIMIT_REACHED")
    fp = _fingerprint(body.ifsc, body.account_number)
    _ensure_unique(db, merchant_id, body.environment, fp)

    make_default = body.make_default or not any(a.is_default and a.is_active for a in existing)
    if make_default:
        _clear_default(db, merchant_id, body.environment)
    acct = MerchantBankAccount(
        merchant_id=merchant_id, environment=body.environment, account_holder_name=body.account_holder_name,
        bank_name=body.bank_name, account_number_enc=encrypt_str(body.account_number),
        account_number_last4=body.account_number[-4:], account_fingerprint=fp, ifsc=body.ifsc, upi_vpa=body.upi_vpa,
        is_default=make_default, is_active=True, verification_status=VerificationStatus.PENDING,
    )
    db.add(acct)
    db.flush()
    audit.record(db, "bank_account.created", actor=actor, entity_type="bank_account", entity_id=acct.id,
                 merchant_id=merchant_id, details={"environment": acct.environment, "ifsc": acct.ifsc,
                 "last4": acct.account_number_last4, "is_default": make_default}, meta=meta)
    db.commit()
    db.refresh(acct)
    return acct


def update_account(db: Session, acct: MerchantBankAccount, body: BankAccountUpdate, actor: User, meta: RequestMeta) -> MerchantBankAccount:
    changes: dict = {}
    identity_changed = False
    number = body.account_number
    ifsc = body.ifsc or acct.ifsc
    if number is not None or body.ifsc is not None:
        current_number = number or decrypt_str(acct.account_number_enc)
        fp = _fingerprint(ifsc, current_number)
        if fp != acct.account_fingerprint:
            _ensure_unique(db, acct.merchant_id, acct.environment, fp, exclude_id=acct.id)
            acct.account_fingerprint = fp
            identity_changed = True
            if number is not None:
                acct.account_number_enc = encrypt_str(number)
                changes["account_number_last4"] = [acct.account_number_last4, number[-4:]]
                acct.account_number_last4 = number[-4:]
            if body.ifsc is not None and body.ifsc != acct.ifsc:
                changes["ifsc"] = [acct.ifsc, body.ifsc]
                acct.ifsc = body.ifsc
    for field in ("account_holder_name", "bank_name", "upi_vpa"):
        new = getattr(body, field)
        if new is not None and new != getattr(acct, field):
            changes[field] = [getattr(acct, field), new]
            setattr(acct, field, new)
            identity_changed = identity_changed or field == "account_holder_name"
    if body.clear_upi_vpa and acct.upi_vpa:
        changes["upi_vpa"] = [acct.upi_vpa, None]
        acct.upi_vpa = None

    if identity_changed:
        # Any change to who/where the money goes requires re-verification.
        acct.verification_status = VerificationStatus.PENDING
        acct.verified_at = None
        acct.verification_note = None
        changes["verification_status"] = "reset_to_PENDING"
    if changes:
        audit.record(db, "bank_account.updated", actor=actor, entity_type="bank_account", entity_id=acct.id,
                     merchant_id=acct.merchant_id, details=changes, meta=meta)
    db.commit()
    db.refresh(acct)
    return acct


def set_default(db: Session, acct: MerchantBankAccount, actor: User, meta: RequestMeta) -> MerchantBankAccount:
    if not acct.is_active:
        raise AppError("Activate the account before making it the default", code="ACCOUNT_INACTIVE")
    if not acct.is_default:
        _clear_default(db, acct.merchant_id, acct.environment)
        acct.is_default = True
        audit.record(db, "bank_account.set_default", actor=actor, entity_type="bank_account", entity_id=acct.id,
                     merchant_id=acct.merchant_id, meta=meta)
        db.commit()
        db.refresh(acct)
    return acct


def set_active(db: Session, acct: MerchantBankAccount, active: bool, actor: User, meta: RequestMeta) -> MerchantBankAccount:
    if acct.is_active != active:
        acct.is_active = active
        details = {"is_active": active}
        if not active and acct.is_default:
            acct.is_default = False
            details["default_cleared"] = True
        audit.record(db, "bank_account." + ("activated" if active else "deactivated"), actor=actor,
                     entity_type="bank_account", entity_id=acct.id, merchant_id=acct.merchant_id, details=details, meta=meta)
        db.commit()
        db.refresh(acct)
    return acct


def reveal(db: Session, acct: MerchantBankAccount, actor: User, meta: RequestMeta) -> str:
    number = decrypt_str(acct.account_number_enc)
    audit.record(db, "bank_account.revealed", actor=actor, entity_type="bank_account", entity_id=acct.id,
                 merchant_id=acct.merchant_id, meta=meta)
    db.commit()
    return number


def decide_verification(db: Session, acct: MerchantBankAccount, decision: str, note: str | None, actor: User, meta: RequestMeta) -> MerchantBankAccount:
    if acct.verification_status != VerificationStatus.PENDING:
        raise Conflict(f"Account is {acct.verification_status}, not pending verification", code="NOT_PENDING")
    if decision == VerificationStatus.REJECTED and not note:
        raise AppError("A note explaining the rejection is required", code="REASON_REQUIRED")
    acct.verification_status = decision
    acct.verification_note = note
    acct.verified_at = utcnow() if decision == VerificationStatus.VERIFIED else None
    audit.record(db, "bank_account.verification_" + decision.lower(), actor=actor, entity_type="bank_account",
                 entity_id=acct.id, merchant_id=acct.merchant_id, details={"note": note}, meta=meta)
    db.commit()
    db.refresh(acct)
    return acct
