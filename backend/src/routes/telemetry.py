from fastapi import APIRouter,Depends,Query
from src.middlewares.auth import current,writer,admin
from src.schemas.business import TelemetryReport
from src.services import telemetry,dedup
from src.controllers.business import report_reading,run_dedup,finalize_dedup
router=APIRouter()
@router.post('/telemetry/report')
def report(data:TelemetryReport,u=Depends(writer)):return report_reading(data,u)
@router.get('/telemetry/dedup/status')
def dedup_status(u=Depends(current)):return dedup.status()
@router.post('/telemetry/dedup/run')
def dedup_run(limit:int=Query(200,ge=1,le=1000),u=Depends(writer)):return run_dedup(limit,u)
@router.post('/telemetry/dedup/finalize')
def dedup_finalize(u=Depends(admin)):return finalize_dedup(u)
@router.get('/telemetry/{item_id}')
def by_id(item_id:int,u=Depends(current)):return telemetry.get_reading(item_id)
