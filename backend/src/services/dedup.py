"""可恢复的重复遥测清理：保留每键最早入库行，旧编号登记别名后删除；核对无遗漏再启用唯一约束。"""
from sqlalchemy import text,bindparam
from fastapi import HTTPException
from src.config.database import engine
LOCK='index_trial_serial'  # 与试验互斥，避免清理改动影响执行计划与结果校验
UNIQ='uniq_sensor_recorded'
def _dup_keys(conn,limit):
 return conn.execute(text('SELECT sensor_id,recorded_at FROM telemetry GROUP BY sensor_id,recorded_at HAVING COUNT(*)>1 ORDER BY MIN(id) LIMIT :n'),{'n':limit}).all()
def status():
 with engine.connect() as conn:
  groups=conn.execute(text('SELECT COUNT(*) FROM (SELECT 1 FROM telemetry GROUP BY sensor_id,recorded_at HAVING COUNT(*)>1) d')).scalar()
  aliases=conn.execute(text('SELECT COUNT(*) FROM telemetry_aliases')).scalar()
  orphans=conn.execute(text('SELECT COUNT(*) FROM telemetry_aliases a LEFT JOIN telemetry t ON t.id=a.retained_id WHERE t.id IS NULL')).scalar()
  unique=conn.execute(text("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='telemetry' AND index_name=:u"),{'u':UNIQ}).scalar()
  rows=conn.execute(text('SELECT COUNT(*) FROM telemetry')).scalar()
 return {'duplicate_groups':groups,'aliases':aliases,'orphan_aliases':orphans,'rows':rows,'unique_constraint':bool(unique)}
def run_pass(limit=200):
 """清理至多 limit 组重复。每组一个事务（先别名后删除），中断后重跑即可恢复，旧编号始终可查。"""
 cleaned=aliased=0
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,30)'),{'l':LOCK}).scalar()!=1:
   raise HTTPException(409,'试验或清理正在进行，请稍后重试')
  try:
   for sensor_id,recorded_at in _dup_keys(conn,limit):
    ids=[r[0] for r in conn.execute(text('SELECT id FROM telemetry WHERE sensor_id=:s AND recorded_at=:r ORDER BY id FOR UPDATE'),{'s':sensor_id,'r':recorded_at})]
    keep,drop=ids[0],ids[1:]
    if not drop:continue
    conn.execute(text('INSERT IGNORE INTO telemetry_aliases(old_id,retained_id,sensor_id,recorded_at) VALUES (:o,:k,:s,:r)'),[{'o':o,'k':keep,'s':sensor_id,'r':recorded_at} for o in drop])
    conn.execute(text('DELETE FROM telemetry WHERE id IN :ids').bindparams(bindparam('ids',expanding=True)),{'ids':drop})
    conn.commit()
    cleaned+=1;aliased+=len(drop)
  finally:
   conn.rollback()
   conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':LOCK});conn.commit()
 return {'cleaned_keys':cleaned,'aliased_rows':aliased,**status()}
def verify():
 """核对无遗漏：无重复组且无悬空别名，才允许启用唯一约束。"""
 st=status()
 if st['duplicate_groups'] or st['orphan_aliases']:
  raise HTTPException(409,f"核对未通过：剩余重复组 {st['duplicate_groups']}，悬空别名 {st['orphan_aliases']}")
 return st
def finalize():
 """核对通过后启用库级唯一约束；重复执行安全。"""
 verify()
 if status()['unique_constraint']:return status()
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,30)'),{'l':LOCK}).scalar()!=1:
   raise HTTPException(409,'试验或清理正在进行，请稍后重试')
  try:
   conn.execute(text(f'ALTER TABLE telemetry ADD UNIQUE INDEX {UNIQ} (sensor_id,recorded_at)'))
   conn.commit()
  finally:
   conn.rollback()
   conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':LOCK});conn.commit()
 return status()
