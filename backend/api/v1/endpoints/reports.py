from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.deps import get_db
from backend.models.schemas.report import ReportSummaryOut
from backend.services.report_service import report_service

router = APIRouter()


@router.get("/summary", response_model=ReportSummaryOut)
def get_report_summary(db: Session = Depends(get_db)):
    """API tổng hợp báo cáo và thống kê vi phạm an toàn lao động."""
    return report_service.get_summary(db)
