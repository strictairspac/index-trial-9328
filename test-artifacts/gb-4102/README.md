# gb-4102 遥测去重验证

对应需求：设备重发导致同一 `sensor_id + recorded_at` 多条遥测；提供上报与按旧编号查询接口，清理可中断恢复，核对无遗漏后启用库级唯一约束。

## 运行

```sh
docker compose down -v --remove-orphans   # 需要全新栈：finalize 后无法再造重复数据
docker compose up -d --build
docker compose exec -T backend python - < test-artifacts/gb-4102/dedup_verify.py > test-artifacts/gb-4102/dedup_report.json
echo $?   # 0 = 全部通过
```

进度打在 stderr，JSON 报告写入 `dedup_report.json`。

## 覆盖点

| 阶段 | 验证内容 |
|---|---|
| 准备 | 直接落库构造 777×3、778×2 历史重复（模拟设备重发） |
| 1 | **旧重复未清完就同键上报**：同值返回最早保留编号，异值 409；8 线程并发上报新键 → 同一编号、仅 1 次 accepted |
| 2 | 清理中断（别名+删除事务回滚）后旧编号仍指向原始行；恢复运行后旧编号经别名查到保留读数；未清完的 B 组同键上报仍幂等/冲突 |
| 3 | 核对 0 重复组、0 悬空别名；operator 启用约束被 403；admin finalize 启用 `uniq_sensor_recorded`；直接重复插入被约束拒绝 |
| 4 | 约束后同键同值仍返回保留编号、异值仍 409、新键正常入库；已确认读数未被覆盖；viewer 上报 403；不存在编号 404 |
| 5 | 20 行写探针在唯一约束下执行且 ROLLBACK，telemetry 行数不变、无 sensor 999 残留 |

测试数据为 sensor 777–780，不影响种子负载（17/36/59）与试验探针（999）；验证结束后保留 a1/b1/c1/d1 及 3 条别名，便于人工复查旧编号查询。
