
import argparse
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from html import escape

def read_csv(data, name):
    return pd.read_csv(data / f"{name}.csv", low_memory=False)

def to_ist(value, timezone):
    if pd.isna(value):
        return pd.NaT
    tz = timezone if isinstance(timezone, str) and timezone else "Asia/Kolkata"
    try:
        return pd.Timestamp(value).tz_localize(ZoneInfo(tz), ambiguous="NaT", nonexistent="shift_forward").tz_convert("Asia/Kolkata").tz_localize(None)
    except Exception:
        return pd.Timestamp(value)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()
    data, out = Path(args.data), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    charts = out / "charts"
    charts.mkdir(exist_ok=True)

    accounts = read_csv(data, "accounts")
    rawp = read_csv(data, "payments")
    vendors = read_csv(data, "vendor_telephony").set_index("vendor_id")["timezone"].to_dict()
    calls = read_csv(data, "calls")
    targets = read_csv(data, "daily_targeting")
    campaigns = read_csv(data, "campaigns")
    borrowers = read_csv(data, "borrowers")
    agents = read_csv(data, "agents")
    wa = read_csv(data, "whatsapp_events")
    sms = read_csv(data, "sms_events")

    rawp["event_at"] = pd.to_datetime(rawp.event_at, errors="coerce")
    duplicate_mask = rawp.duplicated("payment_id", keep="first")
    duplicate_success_amount = rawp.loc[duplicate_mask & rawp.payment_status.eq("SUCCESS"), "amount"].sum()
    duplicate_success_rows = int((duplicate_mask & rawp.payment_status.eq("SUCCESS")).sum())
    payments = rawp.loc[~duplicate_mask].copy()
    payments["timezone"] = payments.provider_id.map(vendors).fillna("Asia/Kolkata")
    payments["event_ts_ist"] = [to_ist(t,z) for t,z in zip(payments.event_at,payments.timezone)]
    payments["month"] = payments.event_ts_ist.dt.to_period("M").astype(str)
    payments["is_success"] = payments.payment_status.eq("SUCCESS")
    payments["recovered_amount"] = np.where(payments.is_success,payments.amount,0.0)

    book_outstanding = pd.to_numeric(accounts.outstanding_amount,errors="coerce").sum()
    n_accounts = accounts.account_id.nunique()
    monthly = payments.groupby("month").agg(
        unique_payment_rows=("payment_id","nunique"),
        successful_payments=("is_success","sum"),
        recovered_amount=("recovered_amount","sum"),
        payers=("account_id",lambda s:s[payments.loc[s.index,"is_success"]].nunique()),
        pending_amount=("amount",lambda s:s[payments.loc[s.index,"payment_status"].eq("PENDING")].sum()),
        reversed_amount=("amount",lambda s:s[payments.loc[s.index,"payment_status"].eq("REVERSED")].sum()),
        failed_amount=("amount",lambda s:s[payments.loc[s.index,"payment_status"].eq("FAILED")].sum())
    ).sort_index()
    monthly["days_observed"] = [8 if m=="2026-08" else pd.Period(m).days_in_month for m in monthly.index]
    monthly["recovered_per_day"] = monthly.recovered_amount/monthly.days_observed
    monthly["recovery_rate_30d_pct"] = monthly.recovered_per_day*30/book_outstanding*100
    monthly["recovery_per_account"] = monthly.recovered_amount/n_accounts
    monthly["mom_recovered_pct"] = monthly.recovered_amount.pct_change()*100
    monthly["mom_per_day_pct"] = monthly.recovered_per_day.pct_change()*100
    monthly["is_partial_month"] = (monthly.index == "2026-08")
    monthly.to_csv(out/"monthly_recovery.csv",index_label="month")

    raw_success = rawp.loc[rawp.payment_status.eq("SUCCESS"),"amount"].sum()
    dedup_success = payments.loc[payments.is_success,"amount"].sum()
    dq = pd.DataFrame([
        {"dataset":"payments","rule":"DUPLICATE_PAYMENT_ID","action":"reject","raw_rows":len(rawp),"affected_rows":int(duplicate_mask.sum()),"business_impact_inr":float(duplicate_success_amount),"interpretation":"Repeated successful amount on later duplicate payment_id rows; exclude from recovered cash."},
        {"dataset":"calls","rule":"DUPLICATE_CALL_ID","action":"reject","raw_rows":len(calls),"affected_rows":int(calls.duplicated("call_id",keep="first").sum()),"business_impact_inr":np.nan,"interpretation":"Keep first row per call_id; preserve rejected rows and confirm retry semantics."},
        {"dataset":"whatsapp_events","rule":"DUPLICATE_EVENT_ID","action":"reject","raw_rows":len(wa),"affected_rows":int(wa.duplicated("whatsapp_event_id",keep="first").sum()),"business_impact_inr":np.nan,"interpretation":"Keep first row per whatsapp_event_id."},
        {"dataset":"sms_events","rule":"DUPLICATE_EVENT_ID","action":"investigate","raw_rows":len(sms),"affected_rows":int(sms.duplicated("sms_event_id",keep="first").sum()),"business_impact_inr":np.nan,"interpretation":"No duplicate IDs detected in supplied extract."},
        {"dataset":"borrowers","rule":"SUPERSEDED_BORROWER_VERSION","action":"deduplicate","raw_rows":len(borrowers),"affected_rows":int(borrowers.duplicated("borrower_id",keep="first").sum()),"business_impact_inr":np.nan,"interpretation":"Select latest valid borrower version, preserving history."},
        {"dataset":"agents","rule":"SUPERSEDED_AGENT_VERSION","action":"deduplicate","raw_rows":len(agents),"affected_rows":int(agents.duplicated("agent_id",keep="first").sum()),"business_impact_inr":np.nan,"interpretation":"Select latest agent version; do not merge identities solely on name."}
    ])
    dq.to_csv(out/"data_quality_summary.csv",index=False)

    calls["event_at"] = pd.to_datetime(calls.event_at,errors="coerce")
    calls["event_ts_ist"] = [to_ist(t,z) for t,z in zip(calls.event_at,calls.timezone.fillna("Asia/Kolkata"))]
    calls["source_month"] = calls.event_at.dt.to_period("M").astype(str)
    calls["ist_month"] = calls.event_ts_ist.dt.to_period("M").astype(str)
    calls["month_changed"] = calls.source_month.ne(calls.ist_month)
    calls["hour_changed"] = calls.event_at.dt.hour.ne(calls.event_ts_ist.dt.hour)
    timezone_summary = pd.DataFrame([{
        "calls":len(calls),
        "month_classification_changed":int(calls.month_changed.sum()),
        "month_classification_changed_pct":float(calls.month_changed.mean()*100),
        "hour_classification_changed":int(calls.hour_changed.sum()),
        "hour_classification_changed_pct":float(calls.hour_changed.mean()*100),
        "source_hour_08_18_pct":float(calls.event_at.dt.hour.between(8,18).mean()*100),
        "ist_hour_08_18_pct":float(calls.event_ts_ist.dt.hour.between(8,18).mean()*100)
    }])
    timezone_summary.to_csv(out/"timezone_audit.csv",index=False)

    accounts["dpd_bucket"] = pd.cut(pd.to_numeric(accounts.dpd,errors="coerce"),
        bins=[-np.inf,0,29,59,89,np.inf],labels=["0 current","1-29","30-59","60-89","90+"])
    payer_month = payments.loc[payments.is_success,["account_id","month","recovered_amount"]].groupby(["month","account_id"],as_index=False).recovered_amount.sum()
    payer_month = payer_month.merge(accounts[["account_id","loan_type","dpd_bucket","risk_segment"]],on="account_id",how="left")
    segment = payer_month.groupby(["month","loan_type"],observed=False).agg(payers=("account_id","nunique"),recovery=("recovered_amount","sum")).reset_index()
    seg_book = accounts.groupby("loan_type",observed=False).account_id.nunique().rename("book_accounts")
    segment = segment.join(seg_book,on="loan_type")
    segment["payer_rate_pct"] = segment.payers/segment.book_accounts*100
    segment.to_csv(out/"loan_type_monthly.csv",index=False)
    dpd = payer_month.groupby(["month","dpd_bucket"],observed=False).agg(payers=("account_id","nunique"),recovery=("recovered_amount","sum")).reset_index()
    dpd_book = accounts.groupby("dpd_bucket",observed=False).account_id.nunique().rename("book_accounts")
    dpd = dpd.join(dpd_book,on="dpd_bucket")
    dpd["payer_rate_pct"] = dpd.payers/dpd.book_accounts*100
    dpd.to_csv(out/"dpd_monthly.csv",index=False)

    # Survivorship/denominator sensitivity by current account status snapshot.
    status_panel = payments.loc[payments.is_success,["account_id","month"]].drop_duplicates()
    status_panel = status_panel.merge(accounts[["account_id","status"]],on="account_id",how="right")
    status_panel["paid"] = status_panel.month.notna().astype(int)
    status_panel = status_panel[status_panel.month.isin(monthly.index)]
    status_counts = status_panel.groupby(["month","status"]).agg(
        paying_accounts=("account_id",lambda s:s[status_panel.loc[s.index,"paid"].eq(1)].nunique())
    ).reset_index()
    status_book = accounts.groupby("status").account_id.nunique().rename("book_accounts")
    status_counts = status_counts.join(status_book,on="status")
    status_counts["payer_rate_pct"] = status_counts.paying_accounts/status_counts.book_accounts*100
    status_counts.to_csv(out/"survivorship_status_audit.csv",index=False)

    targets["target_date"] = pd.to_datetime(targets.target_date,errors="coerce")
    targets["month"] = targets.target_date.dt.to_period("M").astype(str)
    targetmix = targets.merge(campaigns[["campaign_id","strategy_version","target_definition","channel"]],on="campaign_id",how="left")
    targetmix = targetmix.merge(accounts[["account_id","loan_type","dpd"]],on="account_id",how="left")
    targetmix.groupby(["month","strategy_version"]).size().rename("target_rows").reset_index().to_csv(out/"targeting_strategy_mix.csv",index=False)
    targetmix.groupby(["month","loan_type"]).account_id.nunique().rename("targeted_accounts").reset_index().to_csv(out/"targeting_portfolio_mix.csv",index=False)

    # Denominator/selection audit: status-conditioned account counts and same-month payers.
    target_accounts = targetmix.groupby(["month","account_id"]).agg(
        statuses=("status", lambda s: set(s.astype(str))),
        target_events=("target_id","count")
    ).reset_index()
    payers_by_month = payments.loc[payments.is_success].groupby(["month","account_id"]).size().rename("paid_events").reset_index()
    target_accounts = target_accounts.merge(payers_by_month,on=["month","account_id"],how="left")
    target_accounts["paid"] = target_accounts.paid_events.fillna(0).gt(0)
    target_accounts["ever_contacted"] = target_accounts.statuses.map(lambda s: "CONTACTED" in s)
    target_accounts["ever_dropped"] = target_accounts.statuses.map(lambda s: bool({"EXPIRED","SKIPPED"} & s))
    denominator = target_accounts.groupby("month").agg(
        targeted_accounts=("account_id","nunique"),
        ever_contacted_accounts=("ever_contacted","sum"),
        ever_dropped_accounts=("ever_dropped","sum"),
        payers_among_targeted=("paid","sum"),
        payers_among_contacted=("paid",lambda s: int(s[target_accounts.loc[s.index,"ever_contacted"]].sum()))
    ).reset_index()
    denominator["payer_rate_all_targeted_pct"] = denominator.payers_among_targeted / denominator.targeted_accounts * 100
    denominator["payer_rate_ever_contacted_pct"] = denominator.payers_among_contacted / denominator.ever_contacted_accounts * 100
    denominator["caveat"] = "Same-month association only; payment may precede target/contact. Do not interpret as conversion or causal lift."
    denominator.to_csv(out/"targeting_denominator_audit.csv",index=False)

    # First-target cohort analysis with a fully observed 30-day outcome window.
    first_target = targetmix.groupby("account_id",as_index=False).target_date.min()
    first_target["cohort_month"] = first_target.target_date.dt.to_period("M").astype(str)
    observation_end = payments.event_ts_ist.max().normalize()
    first_target["window_end"] = first_target.target_date + pd.Timedelta(days=30)
    first_target["window_complete"] = first_target.window_end <= observation_end
    cohort_eligible = first_target[first_target.window_complete].copy()
    success_events = payments.loc[payments.is_success,["account_id","event_ts_ist"]]
    cohort_events = cohort_eligible.merge(success_events,on="account_id",how="left")
    cohort_events["paid_within_30d"] = (
        cohort_events.event_ts_ist.notna()
        & (cohort_events.event_ts_ist >= cohort_events.target_date)
        & (cohort_events.event_ts_ist <= cohort_events.window_end)
    )
    cohort_out = cohort_events.groupby(["cohort_month","account_id"]).paid_within_30d.max().reset_index()
    cohort_summary = cohort_out.groupby("cohort_month").agg(
        first_target_accounts=("account_id","nunique"),
        accounts_paid_within_30d=("paid_within_30d","sum")
    ).reset_index()
    cohort_summary["paid_within_30d_rate_pct"] = cohort_summary.accounts_paid_within_30d/cohort_summary.first_target_accounts*100
    cohort_summary["window_note"] = "Only accounts with a complete 30-day follow-up window; descriptive, not causal."
    cohort_summary.to_csv(out/"first_target_cohort_30d.csv",index=False)

    t2 = targetmix[["account_id","target_date","campaign_id"]].dropna(subset=["account_id","target_date"]).copy()
    successful = payments.loc[payments.is_success,["payment_id","account_id","event_ts_ist","recovered_amount"]].copy()
    successful["payment_date"] = successful.event_ts_ist.dt.normalize()
    latest_any = t2.sort_values("target_date").groupby("account_id").tail(1)[["account_id","target_date","campaign_id"]]
    latest_join = successful.merge(latest_any,on="account_id",how="left",suffixes=("","_latest"))
    naive_after = int((latest_join.target_date > latest_join.payment_date).fillna(False).sum())

    candidate = successful.merge(t2,on="account_id",how="left",suffixes=("","_target"))
    in_window = candidate[
        candidate.target_date.notna()
        & (candidate.target_date <= candidate.payment_date)
        & (candidate.target_date >= candidate.payment_date - pd.Timedelta(days=30))
    ].copy()
    last_touch = in_window.sort_values("target_date").drop_duplicates("payment_id",keep="last")
    has_lookback = len(last_touch)
    latest_campaign = latest_join.set_index("payment_id").target_date
    last_campaign = last_touch.set_index("payment_id").campaign_id
    latest_campaign_id = latest_join.set_index("payment_id").campaign_id
    disagree_ids = set(last_campaign.index) & set(latest_campaign_id.index)
    disagree = int(sum(latest_campaign_id.loc[i] != last_campaign.loc[i] for i in disagree_ids))
    no_touch_ids = set(successful.payment_id) - set(last_touch.payment_id)
    amount_no_touch = float(successful.loc[successful.payment_id.isin(no_touch_ids),"recovered_amount"].sum())
    pd.DataFrame([{
        "successful_payment_events":len(successful),
        "successful_payments_with_any_target_record":int(successful.account_id.isin(t2.account_id).sum()),
        "latest_target_after_payment_events":naive_after,
        "payments_with_30d_prior_target":int(has_lookback),
        "naive_latest_vs_30d_last_touch_disagree_events":disagree,
        "successful_recovery_amount":float(successful.recovered_amount.sum()),
        "recovery_amount_without_30d_prior_target":amount_no_touch,
        "interpretation":"Targeting is not proof of delivered contact or causation; this is attribution sensitivity, not causal credit."
    }]).to_csv(out/"attribution_audit.csv",index=False)

    x = pd.PeriodIndex(monthly.index,freq="M").to_timestamp()
    for column, filename, title, ylabel in [
        ("recovered_amount","monthly_recovery.png","Monthly successful payments (IST; August partial)","₹ million"),
        ("recovered_per_day","daily_normalized_recovery.png","Daily-normalized recovery (IST)","₹ million per day")]:
        fig,ax=plt.subplots(figsize=(10,4.8))
        ax.plot(x,monthly[column]/1e6,marker="o",label=title)
        ax.set_title(title); ax.set_ylabel(ylabel); ax.grid(True,alpha=.25); ax.legend()
        fig.tight_layout(); fig.savefig(charts/filename,dpi=160); plt.close(fig)

    jan,jul=monthly.loc["2026-01"],monthly.loc["2026-07"]
    daily_change=(jul.recovered_per_day/jan.recovered_per_day-1)*100
    feb_mar_total_change=(monthly.loc["2026-03","recovered_amount"]/monthly.loc["2026-02","recovered_amount"]-1)*100
    feb_mar_daily_change=(monthly.loc["2026-03","recovered_per_day"]/monthly.loc["2026-02","recovered_per_day"]-1)*100
    money=lambda v:"₹"+f"{v/1e7:,.2f} Cr"
    rows = "".join(
        f"<tr><td>{escape(str(i))}</td>"
        f"<td>{money(r.recovered_amount)}</td>"
        f"<td>{money(r.recovered_per_day * 30)}</td>"
        f"<td>{chr(8212) if pd.isna(r.mom_per_day_pct) else f'{r.mom_per_day_pct:+.2f}%'}</td>"
        f"<td>{int(r.payers):,}</td></tr>"
        for i, r in monthly.iterrows()
    )
    html=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CredResolve | Collections truth dashboard</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f5f7fb;color:#172033;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{max-width:1200px;margin:auto;padding:28px}}h1{{font-size:25px;margin:0 0 4px}}h2{{font-size:16px;margin:0 0 12px}}p{{margin:4px 0;color:#667085}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0}}.card,.panel{{background:#fff;border:1px solid #e3e7ee;border-radius:12px;padding:16px}}.label{{color:#667085;font-size:12px}}.value{{font-size:24px;font-weight:700;margin:7px 0}}.small{{font-size:12px;color:#667085}}.twocol{{display:grid;grid-template-columns:1.15fr .85fr;gap:12px}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:9px 7px;border-bottom:1px solid #e3e7ee;text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{color:#667085;font-weight:600}}.flag{{border-left:4px solid #b7791f;padding:10px 12px;background:#fff8e8;border-radius:5px;margin:10px 0}}img{{width:100%;height:auto}}ul{{padding-left:18px;margin:8px 0}}li{{margin:6px 0}}@media(max-width:800px){{.grid{{grid-template-columns:repeat(2,1fr)}}.twocol{{grid-template-columns:1fr}}main{{padding:14px}}}}</style></head><body><main>
    <h1>Collections performance: independent reconstruction</h1><p>January–August 2026 · IST-normalized successful payments · Fixed book denominator · August observed through 8 Aug only</p>
    <div class="grid"><div class="card"><div class="label">Unique successful payment events</div><div class="value">{int(payments.is_success.sum()):,}</div><div class="small">After payment_id deduplication</div></div><div class="card"><div class="label">Recovered amount, Jan–Jul</div><div class="value">{money(monthly.loc["2026-01":"2026-07","recovered_amount"].sum())}</div><div class="small">Successful status only</div></div><div class="card"><div class="label">Jan→Jul recovery/day change</div><div class="value">{daily_change:+.2f}%</div><div class="small">Not an 11% sustained improvement</div></div><div class="card"><div class="label">Duplicate successful amount</div><div class="value">{money(duplicate_success_amount)}</div><div class="small">{duplicate_success_rows:,} duplicate success rows rejected</div></div></div>
    <div class="flag"><b>Executive read:</b> The supplied extract covers Jan–Aug 2026, not a full 12 months. After payment-ID deduplication and daily normalization, recovery per day changes by {daily_change:+.2f}% from January to July. The February-to-March total rises {feb_mar_total_change:+.2f}%, but the per-day change is only {feb_mar_daily_change:+.2f}% as March has 31 days versus February's 28. The data does not support sustained +11% operational improvement. August is partial.</div>
    <div class="twocol"><section class="panel"><h2>Recovery trend</h2><img src="charts/monthly_recovery.png" alt="Monthly successful payment amount"><img src="charts/daily_normalized_recovery.png" alt="Daily normalized recovery"></section><section class="panel"><h2>Monthly performance</h2><table><thead><tr><th>Month</th><th>Recovery</th><th>30-day equivalent*</th><th>MoM / day</th><th>Payers</th></tr></thead><tbody>{rows}</tbody></table><p class="small">*30-day equivalent = daily recovery × 30; denominator is total current outstanding balance. This is normalization, not forecast.</p></section></div>
    <div class="twocol" style="margin-top:12px"><section class="panel"><h2>What to trust / investigate</h2><ul><li><b>Trust provisionally:</b> successful payment status after payment_id deduplication; fixed denominator of all {n_accounts:,} accounts.</li><li><b>Data-quality impact:</b> {duplicate_success_rows:,} duplicate successful rows contain {money(duplicate_success_amount)} of repeated amount.</li><li><b>Time:</b> {int(calls.month_changed.sum()):,} calls ({calls.month_changed.mean()*100:.2f}%) shift month after timezone normalization; {int(calls.hour_changed.sum()):,} ({calls.hour_changed.mean()*100:.2f}%) shift hour.</li><li><b>Attribution:</b> targeting is not the same as a verified contact; last-touch attribution is sensitive to window choice.</li></ul></section><section class="panel"><h2>Investment decision</h2><p>Do not commit the full ₹10 Cr based on observational data alone. Run a randomized or phased pilot for the strongest candidate, with holdout and pre-registered outcomes.</p><ul><li>Measure incremental successful recovery net of reversals and costs.</li><li>Stratify by DPD, loan type, client, geography and channel.</li><li>Track complaints and cost per incremental ₹ recovered.</li><li>Scale only if conservative incremental ROI is positive.</li></ul></section></div>
    <p class="small" style="margin-top:16px">Generated from supplied synthetic assignment data. Findings are descriptive; causal claims require a credible experiment or counterfactual design. See executive_memo.md and analysis tables for definitions and caveats.</p></main></body></html>'''
    (out/"dashboard.html").write_text(html,encoding="utf-8")

    memo=f'''# Executive memo — CredResolve collections performance

