from src.services import workloads,candidates,experiments,telemetry,dedup
from src.services.audit import log
def save_workload(data,user,item_id=None):
 row=workloads.save(data,item_id);log(user.email,'workload.save',row['name']);return row
def save_candidate(data,user,item_id=None):
 row=candidates.save(data,item_id);log(user.email,'candidate.save',row['name']);return row
def start_experiment(data,user):
 row=experiments.create(data);log(user.email,'experiment.queue',row['name']);return row
def report_reading(data,user):
 result=telemetry.report(data);log(user.email,'telemetry.report',f"{data.sensor_id}@{data.recorded_at} {result['status']} #{result['id']}");return result
def run_dedup(limit,user):
 result=dedup.run_pass(limit);log(user.email,'telemetry.dedup.run',f"cleaned={result['cleaned_keys']} aliased={result['aliased_rows']}");return result
def finalize_dedup(user):
 result=dedup.finalize();log(user.email,'telemetry.dedup.finalize',f"unique={result['unique_constraint']}");return result
