"""Import every model so Base.metadata is complete (needed by Alembic)."""

from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.category import Category, CategoryMapping
from app.models.credit import CreditLink
from app.models.cv_model import CvModel, SiteModel
from app.models.detection import Detection
from app.models.org_site import Camera, Organization, Site, User
from app.models.pos_sale import PosImportBatch, PosSale
from app.models.site_settings import SiteSettingsModel
from app.models.summary import DailySummary, HourlySummary

__all__ = [
    "Alert", "AuditLog", "Camera", "Category", "CategoryMapping", "CreditLink", "CvModel",
    "DailySummary", "Detection", "HourlySummary", "Organization", "PosImportBatch", "PosSale",
    "Site", "SiteModel", "SiteSettingsModel", "User",
]
