# Schema v2 — 遥测去重与库级唯一约束

背景：设备重发后，同一 `sensor_id + recorded_at` 在 telemetry 中出现多行。

1. `telemetry_aliases(old_id UNIQUE, retained_id, sensor_id, recorded_at, created_at)` 由 SQLAlchemy metadata 在启动时随 create_all 建立。清理保留每键最早入库行，其余旧编号先登记别名再删除，别名与删除同事务；清理可中断，重跑 `POST /telemetry/dedup/run` 即恢复，旧编号全程可查。
2. 清理期间上报 `POST /telemetry/report` 走键级 `GET_LOCK` 互斥：同键同值返回保留编号（幂等），异值 409，已确认读数不被覆盖。唯一约束启用后由 IntegrityError 回读兜底，行为不变。
3. `POST /telemetry/dedup/finalize`（admin）在 `duplicate_groups=0` 且 `orphan_aliases=0` 核对通过后执行：
   `ALTER TABLE telemetry ADD UNIQUE INDEX uniq_sensor_recorded (sensor_id, recorded_at)`。
   约束由运维步骤启用、不写入 metadata，避免存量重复导致启动建表失败。
4. 试验写探针改为 20 个不同采集时刻（sensor_id=999），仍真实 INSERT 后 ROLLBACK，与唯一约束兼容；自增序列空洞属正常。
5. 清理与试验共用 `index_trial_serial` 命名锁互斥，避免清理改动影响执行计划对比与结果 SHA-256 校验。
