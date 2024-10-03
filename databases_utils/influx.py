__version__='1.1.2'
__author__=['Ioannis Tsakmakis']
__date_created__='2023-11-16'
__last_updated__='2024-10-03'

from influxdb_client import InfluxDBClient, Bucket, BucketRetentionRules
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
from typing import Union
from aws_utils import SecretsManager
from dotenv import load_dotenv
from decorators import influxdb_error_handler
from logger import alchemy
import os

# Load variables from the .env file
load_dotenv()

# Access database configuration info
influx_conf = SecretsManager().get_secret(secret_name=os.getenv('db_timeseries'))

class InfluxConnector():

    def __init__(self, bucket_name: str, influx_conf: dict):
        self.client = InfluxDBClient(url=influx_conf['url'], token=influx_conf['token'], org=influx_conf['org'])
        if not self.client.ping():
            alchemy.error("Connection to InfluxDB failed.")
            raise ConnectionError("Connection to InfluxDB failed.")
        self.bucket_name = bucket_name
        self.org = influx_conf['org']

class DataManagement(InfluxConnector):

    @influxdb_error_handler
    def write_point(self, measurement:str, sensor_id:int, unit:str, data:dict):
        write_api = self.client.write_api(write_options=SYNCHRONOUS)
        records =[]
        for i in range(0,len(data['date_time'])):
            point = {
                'measurement': measurement,
                'tags': {'sensor_id': sensor_id},
                'fields': {unit: float(data['values'][i]) if data['values'][i] is not None else data['values'][i]},
                'time': data['date_time'][i].strftime('%Y-%m-%dT%H:%M:%S')
                }
            records.append(point)
        write_api.write(bucket=self.bucket_name, org=self.org, record=records)
        alchemy.info(f"message: Data successfully persisted to the bucket: {self.bucket_name}, measurement: {measurement}")        

    @influxdb_error_handler
    def delete_rows(self, measurement:str, tag:str, start:Union[str,datetime], stop:Union[str,datetime] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")):
        # Define api methods
        delete_api = self.client.delete_api()
        # Delete Points
        delete_api.delete(start,stop,predicate = f'_measurement = "{measurement}" and sensor_id = "{tag}"',bucket = self.bucket_name,org = self.org)
        alchemy.info(f"message: Data successfully deleted from the bucket: {self.bucket_name}, measurement: {measurement}, sensor_id: {tag}, from: {start} to: {stop}")

    @influxdb_error_handler
    def query_data(self,measurement: str,sensor_id: int,unit: str,start: Union[str, datetime],stop: Union[str, datetime] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")):
        query_api = self.client.query_api()
        data_frame = query_api.query_data_frame(f'''from(bucket:"{self.bucket_name}") 
                                                    |> range(start: {start.strftime("%Y-%m-%dT%H:%M:%SZ")}, stop: {stop.strftime("%Y-%m-%dT%H:%M:%SZ")}) 
                                                    |> filter(fn: (r) => r["_measurement"] == "{measurement}" and r["sensor_id"] == "{str(sensor_id)}")
                                                    |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                                                    |> keep(columns: ["_time","sensor_id", "{unit}"])''')
        alchemy.info(f"message: Data from bucket: {self.bucket_name}, measurement: {measurement}, sensor_id: {sensor_id} between: {start} and {stop} retrived successfully")
        return data_frame

class BucketConfiguration(InfluxConnector):
    
    @influxdb_error_handler
    def list_buckets(self):
        buckets_api = self.client.buckets_api()
        buckets = buckets_api.find_buckets().buckets
        print("\n".join([f" ---\n ID: {bucket.id}\n Name: {bucket.name}\n Retention: {bucket.retention_rules}"
                for bucket in buckets]))
        return buckets
    
    @influxdb_error_handler
    def update_bucket(self, type='expire', data_duration=0, shard_group_duration=630720000, description='Update to a 20 years shard group duration'):
        buckets_api=self.client.buckets_api()
        bucket_info=buckets_api.find_bucket_by_name(self.bucket_name)
        bucket_id="\n".join([f"{bucket_info.id}"])
        org_id ="\n".join([f"{bucket_info.org_id}"])
        bucket_update = Bucket(
                                description = description,
                                id = bucket_id,
                                name = self.bucket_name,
                                org_id = org_id,
                                retention_rules = [BucketRetentionRules(every_seconds = data_duration,
                                                                        shard_group_duration_seconds = shard_group_duration,
                                                                        type = type)])
        buckets_api.update_bucket(bucket = bucket_update)
        alchemy.info(f"message: bucket: {self.bucket_name} updated succefully - {buckets_api.find_bucket_by_name(self.bucket_name)}")
        return print(buckets_api.find_bucket_by_name(self.bucket_name))
