-- Layer 4/5: FEATURE + METRICS. Every metric exists in a NAIVE form (how a legacy report would likely compute it)
-- and a GOLDEN form (our independent definition). Aug-2026 is a partial month (8 days) and is flagged.

create or replace table metrics.calendar as
select strftime(m,'%Y-%m') as month_ist,
  case when strftime(m,'%Y-%m')='2026-08' then 8 else date_diff('day', m, m + interval 1 month) end as days_observed,
  (strftime(m,'%Y-%m')='2026-08') as is_partial
from generate_series(timestamp '2026-01-01', timestamp '2026-08-01', interval 1 month) t(m);

-- Book (fixed denominator): all 30,000 accounts, never filtered on outcome/status.
create or replace table metrics.book as
select count(*) n_accounts, sum(outstanding_amount) outstanding, count(*) filter (where dpd>0) n_delinquent from golden.dim_account;

-- ===== Recovery: naive vs golden =====
create or replace table metrics.recovery_monthly as
with naive as (  -- raw SUCCESS rows incl. duplicates, month by source clock
  select strftime(event_at,'%Y-%m') month_ist, sum(amount) filter (where payment_status='SUCCESS') naive_success_amt,
         sum(amount) naive_all_status_amt, count(*) naive_rows
  from stg.payments group by 1),
g as (
  select month_ist, sum(recovered_amt) rec, count(*) filter (where is_success) n_success, count(distinct account_id) filter (where is_success) payers,
         sum(amount) filter (where is_pending) pending_amt, sum(amount) filter (where is_reversed) reversed_amt, sum(amount) filter (where payment_status='FAILED') failed_amt
  from golden.fact_payment group by 1)
select c.month_ist, c.days_observed, c.is_partial, n.naive_rows, n.naive_success_amt, n.naive_all_status_amt,
  g.rec as golden_recovered, g.n_success, g.payers, g.pending_amt, g.reversed_amt, g.failed_amt,
  g.rec / c.days_observed as golden_recovered_per_day,
  g.rec / c.days_observed * 30.0 / b.outstanding as recovery_rate_30d,       -- % of book outstanding recovered per 30 days
  g.rec / b.n_accounts as recovery_per_account_month,                       -- per account in the fixed book (not per payer)
  g.rec / g.payers as avg_ticket_per_payer
from metrics.calendar c left join naive n using (month_ist) left join g using (month_ist) cross join metrics.book b;

create or replace table metrics.recovery_mom as
select month_ist, is_partial,
  100*(naive_success_amt/lag(naive_success_amt) over (order by month_ist)-1) as naive_mom_pct,
  100*(golden_recovered/lag(golden_recovered) over (order by month_ist)-1) as golden_mom_pct,
  100*(golden_recovered_per_day/lag(golden_recovered_per_day) over (order by month_ist)-1) as golden_per_day_mom_pct,
  100*(days_observed/lag(days_observed) over (order by month_ist)-1) as calendar_days_mom_pct
from metrics.recovery_monthly order by 1;

-- ===== Contact / RPC / PTP definitions =====
create or replace table metrics.contact_monthly as
with c_naive as (select strftime(event_at,'%Y-%m') month_ist, avg((call_status in ('ANSWERED','VOICEMAIL'))::int) naive_contact_rate, count(*) raw_calls from stg.calls group by 1),
c_gold as (select strftime(event_ts_ist,'%Y-%m') month_ist, avg(is_connected::int) filter (where direction='OUTBOUND') contact_rate_outbound,
           count(*) filter (where direction='OUTBOUND') outbound_calls, count(distinct account_id) accounts_called from clean.calls group by 1),
d_naive as (select strftime(event_ts_ist,'%Y-%m') month_ist, avg((code_raw<>'NO_CONTACT')::int) naive_rpc_rate, avg((code_raw='PTP')::int) naive_ptp_share_of_dispo from clean.call_dispositions group by 1),
d_gold as (select strftime(event_ts_ist,'%Y-%m') month_ist, avg(is_rpc::int) rpc_rate, avg(is_ptp::int) filter (where is_rpc) ptp_per_rpc, count(*) dispositions from clean.call_dispositions group by 1)
select cn.month_ist, naive_contact_rate, contact_rate_outbound, naive_rpc_rate, rpc_rate, naive_ptp_share_of_dispo, ptp_per_rpc, raw_calls, outbound_calls, accounts_called, dispositions
from c_naive cn left join c_gold using (month_ist) left join d_naive using (month_ist) left join d_gold using (month_ist) order by 1;

create or replace table metrics.ptp_monthly as
select month_ist, count(*) ptp_created, sum(promised_amount) promised_amt,
  avg((status_raw='KEPT')::int) naive_kept_rate,                                               -- KEPT / all PTPs (incl. open, cancelled)
  count(*) filter (where status='KEPT') / nullif(count(*) filter (where status in ('KEPT','BROKEN')),0.0) as kept_rate_resolved,   -- KEPT / (KEPT+BROKEN)
  avg((cash_in_window>0)::int) filter (where is_matured) as cash_validated_rate,                -- any cash within window on matured PTPs
  avg((cash_in_window>=promised_amount)::int) filter (where is_matured) as cash_validated_full_rate,
  avg((cash_in_window>0)::int) filter (where is_matured and status='KEPT')   as cash_rate_if_status_kept,
  avg((cash_in_window>0)::int) filter (where is_matured and status='BROKEN') as cash_rate_if_status_broken
from golden.fact_ptp group by 1 order by 1;

-- ===== Channel conversion: accounts reached -> paid within 7d (golden) vs payments/messages (naive) =====
create or replace table metrics.channel_conversion as
with reached as (
  select account_id, channel, strftime(event_ts_ist,'%Y-%m') month_ist, min(event_ts_ist) first_reach
  from golden.fact_contact where is_reached and source_table<>'CALL_ATTEMPT' group by 1,2,3),
conv as (select r.*, exists(select 1 from golden.fact_payment p where p.account_id=r.account_id and p.is_success
          and p.event_ts_ist > r.first_reach and p.event_ts_ist <= r.first_reach + interval 7 day) as paid7 from reached r),
msgs as (select channel, strftime(event_ts_ist,'%Y-%m') month_ist, count(*) events from golden.fact_contact group by 1,2)
select c.channel, c.month_ist, count(*) accounts_reached, avg(paid7::int) conv_paid7_golden, any_value(m.events) all_events
from conv c left join msgs m using (channel, month_ist) group by 1,2 order by 1,2;
