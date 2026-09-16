import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AppSettings


def get_app_settings(
    db: Session,
    org_id: uuid.UUID | str | None = None,
) -> AppSettings:
    target_org = org_id or db.info.get("org_id")
    if target_org is None:
        raise RuntimeError("organization context is required for application settings")
    target_org = (
        target_org if isinstance(target_org, uuid.UUID) else uuid.UUID(str(target_org))
    )
    settings = (
        db.query(AppSettings)
        .filter(AppSettings.org_id == target_org)
        .first()
    )
    if settings is not None:
        return settings

    settings = AppSettings(org_id=target_org)
    db.add(settings)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        settings = (
            db.query(AppSettings)
            .filter(AppSettings.org_id == target_org)
            .first()
        )
        if settings is None:
            raise
        return settings
    db.refresh(settings)
    return settings
