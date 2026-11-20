"""gb-4102 遥测去重验证：旧重复未清完时同键上报 / 并发上报 / 清理中断恢复 / 核对后唯一约束 / 写探针回滚。

用法（需全新栈，先 docker compose down -v 再 up）：
  docker compose up -d --build
  docker compose exec -T backend python - < test-artifacts/gb-4102/dedup_verify.py > test-artifacts/gb-4102/dedup_report.json
进度写 stderr，JSON 报告写 stdout；全部通过退出码 0，否则 1。
"""
import json,sys,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text,bindparam
from sqlalchemy.exc import IntegrityError
from src.config.database import engine
API='http://localhost:8000'
PASSWORD='Trial2026!'
A={'sensor_id':777,'recorded_at':'2026-11-15T08:00:00','device_type':'pump','value':55.5}
B={'sensor_id':778,'recorded_at':'2026-11-16T09:30:00','device_type':'motor','value':77.7}
C={'sensor_id':779,'recorded_at':'2026-11-17T10:00:00','device_type':'valve','value':12.25}
D={'sensor_id':780,'recorded_at':'2026-11-18T11:00:00','device_type':'valve','value':3.75}
SCOPE=(777,778,779,780)
checks=[]
def check(name,ok,detail=''):
 checks.append({'check':name,'ok':bool(ok),'detail':str(detail)[:300]})
 print(('PASS' if ok else 'FAIL'),name,'-',str(detail)[:200],file=sys.stderr)
 return ok
def call(method,path,token,body=None,query=''):
 req=urllib.request.Request(API+path+query,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
 try:
  with urllib.request.urlopen(req) as r:return r.status,json.loads(r.read())
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
def login(email):
 st,body=call('POST','/auth/login','',{'email':email,'password':PASSWORD})
 if st!=200:print('FATAL login failed',email,st,body,file=sys.stderr);sys.exit(2)
 return body['token']
def insert_direct(reading):
 with engine.connect() as conn:
  rid=conn.execute(text('INSERT INTO telemetry(sensor_id,recorded_at,device_type,value) VALUES (:sensor_id,:recorded_at,:device_type,:value)'),reading).lastrowid
  conn.commit();return rid
op=login('operator@index.local');adm=login('admin@index.local');vw=login('viewer@index.local')
st,s=call('GET','/telemetry/dedup/status',op)
if st!=200 or s.get('unique_constraint'):
 print('FATAL 需要未启用唯一约束的全新栈：docker compose down -v 后重跑',st,s,file=sys.stderr);sys.exit(2)
with engine.connect() as conn:  # 清理本脚本测试范围，允许失败重跑
 conn.execute(text('DELETE FROM telemetry WHERE sensor_id IN :ids').bindparams(bindparam('ids',expanding=True)),{'ids':SCOPE})
 conn.execute(text('DELETE FROM telemetry_aliases WHERE sensor_id IN :ids').bindparams(bindparam('ids',expanding=True)),{'ids':SCOPE})
 conn.commit()
# ---- 准备：模拟设备重发留下的历史重复（直接落库，绕过上报接口）----
a_ids=[insert_direct(A) for _ in range(3)]
b_ids=[insert_direct(B) for _ in range(2)]
st,s=call('GET','/telemetry/dedup/status',op)
check('准备：历史重复已存在',st==200 and s['duplicate_groups']>=2 and not s['unique_constraint'],s)
# ---- 阶段1：旧重复还没清完就同键上报 ----
st,r=call('POST','/telemetry/report',op,A)
check('未清完时同键同值返回最早保留编号',st==200 and r['status']=='exists' and r['id']==a_ids[0],r)
st,r=call('POST','/telemetry/report',op,{**A,'value':56.6})
check('未清完时同键异值报409',st==409,f'{st} {r}')
st,r=call('POST','/telemetry/report',op,B)
check('第二组重复同键同值返回保留编号',st==200 and r['status']=='exists' and r['id']==b_ids[0],r)
st,r=call('GET',f"/telemetry/{a_ids[1]}",vw)
check('清理前旧编号仍是原始行',st==200 and r.get('merged')==False and r['id']==a_ids[1],r)
with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:call('POST','/telemetry/report',op,D),range(8)))
ids={r['id'] for _,r in results};accepted=sum(1 for _,r in results if r['status']=='accepted')
check('清理期间并发上报同键同值：同一编号且仅一次accepted',all(s==200 for s,_ in results) and len(ids)==1 and accepted==1 and 200 in [s for s,_ in results],results)
# ---- 阶段2：清理中断后恢复 ----
with engine.connect() as conn:  # 模拟清理中断：别名+删除进行到一半回滚
 ids=[row[0] for row in conn.execute(text('SELECT id FROM telemetry WHERE sensor_id=777 AND recorded_at=:r ORDER BY id FOR UPDATE'),{'r':A['recorded_at']})]
 conn.execute(text('INSERT INTO telemetry_aliases(old_id,retained_id,sensor_id,recorded_at) VALUES (:o,:k,777,:r)'),[{'o':o,'k':ids[0],'r':A['recorded_at']} for o in ids[1:]])
 conn.execute(text('DELETE FROM telemetry WHERE id IN (:x,:y)'),{'x':ids[1],'y':ids[2]})
 conn.rollback()
