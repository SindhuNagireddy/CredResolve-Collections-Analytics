"""Stratified 'touch lift': does an outreach event raise P(success payment in next 7 days)?
Unit = account-day. Strata = dpd_bucket x loan_type x month (exact stratification, Mantel-Haenszel pooled risk difference).
Placebo: same estimator with the outcome window shifted 14 days later (a touch cannot cause a payment that is not yet in its window
 -> RD should be ~0 if the estimator is not picking up confounding)."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stats_lib import *
def run():
    con = connect()
    con.execute("create or replace temp table days as select cast(d as date) dt, row_number() over (order by d) di from generate_series(timestamp '2026-01-01', timestamp '2026-08-01', interval 1 day) t(d)")
    con.execute("create or replace temp table pay_i as select p.account_id, d.di from (select distinct account_id, cast(event_ts_ist as date) dt from golden.fact_payment where is_success) p join days d using (dt)")
    con.execute("create or replace temp table touch_i as select c.account_id, d.di, c.channel from golden.fact_contact c join days d on d.dt=cast(c.event_ts_ist as date) where source_table<>'CALL_ATTEMPT' and is_reached group by 1,2,3")
    con.execute("create or replace temp table grid as select a.account_id, a.dpd_bucket, a.loan_type, d.di, strftime(d.dt,'%Y-%m') m from golden.dim_account a cross join days d where d.di<=200")
    res = []
    for ch in ['VOICE', 'WHATSAPP', 'SMS', 'FIELD']:
        for lead in [0, 14]:
            df = con.execute(f"""
            select g.dpd_bucket, g.loan_type, g.m, (t.account_id is not null) tr, count(*) n,
              sum((exists(select 1 from pay_i p where p.account_id=g.account_id and p.di>g.di+{lead} and p.di<=g.di+{lead}+7))::int) yy
            from grid g left join (select * from touch_i where channel='{ch}') t on t.account_id=g.account_id and t.di=g.di group by 1,2,3,4""").df()
            a = df[df.tr].rename(columns={'n': 'n1', 'yy': 'y1'}).drop(columns='tr'); b = df[~df.tr].rename(columns={'n': 'n0', 'yy': 'y0'}).drop(columns='tr')
            m = a.merge(b, on=['dpd_bucket', 'loan_type', 'm'])
            rd, lo, hi, p = mh_risk_difference(m)
            res.append(dict(channel=ch, placebo_lead_days=lead, touched_account_days=int(m.n1.sum()), base_p7=m.y0.sum() / m.n0.sum(), rd=rd, lo=lo, hi=hi, p=p))
            print(res[-1], flush=True)
    out = pd.DataFrame(res); out.to_csv(ROOT / 'golden' / 'touch_lift.csv', index=False); return out
if __name__ == '__main__':
    run()
