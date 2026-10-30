-- Layer 2: CLEAN. Dedup, type/timezone normalisation. Every dropped row lands in reject.* with a reason.
-- Timezone convention: naive event_at is wall-clock in the row's own tz (calls.timezone), else the
-- provider's tz (vendor_telephony.timezone), else Asia/Kolkata (business tz). Normalised to IST.
-- Source-clock observation window: [2026-01-01, 2026-08-09).

create or replace macro to_ist(ts, tz) as
  timezone('Asia/Kolkata', timezone(coalesce(tz,'Asia/Kolkata'), ts));

-- ---------- vendors ----------
create or replace table clean.vendors as
select vendor_id, vendor_name, vendor_account_id, timezone as vendor_tz, status as vendor_status, schema_version
from stg.vendor_telephony;

-- ---------- payments ----------
create or replace table reject.payments as
select *, 'DUPLICATE_PAYMENT_ID' as reject_reason from (
  select *, row_number() over (partition by payment_id order by _src_row) rn from stg.payments) where rn>1;

create or replace table clean.payments as
select p.payment_id, p.account_id, p.event_at as event_at_src, p.payment_reference, p.amount,
       p.payment_status, p.payment_method, p.provider_id,
       to_ist(p.event_at, v.vendor_tz) as event_ts_ist,
       (p.payment_reference is null) as ref_missing,
       (p.payment_status='SUCCESS')  as is_success,
       (p.payment_status='REVERSED') as is_reversed,
       (p.payment_status='PENDING')  as is_pending
from (select * from stg.payments qualify row_number() over (partition by payment_id order by _src_row)=1) p
left join clean.vendors v on v.vendor_id=p.provider_id;

-- ---------- calls ----------
create or replace table reject.calls as
select *, 'DUPLICATE_CALL_ID' as reject_reason from (
  select *, row_number() over (partition by call_id order by _src_row) rn from stg.calls) where rn>1
union all by name
select *, 'OUT_OF_OBSERVATION_WINDOW' as reject_reason from (
  select * from stg.calls qualify row_number() over (partition by call_id order by _src_row)=1)
  where event_at < timestamp '2026-01-01' or event_at >= timestamp '2026-08-09';

create or replace table clean.calls as
select c.call_id, c.account_id, c.event_at as event_at_src, c.agent_id, c.campaign_id, c.direction, c.vendor_id,
       c.call_status, c.duration_sec, c.timezone as tz,
       to_ist(c.event_at, c.timezone) as event_ts_ist,
       (c.agent_id is null) as agent_missing,
       (c.call_status='ANSWERED' and c.duration_sec>=15) as is_connected,
       (c.call_status in ('FAILED','NO_ANSWER','BUSY') and c.duration_sec>=30) as status_duration_conflict
from (select * from stg.calls qualify row_number() over (partition by call_id order by _src_row)=1) c
where c.event_at >= timestamp '2026-01-01' and c.event_at < timestamp '2026-08-09';

-- ---------- call_attempts ----------
create or replace table clean.call_attempts as
select a.attempt_id, a.account_id, a.event_at as event_at_src, a.call_id, a.agent_id, a.attempt_no,
       coalesce(a.vendor_id,'UNKNOWN') as vendor_id, a.attempt_status,
       to_ist(a.event_at, v.vendor_tz) as event_ts_ist,
       (a.vendor_id is null) as vendor_missing,
       (a.attempt_status='CONNECTED') as is_connected
from stg.call_attempts a left join clean.vendors v using (vendor_id);

-- ---------- call_dispositions (legacy alias PROMISE_TO_PAY == PTP) ----------
create or replace table clean.call_dispositions as
select disposition_id, account_id, call_id, agent_id, event_at as event_ts_ist,  -- no tz column: assumed IST
       disposition_code as code_raw, disposition_version,
       case disposition_code when 'PROMISE_TO_PAY' then 'PTP' else disposition_code end as code,
       (disposition_code not in ('NO_CONTACT','WRONG_NUMBER')) as is_rpc,
       (disposition_code in ('PTP','PROMISE_TO_PAY')) as is_ptp