**Scope.** Supplied extract, 1 January–8 August 2026. This is eight observed calendar months, with August partial; it is not a full 12-month history. Recovery is defined here as deduplicated payment rows with `payment_status = SUCCESS`, assigned to month after converting the provider's declared timezone to Asia/Kolkata. This is a transparent working definition, not proof that every event is settled cash; reversals and settlement confirmation should be reconciled with the payment ledger.

## What happened?
- Deduplicated successful payments total **{money(dedup_success)}** across the observed period.
- January recovery/day was **{money(jan.recovered_per_day)}**; July was **{money(jul.recovered_per_day)}**, a change of **{daily_change:+.2f}%**.
- February→March deduplicated total recovery rises **{feb_mar_total_change:+.2f}%**, close to the reported claim, but daily-normalized recovery rises only **{feb_mar_daily_change:+.2f}%** because March has 31 days versus February's 28. Other months move in both directions.
- August contains only eight observed days. Comparing its raw total with full months would understate performance.

## Why / data forensics
- **Duplicate payment IDs (strong evidence):** {int(duplicate_mask.sum()):,} later duplicate rows were found in {len(rawp):,} raw payment rows. Duplicate successful rows account for **{money(duplicate_success_amount)}** repeated amount; raw successful amount is {money(raw_success)} versus {money(dedup_success)} after deduplication. This is a correction, not incremental recovery.
- **Duplicate calls / digital events (strong evidence):** {int(calls.duplicated("call_id",keep="first").sum()):,} duplicate `call_id` rows and {int(wa.duplicated("whatsapp_event_id",keep="first").sum()):,} duplicate WhatsApp event IDs.
- **Timezone classification (strong evidence):** {int(calls.month_changed.sum()):,} of {len(calls):,} calls ({calls.month_changed.mean()*100:.2f}%) change calendar month, and {int(calls.hour_changed.sum()):,} ({calls.hour_changed.mean()*100:.2f}%) change hour when normalized to IST.
- **Identity/version risk:** {int(borrowers.duplicated("borrower_id",keep="first").sum()):,} repeated borrower IDs and {int(agents.duplicated("agent_id",keep="first").sum()):,} repeated agent IDs exist in versioned tables. Select latest valid records and preserve history; do not merge agents solely on name.
- **Attribution-window bias:** the naive latest-target record occurs after payment for {naive_after:,} of {len(successful):,} successful payment events; only {int(has_lookback):,} events have a target record in the prior 30 days. Under this definition, {money(amount_no_touch)} of successful amount has no 30-day prior targeting record. Targeting is not proof of a delivered contact or causal credit.

