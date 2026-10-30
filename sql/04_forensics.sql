-- FORENSICS A-G. Each result is materialised in dq.forensic_* for the notebook / report.

-- A. duplicate payments: effect on monthly recovery
create or replace table dq.forensic_a_dup_payments as
select strftime(event_at,'%Y-%m') month_ist, count(*) raw_rows, count(distinct payment_id) uniq_rows,
  sum(amount) filter (where payment_status='SUCCESS') raw_success_amt,
  sum(amount) filter (where payment_status='SUCCESS' and rn>1) dup_success_amt
from (select *, row_number() over (partition by payment_id order by _src_row) rn from stg.payments) group by 1 order by 1;

-- A2. payment_reference collisions: same reference on different accounts is NOT a duplicate (different amount/account)
create or replace table dq.forensic_a_ref_collisions as
select count(*) refs_total, count(*) filter (where n_pay>1) refs_reused, count(*) filter (where n_acct>1) refs_on_multiple_accounts
from (select payment_reference, count(distinct payment_id) n_pay, count(distinct account_id) n_acct from golden.fact_payment where payment_reference is not null group by 1);

-- B. attribution: naive "latest campaign on the account" (can be AFTER the payment) vs lookback-correct last touch
create or replace table dq.forensic_b_attribution as
with p as (select payment_id, account_id, event_ts_ist, recovered_amt from golden.fact_payment where is_success),
latest_any as (select account_id, arg_max(campaign_id, target_date) camp_latest, max(target_date) d_latest from golden.fact_target group by 1),
lt as (select p.payment_id, p.recovered_amt,
   (select arg_max(t.campaign_id, t.target_date) from golden.fact_target t where t.account_id=p.account_id and t.target_date <= cast(p.event_ts_ist as date) and t.target_date >= cast(p.event_ts_ist as date) - 30) camp_lastclick_30d,
   (select arg_min(t.campaign_id, t.target_date) from golden.fact_target t where t.account_id=p.account_id and t.target_date <= cast(p.event_ts_ist as date) and t.target_date >= cast(p.event_ts_ist as date) - 30) camp_first_30d
 from p)
select count(*) payments,
  count(*) filter (where l.camp_latest is not null) has_any_campaign_naive,
  count(*) filter (where l.d_latest > cast(p.event_ts_ist as date)) naive_campaign_starts_after_payment,
  count(*) filter (where lt.camp_lastclick_30d is not null) has_touch_in_30d_lookback,
  count(*) filter (where lt.camp_lastclick_30d is not null and l.camp_latest is distinct from lt.camp_lastclick_30d) naive_vs_lookback_disagree,
  count(*) filter (where lt.camp_lastclick_30d is distinct from lt.camp_first_30d) first_vs_last_disagree,
  sum(p.recovered_amt) total_amt, sum(p.recovered_amt) filter (where lt.camp_lastclick_30d is null) amt_no_touch_30d
from p join lt using (payment_id) left join latest_any l using (account_id);

-- C. timezone: effect on month / hour classification and RBI-style calling window (08:00-19:00 local)
create or replace table dq.forensic_c_timezone as
select tz, count(*) calls,
  avg((strftime(event_ts_ist,'%Y-%m')<>strftime(event_at_src,'%Y-%m'))::int) share_month_changed,
  avg((hour(event_ts_ist)<>hour(event_at_src))::int) share_hour_changed,
  avg((hour(event_at_src) between 8 and 18)::int) share_in_window_as_stamped,
  avg((hour(event_ts_ist) between 8 and 18)::int) share_in_window_ist
from clean.calls group by 1;

-- D. vendor / disposition mapping
create or replace table dq.forensic_d_dispo_version as
select strftime(event_ts_ist,'%Y-%m') month_ist, disposition_version, count(*) n,
  avg((code_raw='PTP')::int) ptp_only_code, avg((is_ptp)::int) ptp_merged from clean.call_dispositions group by 1,2 order by 1,2;
create or replace table dq.forensic_d_vendor_status as
select v.vendor_name, v.vendor_status, count(*) calls, count(*) filter (where c.event_ts_ist >= timestamp '2026-07-01') calls_jul
from clean.calls c join clean.vendors v using (vendor_id) group by 1,2 order by 1,2;

-- E. agent identity
create or replace table dq.forensic_e_agent_identity as
select (select count(distinct agent_id) from stg.agents) agent_ids, (select count(distinct employee_code) from stg.agents) employee_codes,
  (select count(distinct agent_name) from stg.agents) distinct_names, (select count(*) from stg.agents) agent_rows,
  (select avg(c) from (select employee_code, count(distinct agent_id) c from stg.agents group by 1)) avg_agent_ids_per_employee_code,
  (select avg(c) from (select agent_id, count(distinct employee_code) c from stg.agents group by 1)) avg_codes_per_agent_id,
  (select avg(c) from (select agent_id, count(distinct vendor_id) c from stg.agents group by 1)) avg_vendors_per_agent_id,
  (select count(*) from golden.fact_contact where source_table='CALL' and agent_id is null) calls_without_agent;

-- F. portfolio mix of PAYING accounts and TARGETED accounts, by month
create or replace table dq.forensic_f_mix as
select 'paying' pop, month_ist, dpd_bucket, loan_type, sum(recovered_amt) rec, count(distinct p.account_id) accts
from golden.fact_payment p join golden.dim_account a using (account_id) where is_success group by 2,3,4
union all
select 'targeted', month_ist, dpd_bucket, loan_type, null, count(distinct t.account_id)
from golden.fact_target t join golden.dim_account a using (account_id) group by 2,3,4;

-- G. denominator: who leaves the population used for conversion?
create or replace table dq.forensic_g_denominator as
select t.month_ist, count(distinct t.account_id) targeted_accts,
  count(distinct t.account_id) filter (where t.status='CONTACTED') contacted_accts,
  count(distinct t.account_id) filter (where t.status in ('EXPIRED','SKIPPED')) dropped_accts,
  count(distinct p.account_id) payers_among_targeted,
  count(distinct p.account_id) filter (where t.status='CONTACTED') payers_among_contacted
from golden.fact_target t
left join (select distinct account_id, month_ist from golden.fact_payment where is_success) p on p.account_id=t.account_id and p.month_ist=t.month_ist
group by 1 order by 1;
create or replace table dq.forensic_g_status_effort as
select a.status_master, count(*) targets, count(*) filter (where t.status='CONTACTED') contacted
from golden.fact_target t join golden.dim_account a using (account_id) group by 1;
