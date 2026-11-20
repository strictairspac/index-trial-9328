"""遥测上报与按编号查询。保留规则：同一 (sensor_id,recorded_at) 以最早入库行为准。"""
import hashlib,math
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.config.database import engine,Session
from src.models.telemetry import Telemetry,TelemetryAlias
from src.utils.serialization import record
TOL=1e-6  # FLOAT 单精度回读误差容差
def _matches(kept,value,device_type):
 return kept.device_type==device_type and math.isclose(kept.value,value,rel_tol=TOL,abs_tol=TOL)
def _lock_name(sensor_id,recorded_at):
 return 'telemetry_ingest_'+hashlib.sha1(f'{sensor_id}|{recorded_at}'.encode()).hexdigest()[:24]
def _kept_row(conn,params):
 return conn.execute(text('SELECT id,device_type,value FROM telemetry WHERE sensor_id=:s AND recorded_at=:r ORDER BY id LIMIT 1'),params).first()
def report(data):
 """同键同值返回保留编号；异值 409；已确认读数不覆盖。键级 GET_LOCK 使约束启用前后均幂等。"""
 name=_lock_name(data.sensor_id,data.recorded_at)
 params={'s':data.sensor_id,'r':data.recorded_at}
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:n,10)'),{'n':name}).scalar()!=1:
   raise HTTPException(503,'上报通道繁忙，请稍后重试')
  try:
   kept=_kept_row(conn,params)
   if kept:
    conn.commit()
    if _matches(kept,data.value,data.device_type):
     return {'id':kept.id,'status':'exists','detail':'同键同值，返回保留编号'}
    raise HTTPException(409,'同一设备同一采集时刻已存在不同读数，已确认的记录不可覆盖')
   try:
    new_id=conn.execute(text('INSERT INTO telemetry(sensor_id,recorded_at,device_type,value) VALUES (:s,:r,:t,:v)'),{**params,'t':data.device_type,'v':data.value}).lastrowid
    conn.commit()
    return {'id':new_id,'status':'accepted','detail':'已入库'}
   except IntegrityError:
    conn.rollback()  # 唯一约束已启用：并发插入捷足先登，回读保留记录
    kept=_kept_row(conn,params)
    conn.commit()
    if kept and _matches(kept,data.value,data.device_type):
     return {'id':kept.id,'status':'exists','detail':'同键同值，返回保留编号'}
    raise HTTPException(409,'同一设备同一采集时刻已存在不同读数，已确认的记录不可覆盖')
  finally:
   conn.rollback()
   conn.execute(text('SELECT RELEASE_LOCK(:n)'),{'n':name})
   conn.commit()
def get_reading(item_id):
 """按编号查询；已合并的旧编号解析到保留读数。"""
 with Session() as s:
  row=s.get(Telemetry,item_id)
  if row:return {**record(row),'merged':False}
  alias=s.query(TelemetryAlias).filter_by(old_id=item_id).first()
  if not alias:raise HTTPException(404,'未找到遥测记录')
  kept=s.get(Telemetry,alias.retained_id)
  if not kept:raise HTTPException(409,'保留记录缺失，请复查清理结果')
  return {**record(kept),'merged':True,'queried_id':item_id,'detail':'该编号为重复上报，读数以最早入库的保留记录为准'}