## Is the 11% claim real?
**Not established as a sustained operational improvement.** February-to-March total recovery rose {feb_mar_total_change:+.2f}%, but daily-normalized recovery rose only {feb_mar_daily_change:+.2f}%; January-to-July daily-normalized recovery changed {daily_change:+.2f}%. Monthly daily-normalized changes are {", ".join(f"{m}: {v:+.2f}%" for m,v in monthly.loc["2026-02":"2026-07","mom_per_day_pct"].items())}. Verification requires the original metric definition, original report and complete 12-month history. Use a fixed denominator, exclude duplicate/pending/failed/reversed events from recovery, and compare full months only.

## What should we do with ₹10 Cr?
**Recommendation: do not allocate the full amount yet.** The observational extract cannot reliably identify the causal return of AI voice, more agents, telephony, targeting, digital engagement or field operations. Run a staged randomized or phased pilot for one candidate intervention, stratified by DPD, loan type, client and geography, with a holdout group. Pre-register incremental successful recovery net of reversals and incremental cost as the primary outcome; track complaints and borrower outcomes as guardrails.

Estimate incremental recovery as treatment-minus-control per eligible account × eligible volume, net of costs. Report a confidence interval and downside case. Break-even occurs when incremental net recovery equals fully loaded pilot and scale costs. Expand only if the conservative confidence bound on incremental ROI is positive and guardrails remain acceptable.

