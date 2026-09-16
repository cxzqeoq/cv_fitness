from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AppSettings


def get_app_settings(db: Session) -> AppSettings:
    settings = db.get(AppSettings, 1)
    if settings is not None:
        return settings

    settings = AppSettings(id=1)
    db.add(settings)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        settings = db.get(AppSettings, 1)
        if settings is None:
            raise
        return settings
    db.refresh(settings)
    return settings