from stg.call_dispositions;

-- ---------- whatsapp / sms ----------
create or replace table reject.whatsapp_events as
select *, 'DUPLICATE_EVENT_ID' as reject_reason from (
  select *, row_number() over (partition by whatsapp_event_id order by _src_row) rn from stg.whatsapp_events) where rn>1;
create or replace table clean.whatsapp_events as
select e.whatsapp_event_id as event_id, e.account_id, e.message_id, e.event_type, e.template_code, e.provider_id,
       to_ist(e.event_at, v.vendor_tz) as event_ts_ist
from (select * from stg.whatsapp_events qualify row_number() over (partition by whatsapp_event_id order by _src_row)=1) e
left join clean.vendors v on v.vendor_id=e.provider_id;

create or replace table clean.sms_events as
select e.sms_event_id as event_id, e.account_id, e.message_id, e.event_type, e.template_code, e.provider_id,
       to_ist(e.event_at, v.vendor_tz) as event_ts_ist
from stg.sms_events e left join clean.vendors v on v.vendor_id=e.provider_id;

-- ---------- field visits / PTP / complaints / targeting / status history ----------
create or replace table clean.field_visits as
select visit_id, account_id, agent_id, event_at as event_ts_ist, visit_type, outcome, scheduled_at, (scheduled_at is null) as sched_missing
from stg.field_visits;

-- PTP: OPEN promises already past due (+3d grace) are unresolved, not "open".
create or replace table clean.promises_to_pay as
select ptp_id, account_id, agent_id, event_at as event_ts_ist, promised_amount, promised_date, status as status_raw, source,
  case when status='OPEN' and promised_date + interval 3 day < timestamp '2026-08-09' then 'STALE_OPEN' else status end as status,
  (promised_date + interval 3 day < timestamp '2026-08-09') as is_matured
from stg.promises_to_pay;

create or replace table clean.complaints as select * exclude(_src_row) from stg.complaints;
create or replace table clean.daily_targeting as select * exclude(_src_row) from stg.daily_targeting;

-- status history: recorded_at < event_at is impossible (record cannot precede the event)
create or replace table clean.account_status_history as
select *, (recorded_at < event_at) as recorded_before_event from stg.account_status_history;

-- ---------- borrowers: one row per borrower_id (latest sane version) ----------
create or replace table clean.borrowers as
select borrower_id, name, cast(cast(phone as bigint) as varchar) as phone, email, city, state, created_at, updated_at
from (select *, row_number() over (partition by borrower_id
        order by (updated_at >= created_at) desc, updated_at desc, _src_row) rn from stg.borrowers
      qualify true) where rn=1;
create or replace table reject.borrowers as
select *, 'SUPERSEDED_BORROWER_VERSION' as reject_reason from (
  select *, row_number() over (partition by borrower_id
        order by (updated_at >= created_at) desc, updated_at desc, _src_row) rn from stg.borrowers) where rn>1;

-- ---------- agents: canonical key = agent_id (only id used by facts) ----------
create or replace table clean.agents as
select agent_id, employee_code, agent_name, vendor_id, team, status, joined_at, updated_at
from (select *, row_number() over (partition by agent_id order by updated_at desc, _src_row) rn from stg.agents) where rn=1;
create or replace table reject.agents as
select *, 'SUPERSEDED_AGENT_VERSION' as reject_reason from (
  select *, row_number() over (partition by agent_id order by updated_at desc, _src_row) rn from stg.agents) where rn>1;

create or replace table clean.accounts as select * exclude(_src_row) from stg.accounts;
create or replace table clean.campaigns as select * exclude(_src_row) from stg.campaigns;
create or replace table clean.agent_sessions as select * exclude(_src_row) from stg.agent_sessions;
