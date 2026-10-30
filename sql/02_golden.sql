-- Layer 3: GOLDEN. Trusted, joinable entities. Join key = account_id (the only key that survives
-- cross-table reconciliation; borrower_id/call_id on event rows do not agree with the account master).

create or replace table golden.dim_account as
select a.account_id, a.borrower_id, a.loan_type, a.principal_amount, a.outstanding_amount, a.dpd, a.risk_segment,
  a.status as status_master, a.opened_at,
  case when a.dpd=0 then '0 current' when a.dpd<30 then '1-29' when a.dpd<60 then '30-59' when a.dpd<90 then '60-89' else '90+' end as dpd_bucket,
  case when a.outstanding_amount<150000 then '<1.5L' when a.outstanding_amount<350000 then '1.5-3.5L' when a.outstanding_amount<550000 then '3.5-5.5L' else '5.5L+' end as ticket_band,
  coalesce(b.city,'UNKNOWN') as city, coalesce(b.state,'UNKNOWN') as state,
  (a.borrower_id is null) as borrower_missing,
  (a.borrower_id is not null and b.borrower_id is null) as borrower_orphan
from clean.accounts a left join clean.borrowers b using (borrower_id);

create or replace table golden.dim_vendor as select * from clean.vendors;

create or replace table golden.dim_agent as
select a.*, date_diff('day', a.joined_at, timestamp '2026-08-09') as tenure_days,
  case when date_diff('day', a.joined_at, timestamp '2026-08-09')<365 then '<1y'
       when date_diff('day', a.joined_at, timestamp '2026-08-09')<730 then '1-2y' else '2y+' end as tenure_band,
  (select count(distinct employee_code) from stg.agents s where s.agent_id=a.agent_id) as n_employee_codes_seen
from clean.agents a;

create or replace table golden.dim_campaign as
select c.*, (c.campaign_name like '30DPD%' and c.target_definition<>'DPD>=30') as name_def_conflict
from clean.campaigns c;

create or replace table golden.fact_payment as
select p.*, strftime(p.event_ts_ist,'%Y-%m') as month_ist, cast(p.event_ts_ist as date) as date_ist,
  strftime(p.event_at_src,'%Y-%m') as month_src,
  case when p.is_success then p.amount else 0 end as recovered_amt
from clean.payments p;

-- unified contact ledger (one row per outreach event). 'engaged' = a human/borrower-side response.
create or replace table golden.fact_contact as
select 'CALL_'||call_id as contact_id, account_id, 'VOICE' as channel, 'CALL' as source_table, event_ts_ist,
       agent_id, campaign_id, vendor_id, call_status as outcome, is_connected as is_reached, is_connected as is_engaged
from clean.calls
union all
select 'ATT_'||attempt_id, account_id, 'VOICE', 'CALL_ATTEMPT', event_ts_ist, agent_id, null, vendor_id, attempt_status, is_connected, is_connected
from clean.call_attempts
union all
select 'WA_'||event_id, account_id, 'WHATSAPP', 'WHATSAPP', event_ts_ist, null, null, provider_id, event_type,
       event_type in ('DELIVERED','READ','REPLIED','PAYMENT_CLICK'), event_type in ('REPLIED','PAYMENT_CLICK')
from clean.whatsapp_events
union all
select 'SMS_'||event_id, account_id, 'SMS', 'SMS', event_ts_ist, null, null, provider_id, event_type,
       event_type in ('DELIVERED','CLICKED'), event_type='CLICKED'
from clean.sms_events
union all
select 'FLD_'||visit_id, account_id, 'FIELD', 'FIELD', event_ts_ist, agent_id, null, null, outcome,
       outcome in ('CONTACTED','PTP','PAID','REFUSED'), outcome in ('PTP','PAID')
from clean.field_visits;

create or replace table golden.fact_ptp as
select t.*, strftime(t.event_ts_ist,'%Y-%m') as month_ist,
  coalesce((select sum(p.amount) from clean.payments p where p.account_id=t.account_id and p.is_success
     and p.event_ts_ist between t.event_ts_ist and t.promised_date + interval 3 day),0) as cash_in_window
from clean.promises_to_pay t;

create or replace table golden.fact_target as
select t.*, strftime(t.target_date,'%Y-%m') as month_ist, c.strategy_version, c.target_definition, c.campaign_name,
  (t.target_date between cast(c.start_at as date) and cast(c.end_at as date)) as in_campaign_window
from clean.daily_targeting t left join clean.campaigns c using (campaign_id);

