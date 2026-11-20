from sqlalchemy import Column,Integer,String,Float,DateTime,func
from src.config.database import Base
class Telemetry(Base):
 __tablename__='telemetry'
 id=Column(Integer,primary_key=True)
 sensor_id=Column(Integer,nullable=False)
 recorded_at=Column(String(30),nullable=False)
 device_type=Column(String(40),nullable=False)
 value=Column(Float,nullable=False)
class TelemetryAlias(Base):
 __tablename__='telemetry_aliases'
 id=Column(Integer,primary_key=True)
 old_id=Column(Integer,unique=True,nullable=False)
 retained_id=Column(Integer,nullable=False)
 sensor_id=Column(Integer,nullable=False)
 recorded_at=Column(String(30),nullable=False)
 created_at=Column(DateTime,server_default=func.now())
