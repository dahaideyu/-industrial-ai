


 

SELECT device_id, device_status, point_uid, point_id, value_type, point_value, point_time, upload_cycle, south_driver_name, "time", load_time, raw_json
FROM device_alarm_info;

SELECT device_id, device_status, point_uid, point_id, value_type, point_value, 
       point_time, upload_cycle, south_driver_name, "time", load_time, raw_json
FROM device_alarm_info
ORDER BY "time" DESC 
LIMIT 1;

SELECT device_id, device_status, point_uid, point_id, point_value, point_time, upload_cycle, south_driver_name, "time", load_time, raw_json
FROM public.device_energy_info;