-- account x month panel (months Jan..Aug; Aug is partial)
create or replace table golden.account_month as
with months as (select strftime(m,'%Y-%m') as month_ist from generate_series(timestamp '2026-01-01', timestamp '2026-08-01', interval 1 month) t(m)),
pay as (select account_id, month_ist, sum(recovered_amt) rec, count(*) filter (where is_success) n_pay from golden.fact_payment group by 1,2),
con as (select account_id, strftime(event_ts_ist,'%Y-%m') month_ist,
  count(*) filter (where channel='VOICE' and source_table='CALL') calls,
  count(*) filter (where source_table='CALL_ATTEMPT') attempts,
  count(*) filter (where channel='WHATSAPP') wa, count(*) filter (where channel='SMS') sms, count(*) filter (where channel='FIELD') visits
  from golden.fact_contact group by 1,2)
select a.account_id, m.month_ist, a.dpd_bucket, a.loan_type, a.risk_segment, a.outstanding_amount,
  coalesce(pay.rec,0) rec, coalesce(pay.n_pay,0) n_pay,
  coalesce(con.calls,0) calls, coalesce(con.attempts,0) attempts, coalesce(con.wa,0) wa, coalesce(con.sms,0) sms, coalesce(con.visits,0) visits
from golden.dim_account a cross join months m
left join pay on pay.account_id=a.account_id and pay.month_ist=m.month_ist
left join con on con.account_id=a.account_id and con.month_ist=m.month_ist;

-- DQ rule log: Raw -> Rejected/Corrected -> Golden
create or replace table dq.rule_log as
select 'payments' tbl, 'DUPLICATE_PAYMENT_ID' rule, 'reject' action, (select count(*) from stg.payments) rows_raw,
  (select count(*) from reject.payments) rows_affected, (select sum(amount) from reject.payments where payment_status='SUCCESS') amt_impact
union all select 'calls','DUPLICATE_CALL_ID','reject',(select count(*) from stg.calls),(select count(*) from reject.calls where reject_reason='DUPLICATE_CALL_ID'),null
union all select 'calls','OUT_OF_OBSERVATION_WINDOW','reject',(select count(*) from stg.calls),(select count(*) from reject.calls where reject_reason='OUT_OF_OBSERVATION_WINDOW'),null
union all select 'calls','AGENT_ID_MISSING','flag',(select count(*) from clean.calls),(select count(*) from clean.calls where agent_missing),null
union all select 'calls','STATUS_DURATION_CONFLICT (failed/busy/no-answer with >=30s)','flag',(select count(*) from clean.calls),(select count(*) from clean.calls where status_duration_conflict),null
union all select 'call_attempts','VENDOR_ID_MISSING','flag',(select count(*) from clean.call_attempts),(select count(*) from clean.call_attempts where vendor_missing),null
union all select 'whatsapp_events','DUPLICATE_EVENT_ID','reject',(select count(*) from stg.whatsapp_events),(select count(*) from reject.whatsapp_events),null
union all select 'borrowers','SUPERSEDED_BORROWER_VERSION','reject',(select count(*) from stg.borrowers),(select count(*) from reject.borrowers),null
union all select 'agents','SUPERSEDED_AGENT_VERSION','reject',(select count(*) from stg.agents),(select count(*) from reject.agents),null
union all select 'accounts','BORROWER_ID_NULL','flag',(select count(*) from clean.accounts),(select count(*) from golden.dim_account where borrower_missing),null
union all select 'accounts','BORROWER_ID_NOT_IN_BORROWERS','flag',(select count(*) from clean.accounts),(select count(*) from golden.dim_account where borrower_orphan),null
union all select 'payments','PAYMENT_REFERENCE_MISSING','flag',(select count(*) from clean.payments),(select count(*) from clean.payments where ref_missing),null
union all select 'payments','STATUS_NOT_SUCCESS (excluded from recovery)','exclude',(select count(*) from clean.payments),(select count(*) from clean.payments where not is_success),(select sum(amount) from clean.payments where not is_success)
union all select 'promises_to_pay','OPEN_PAST_DUE -> STALE_OPEN','correct',(select count(*) from clean.promises_to_pay),(select count(*) from clean.promises_to_pay where status='STALE_OPEN'),null
union all select 'call_dispositions','CODE_ALIAS PROMISE_TO_PAY->PTP','correct',(select count(*) from clean.call_dispositions),(select count(*) from clean.call_dispositions where code_raw='PROMISE_TO_PAY'),null
union all select 'account_status_history','RECORDED_BEFORE_EVENT','flag',(select count(*) from clean.account_status_history),(select count(*) from clean.account_status_history where recorded_before_event),null
union all select 'borrowers','UPDATED_BEFORE_CREATED','flag',(select count(*) from stg.borrowers),(select count(*) from stg.borrowers where updated_at<created_at),null;
