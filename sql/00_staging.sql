-- Layer 1: STAGING. Raw CSVs loaded as-is + lineage columns. No business logic.
create schema if not exists stg;
create schema if not exists clean;
create schema if not exists reject;
create schema if not exists golden;
create schema if not exists metrics;
create schema if not exists dq;

create or replace macro load_raw(f) as table
  select * from read_csv_auto('${DATA_DIR}/' || f || '.csv', header=true, sample_size=-1);

create or replace table stg.accounts           as select row_number() over () as _src_row, * from load_raw('accounts');
create or replace table stg.agents             as select row_number() over () as _src_row, * from load_raw('agents');
create or replace table stg.agent_sessions     as select row_number() over () as _src_row, * from load_raw('agent_sessions');
create or replace table stg.borrowers          as select row_number() over () as _src_row, * from load_raw('borrowers');
create or replace table stg.calls              as select row_number() over () as _src_row, * from load_raw('calls');
create or replace table stg.call_attempts      as select row_number() over () as _src_row, * from load_raw('call_attempts');
create or replace table stg.call_dispositions  as select row_number() over () as _src_row, * from load_raw('call_dispositions');
create or replace table stg.campaigns          as select row_number() over () as _src_row, * from load_raw('campaigns');
create or replace table stg.complaints         as select row_number() over () as _src_row, * from load_raw('complaints');
create or replace table stg.daily_targeting    as select row_number() over () as _src_row, * from load_raw('daily_targeting');
create or replace table stg.field_visits       as select row_number() over () as _src_row, * from load_raw('field_visits');
create or replace table stg.payments           as select row_number() over () as _src_row, * from load_raw('payments');
create or replace table stg.promises_to_pay    as select row_number() over () as _src_row, * from load_raw('promises_to_pay');
create or replace table stg.sms_events         as select row_number() over () as _src_row, * from load_raw('sms_events');
create or replace table stg.whatsapp_events    as select row_number() over () as _src_row, * from load_raw('whatsapp_events');
create or replace table stg.vendor_telephony   as select row_number() over () as _src_row, * from load_raw('vendor_telephony');
create or replace table stg.account_status_history as select row_number() over () as _src_row, * from load_raw('account_status_history');