st,r=call('GET',f"/telemetry/{a_ids[1]}",op)
check('中断回滚后旧编号仍指向原始行',st==200 and r.get('merged')==False,r)
st,s=call('GET','/telemetry/dedup/status',op)
check('中断回滚后无残留别名',st==200 and s['aliases']==0,s)
st,r=call('POST','/telemetry/dedup/run',op,query='?limit=1')
check('恢复后首轮清理1组',st==200 and r['cleaned_keys']==1,r)
st,r=call('GET',f"/telemetry/{a_ids[1]}",vw)
check('旧编号a2查到保留读数',st==200 and r.get('merged')==True and r['id']==a_ids[0] and r.get('queried_id')==a_ids[1],r)
st,r=call('GET',f"/telemetry/{a_ids[2]}",vw)
check('旧编号a3查到保留读数',st==200 and r.get('merged')==True and r['id']==a_ids[0],r)
st,r=call('POST','/telemetry/report',op,B)
check('B组仍未清完时同键同值返回保留编号',st==200 and r['status']=='exists' and r['id']==b_ids[0],r)
st,r=call('POST','/telemetry/report',op,{**B,'value':88.8})
check('B组仍未清完时异值报409',st==409,st)
st,r=call('POST','/telemetry/dedup/run',op)
check('第二轮清完剩余重复',st==200 and r['duplicate_groups']==0,r)
st,r=call('GET',f"/telemetry/{b_ids[1]}",vw)
check('恢复后旧编号b2查到保留读数',st==200 and r.get('merged')==True and r['id']==b_ids[0],r)
# ---- 阶段3：核对无遗漏后启用库级唯一约束 ----
st,s=call('GET','/telemetry/dedup/status',op)
check('核对无遗漏（0重复组/0悬空别名/3别名）',st==200 and s['duplicate_groups']==0 and s['orphan_aliases']==0 and s['aliases']==3,s)
st,r=call('POST','/telemetry/dedup/finalize',op)
check('operator启用约束被403',st==403,st)
st,r=call('POST','/telemetry/dedup/finalize',adm)
check('admin核对后启用唯一约束',st==200 and r['unique_constraint']==True,r)
try:
 with engine.connect() as conn:
  conn.execute(text("INSERT INTO telemetry(sensor_id,recorded_at,device_type,value) VALUES (777,:r,'pump',55.5)"),{'r':A['recorded_at']})
  conn.commit()
 blocked=False
except IntegrityError:blocked=True
check('库级唯一约束拒绝直接重复插入',blocked)
# ---- 阶段4：约束启用后上报行为不变 ----
st,r=call('POST','/telemetry/report',op,A)
check('约束后同键同值仍返回保留编号',st==200 and r['status']=='exists' and r['id']==a_ids[0],r)
st,r=call('POST','/telemetry/report',op,{**A,'value':56.6})
check('约束后同键异值仍报409',st==409,st)
st,r=call('POST','/telemetry/report',op,C)
check('新键正常入库',st==200 and r['status']=='accepted',r)
c_id=r.get('id')
st,r=call('GET',f'/telemetry/{c_id}',vw)
check('新编号可查',st==200 and r.get('merged')==False,r)
st,r=call('GET',f"/telemetry/{a_ids[0]}",vw)
check('已确认读数未被覆盖',st==200 and abs(r['value']-55.5)<1e-6 and r['device_type']=='pump',r)
st,r=call('POST','/telemetry/report',vw,C)
check('viewer上报被403',st==403,st)
st,r=call('GET','/telemetry/999999999',vw)
check('不存在编号404',st==404,st)
# ---- 阶段5：试验写探针照常回滚 ----
from src.services.index_algorithm import _write_probe
st,s=call('GET','/telemetry/dedup/status',op);before=s['rows']
with engine.connect() as conn:ms=_write_probe(conn)
st,s=call('GET','/telemetry/dedup/status',op)
check('写探针在唯一约束下执行且回滚',st==200 and s['rows']==before,f'probe={ms}ms rows {before}->{s["rows"]}')
with engine.connect() as conn:left=conn.execute(text('SELECT COUNT(*) FROM telemetry WHERE sensor_id=999')).scalar()
check('写探针无残留行',left==0,left)
passed=sum(1 for c in checks if c['ok']);failed=len(checks)-passed
json.dump({'batch':'gb-4102','passed':passed,'failed':failed,'checks':checks},sys.stdout,ensure_ascii=False,indent=2)
print(f'\n{passed} passed, {failed} failed',file=sys.stderr)
sys.exit(1 if failed else 0)