## Confidence and limitations
- **High confidence:** duplicate event counts and arithmetic under the stated rules.
- **Moderate confidence:** monthly recovery after deduplication and timezone normalization, conditional on correct provider timezone metadata and SUCCESS meaning settled payment.
- **Low / not identified:** causal channel lift, targeting effect and investment ROI. Account DPD is a current snapshot, targeting is not delivered contact, and the extract ends in August.
'''
    (out/"executive_memo.md").write_text(memo,encoding="utf-8")
    architecture=r'''flowchart TD
    A[Raw CSVs + source metadata] --> B[Staging: schema, source row, load timestamp]
    B --> C[Clean: dedupe, type checks, timezone normalization]
    C --> D[Reject/quarantine tables with reason codes]
    C --> E[Golden entities and event facts]
    E --> F[Feature layer: account-month, cohort, channel and effort features]
    F --> G[Metrics layer: fixed-denominator recovery, RPC/PTP, cost and quality]
    G --> H[Executive one-screen dashboard]
    G --> I[Notebook, DQ report and executive memo]
    J[Data contracts + tests + lineage] -. monitor .-> B
    J -. monitor .-> C
    J -. monitor .-> E
    J -. monitor .-> G
    K[Late events / backfills] --> B
    H --> L[Leadership decision + controlled experiment]
'''
    (out/"architecture.mmd").write_text(architecture,encoding="utf-8")
    print(f"Wrote artifacts to {out.resolve()}")
    print(monthly[["recovered_amount","days_observed","recovered_per_day","mom_per_day_pct","payers"]].round(2).to_string())
    print(f"Duplicate successful amount: {duplicate_success_amount:,.2f} INR")
    print(f"Jan-to-Jul recovery/day change: {daily_change:+.2f}%")
    print(f"Call month shifts: {int(calls.month_changed.sum()):,}; hour shifts: {int(calls.hour_changed.sum()):,}")

if __name__ == "__main__":
    main()
