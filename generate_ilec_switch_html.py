#!/usr/bin/env python3
"""
ILEC Switch Consolidation Dashboard Generator
Usage:  python generate_ilec_switch_html.py
Output: ilec_switch_dashboard.html  (Desktop)
"""
import json, sys
from pathlib import Path
import pandas as pd

DESKTOP     = Path(r"C:\Users\v296938\Desktop")
PLOTLY_FILE = Path(r"C:\Users\v296938\Desktop\FWA\SQDB OFS SITE FORECAST\plotly-2.35.2.min.js")
OUTPUT      = DESKTOP / "ilec_switch_dashboard.html"

# ── Helpers ────────────────────────────────────────────────────────────────
def df_to_cols(df, cols):
    out = {}
    for c in cols:
        if c in df.columns:
            out[c] = [("" if (v is None or (isinstance(v, float) and str(v) == "nan")) else v)
                      for v in df[c].tolist()]
        else:
            out[c] = [""] * len(df)
    return out

def fmt_num(n):
    try:
        return f"{int(float(n)):,}"
    except Exception:
        return "0"

# ── Load data ──────────────────────────────────────────────────────────────
print("Finding latest ILEC Switch Decom file...")
files = sorted(DESKTOP.glob("*Switch Decom Summary*Full Data*.xlsx"))
if not files:
    print("ERROR: No matching files found on Desktop"); sys.exit(1)
latest_file = files[-1]
print(f"  Loading: {latest_file.name}")

xl    = pd.ExcelFile(latest_file, engine="openpyxl")
sheet = next((s for s in xl.sheet_names if "Full Data" in s), xl.sheet_names[-1])
df    = pd.read_excel(latest_file, sheet_name=sheet, engine="openpyxl")

snap_raw = latest_file.name[:8]
try:
    snap_date_fmt = pd.to_datetime(snap_raw, format="%m%d%Y").strftime("%B %d, %Y")
except Exception:
    snap_date_fmt = snap_raw

print(f"  {len(df):,} rows | {df['SWITCH_CLLI'].nunique()} switches | Sheet: {sheet}")

# ── Numeric cleanup ────────────────────────────────────────────────────────
for col in ["Circuit", "#G5 Needed", "IDLC_SYSTEM_COUNT", "ANNUAL_POWER_SAVINGS",
            "Est. Annual Power Savings", "ACD_COUNT", "TANDEM_COUNT"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

# ── Switch-level aggregation (Switch Clli = per-switch key; SWITCH_CLLI = host CLLI) ──
sw_df = df.groupby("Switch Clli", as_index=False).agg(
    switch_name       = ("Switch Name",            "first"),
    sw_type           = ("SWITCH_TYPE_NAME",        "first"),
    clli_status       = ("CLLI_STATUS",             "first"),
    state             = ("STATE",                   "first"),
    area              = ("Area",                    "first"),
    region            = ("Region",                  "first"),
    host_remote       = ("Host or Remote",          "first"),
    host_clli         = ("SWITCH_CLLI",             "first"),  # SWITCH_CLLI = host CLLI
    decom_plan        = ("Decom Plan",              "first"),
    proposed_cutover  = ("Proposed Switch Cutover", "first"),
    circuits          = ("Circuit",                 "sum"),
    g5_needed         = ("#G5 Needed",              "first"),
    idlc_systems      = ("IDLC_SYSTEM_COUNT",       "first"),
    annual_savings    = ("ANNUAL_POWER_SAVINGS",    "sum"),
    est_savings       = ("Est. Annual Power Savings","first"),
)
g5_mig = df[df["G5 Migratable"] == "Y"].groupby("Switch Clli")["Circuit"].sum().rename("g5_mig")
sw_df  = sw_df.join(g5_mig, on="Switch Clli")
sw_df["g5_mig"] = sw_df["g5_mig"].fillna(0).astype(int)
sw_df["circuits"]       = sw_df["circuits"].fillna(0).astype(int)
sw_df["g5_needed"]      = sw_df["g5_needed"].fillna(0).astype(int)
sw_df["idlc_systems"]   = sw_df["idlc_systems"].fillna(0).astype(int)
sw_df["annual_savings"] = sw_df["annual_savings"].fillna(0)
sw_df["est_savings"]    = sw_df["est_savings"].fillna(0)
sw_df["proposed_cutover"] = sw_df["proposed_cutover"].apply(
    lambda v: "" if pd.isnull(v) else str(v)[:10])

# ── Summary KPIs ───────────────────────────────────────────────────────────
total_circuits  = int(df["Circuit"].sum())
total_switches  = int(sw_df["Switch Clli"].nunique())
matched         = int(df[df["MATCH_CATEGORY"] == "cable pair matched"]["Circuit"].sum())
match_rate      = round(matched / total_circuits * 100, 1) if total_circuits else 0
g5_y            = int(df[df["G5 Migratable"] == "Y"]["Circuit"].sum())
g5_pct          = round(g5_y / total_circuits * 100, 1) if total_circuits else 0
decom_y         = int((sw_df["decom_plan"] == "Y").sum())
hosts_count     = int((sw_df["host_remote"] == "Host or Base switch").sum())
remotes_count   = int(sw_df["host_remote"].isin(["Survivable Remote Switch","Non-Survivable Remote Switch"]).sum())
total_savings     = float(sw_df["annual_savings"].sum())
savings_pop       = int((sw_df["annual_savings"] > 0).sum())
total_est_savings = float(sw_df["est_savings"].sum())
est_savings_pop   = int((sw_df["est_savings"] > 0).sum())
total_idlc      = int(sw_df["idlc_systems"].sum())
status_counts   = {str(k): int(v) for k, v in sw_df["clli_status"].value_counts().items()}
print(f"  Switch Clli unique: {total_switches}")

# ── State pivot (State × MATCH_CATEGORY) ──────────────────────────────────
match_cats = ["cable pair matched","cable pair unmatched","circuits in lfacs only","wtns in switch os only"]
piv = df.groupby(["STATE","MATCH_CATEGORY"])["Circuit"].sum().unstack(fill_value=0).reset_index()
for cat in match_cats:
    if cat not in piv.columns:
        piv[cat] = 0
piv["total"] = piv[match_cats].sum(axis=1)
state_area = sw_df[["state","area"]].drop_duplicates().rename(columns={"state":"STATE","area":"Area"}).dropna(subset=["STATE"])
piv = piv.merge(state_area, on="STATE", how="left").sort_values(["Area","STATE"])
piv = piv.rename(columns={
    "cable pair matched":       "matched",
    "cable pair unmatched":     "unmatched",
    "circuits in lfacs only":   "lfacs",
    "wtns in switch os only":   "sw_only",
})

# Build pivot HTML in Python
pivot_rows_html = []
area_order = piv["Area"].dropna().unique()
for area in sorted(area_order):
    area_df = piv[piv["Area"] == area]
    am = int(area_df["matched"].sum()); au = int(area_df["unmatched"].sum())
    al = int(area_df["lfacs"].sum());   aso = int(area_df["sw_only"].sum())
    at = int(area_df["total"].sum())
    pivot_rows_html.append(
        f'<tr class="area-row"><td colspan="2"><strong>{area}</strong></td>'
        f'<td class="right">{fmt_num(am)}</td><td class="right">{fmt_num(au)}</td>'
        f'<td class="right">{fmt_num(al)}</td><td class="right">{fmt_num(aso)}</td>'
        f'<td class="right"><strong>{fmt_num(at)}</strong></td></tr>'
    )
    for _, row in area_df.iterrows():
        pivot_rows_html.append(
            f'<tr><td></td><td>{row["STATE"]}</td>'
            f'<td class="right">{fmt_num(row["matched"])}</td>'
            f'<td class="right">{fmt_num(row["unmatched"])}</td>'
            f'<td class="right">{fmt_num(row["lfacs"])}</td>'
            f'<td class="right">{fmt_num(row["sw_only"])}</td>'
            f'<td class="right"><strong>{fmt_num(row["total"])}</strong></td></tr>'
        )
gm = int(piv["matched"].sum()); gu = int(piv["unmatched"].sum())
gl = int(piv["lfacs"].sum());   gs = int(piv["sw_only"].sum()); gt = int(piv["total"].sum())
pivot_rows_html.append(
    f'<tr class="grand-total-row"><td colspan="2"><strong>Grand Total</strong></td>'
    f'<td class="right"><strong>{fmt_num(gm)}</strong></td>'
    f'<td class="right"><strong>{fmt_num(gu)}</strong></td>'
    f'<td class="right"><strong>{fmt_num(gl)}</strong></td>'
    f'<td class="right"><strong>{fmt_num(gs)}</strong></td>'
    f'<td class="right"><strong>{fmt_num(gt)}</strong></td></tr>'
)
pivot_html_content = "\n".join(pivot_rows_html)

# ── Match by state (for charts) ───────────────────────────────────────────
mbs = df.groupby(["STATE","MATCH_CATEGORY"])["Circuit"].sum().reset_index()
match_by_state_data = []
for state, grp in mbs.groupby("STATE"):
    row = {"state": str(state)}
    for cat in match_cats:
        sub = grp[grp["MATCH_CATEGORY"] == cat]["Circuit"].sum()
        row[cat] = int(sub)
    match_by_state_data.append(row)

# ── Switch-level reconciliation table data ────────────────────────────────
sw_match = df.groupby(["Switch Clli","MATCH_CATEGORY"])["Circuit"].sum().unstack(fill_value=0).reset_index()
for cat in match_cats:
    if cat not in sw_match.columns:
        sw_match[cat] = 0
sw_match["recon_total"] = sw_match[match_cats].sum(axis=1)
sw_match = sw_match.merge(sw_df[["Switch Clli","switch_name","sw_type","state","area","host_remote"]], on="Switch Clli", how="left")
sw_match = sw_match.rename(columns={"Switch Clli": "SWITCH_CLLI"}).fillna("")

# ── Match by switch type ───────────────────────────────────────────────────
mbt = df.groupby(["SWITCH_TYPE_NAME","MATCH_CATEGORY"])["Circuit"].sum().reset_index()
match_by_type_data = []
for sw_type, grp in mbt.groupby("SWITCH_TYPE_NAME"):
    row = {"sw_type": str(sw_type)}
    for cat in match_cats:
        sub = grp[grp["MATCH_CATEGORY"] == cat]["Circuit"].sum()
        row[cat] = int(sub)
    row["total"] = sum(row[cat] for cat in match_cats)
    match_by_type_data.append(row)
match_by_type_data.sort(key=lambda x: x["total"], reverse=True)

# ── G5 by state ───────────────────────────────────────────────────────────
g5s = df.groupby(["STATE","G5 Migratable"])["Circuit"].sum().unstack(fill_value=0).reset_index()
if "Y" not in g5s.columns: g5s["Y"] = 0
if "N" not in g5s.columns: g5s["N"] = 0
g5_by_state_data = g5s.rename(columns={"STATE":"state","Y":"migratable","N":"ineligible"}).to_dict("records")

# G5 by switch type
g5t = df.groupby(["SWITCH_TYPE_NAME","G5 Migratable"])["Circuit"].sum().unstack(fill_value=0).reset_index()
if "Y" not in g5t.columns: g5t["Y"] = 0
if "N" not in g5t.columns: g5t["N"] = 0
g5_by_type_data = g5t.rename(columns={"SWITCH_TYPE_NAME":"sw_type","Y":"migratable","N":"ineligible"}).to_dict("records")
g5_by_type_data.sort(key=lambda x: x.get("migratable",0)+x.get("ineligible",0), reverse=True)

# ── Circuit type ───────────────────────────────────────────────────────────
ckt_type_totals = {str(k): int(v) for k, v in df.groupby("Circuit Type")["Circuit"].sum().items()}
cts = df.groupby(["STATE","Circuit Type"])["Circuit"].sum().unstack(fill_value=0).reset_index()
for ct in ["Copper","OLT-FTTP","PG - Integrated"]:
    if ct not in cts.columns:
        cts[ct] = 0
ckt_type_by_state = cts.rename(columns={"STATE":"state"}).fillna(0).to_dict("records")

# ── IDLC by state ──────────────────────────────────────────────────────────
idlc_by_state_data = sw_df.groupby("state").agg(
    idlc_systems=("idlc_systems","sum"),
    switches=("Switch Clli","count")
).reset_index().to_dict("records")

# ── Savings ────────────────────────────────────────────────────────────────
sav_df = sw_df[(sw_df["annual_savings"] > 0) | (sw_df["est_savings"] > 0)].copy().sort_values("est_savings", ascending=False).fillna("")

# ── Dependencies ──────────────────────────────────────────────────────────
dep_df = df[df["Host or Remote"].isin(["Survivable Remote Switch","Non-Survivable Remote Switch"])]\
    .drop_duplicates("Switch Clli")[["Switch Clli","Switch Name","SWITCH_TYPE_NAME","STATE","SWITCH_CLLI","Host or Remote"]]\
    .copy()
dep_df.columns = ["remote_clli","remote_name","remote_type","remote_state","host_clli","survivable"]
dep_df = dep_df.fillna("")

host_rc = dep_df.groupby("host_clli")["remote_clli"].count().reset_index()
host_rc.columns = ["host_clli","remote_count"]
host_det = sw_df[sw_df["host_remote"] == "Host or Base switch"][["Switch Clli","switch_name","state","clli_status"]].copy()
host_det.columns = ["host_clli","host_name","host_state","host_status"]
host_summary = host_rc.merge(host_det, on="host_clli", how="left").sort_values("remote_count", ascending=False).fillna("")

# ── Per-switch match & circuit-type dicts (for Site Lookup) ───────────────
sw_match_dict = {}
for _, row in df.groupby(["Switch Clli","MATCH_CATEGORY"])["Circuit"].sum().reset_index().iterrows():
    c = str(row["Switch Clli"])
    sw_match_dict.setdefault(c, {})[str(row["MATCH_CATEGORY"])] = int(row["Circuit"])

sw_ckt_dict = {}
for _, row in df.groupby(["Switch Clli","Circuit Type"])["Circuit"].sum().reset_index().iterrows():
    c = str(row["Switch Clli"])
    sw_ckt_dict.setdefault(c, {})[str(row["Circuit Type"])] = int(row["Circuit"])

# ── Plotly.js ──────────────────────────────────────────────────────────────
if PLOTLY_FILE.exists():
    print(f"Plotly.js referenced from local file ({PLOTLY_FILE.stat().st_size/1024/1024:.1f} MB)")
    plotly_script = f'<script src="{PLOTLY_FILE.as_uri()}"></script>'
else:
    print("WARNING: plotly-2.35.2.min.js not found — using CDN")
    plotly_script = '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'

# ── Serialize DATA ─────────────────────────────────────────────────────────
DATA = {
    "summary": {
        "snap_date":      snap_date_fmt,
        "total_switches": total_switches,
        "total_circuits": total_circuits,
        "match_rate":     match_rate,
        "matched":        matched,
        "g5_pct":         g5_pct,
        "g5_y":           g5_y,
        "decom_y":        decom_y,
        "hosts":          hosts_count,
        "remotes":        remotes_count,
        "total_savings":      total_savings,
        "savings_pop":        savings_pop,
        "total_est_savings":  total_est_savings,
        "est_savings_pop":    est_savings_pop,
        "total_idlc":     total_idlc,
        "status_counts":  status_counts,
    },
    "match_by_state":  match_by_state_data,
    "match_by_type":   match_by_type_data,
    "g5_by_state":     g5_by_state_data,
    "g5_by_type":      g5_by_type_data,
    "ckt_type_totals": ckt_type_totals,
    "ckt_type_by_state": ckt_type_by_state,
    "idlc_by_state":   idlc_by_state_data,
    "switches": df_to_cols(sw_df.rename(columns={"Switch Clli":"SWITCH_CLLI"}).fillna(""),
                           ["SWITCH_CLLI","switch_name","sw_type","clli_status",
                           "state","area","region","host_remote","host_clli","decom_plan",
                           "proposed_cutover","circuits","g5_needed","g5_mig","idlc_systems","annual_savings","est_savings"]),
    "sw_match": df_to_cols(sw_match, ["SWITCH_CLLI","switch_name","sw_type","state","area",
                           "cable pair matched","cable pair unmatched","circuits in lfacs only",
                           "wtns in switch os only","recon_total"]),
    "savings": df_to_cols(sav_df.rename(columns={"Switch Clli":"SWITCH_CLLI"}).fillna(""),
                           ["SWITCH_CLLI","switch_name","state","area","decom_plan","annual_savings","est_savings"]),
    "deps":         dep_df.to_dict("records"),
    "host_summary": host_summary.to_dict("records"),
    "sw_match_dict":  sw_match_dict,
    "sw_ckt_dict":    sw_ckt_dict,
}
data_json = json.dumps(DATA, default=str)
print(f"Data size: {len(data_json)/1024/1024:.2f} MB")

# ── HTML Template ──────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ILEC Switch Consolidation Dashboard</title>
__PLOTLY_SCRIPT__
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f6f9;color:#212529;}
.hdr{background:linear-gradient(135deg,#0d1b2a 0%,#1a3a5c 100%);color:#fff;padding:18px 28px;display:flex;align-items:center;justify-content:space-between;}
.hdr h1{font-size:1.35rem;font-weight:700;letter-spacing:.3px;}
.hdr .sub{font-size:.78rem;opacity:.75;margin-top:3px;}
.tabs{background:#fff;border-bottom:2px solid #dee2e6;padding:0 24px;display:flex;gap:0;overflow-x:auto;}
.tab-btn{background:none;border:none;border-bottom:3px solid transparent;padding:12px 18px;cursor:pointer;font-size:.82rem;font-weight:500;color:#6c757d;white-space:nowrap;transition:all .15s;}
.tab-btn:hover{color:#0d6efd;}
.tab-btn.active{color:#0d6efd;border-bottom-color:#0d6efd;}
.tab-content{display:none;padding:22px 24px;}
.tab-content.active{display:block;}
.page{max-width:1400px;margin:0 auto;}
.section-title{font-size:.95rem;font-weight:700;color:#1a3a5c;margin:18px 0 10px;padding-bottom:5px;border-bottom:2px solid #e9ecef;}
.kpi-row,.kpi-row-4,.kpi-row-5,.kpi-row-6{display:grid;gap:14px;margin-bottom:18px;}
.kpi-row{grid-template-columns:repeat(3,1fr);}
.kpi-row-4{grid-template-columns:repeat(4,1fr);}
.kpi-row-5{grid-template-columns:repeat(5,1fr);}
.kpi-row-6{grid-template-columns:repeat(6,1fr);}
@media(max-width:900px){.kpi-row,.kpi-row-4,.kpi-row-5,.kpi-row-6{grid-template-columns:repeat(2,1fr);}}
.kpi-card{background:#fff;border-radius:8px;padding:16px 18px;box-shadow:0 1px 4px rgba(0,0,0,.08);border-left:4px solid #dee2e6;}
.kpi-card.c-blue{border-left-color:#0d6efd;}
.kpi-card.c-green{border-left-color:#198754;}
.kpi-card.c-orange{border-left-color:#fd7e14;}
.kpi-card.c-purple{border-left-color:#6f42c1;}
.kpi-card.c-red{border-left-color:#dc3545;}
.kpi-card.c-teal{border-left-color:#20c997;}
.kpi-label{font-size:.72rem;text-transform:uppercase;letter-spacing:.5px;color:#6c757d;margin-bottom:4px;}
.kpi-value{font-size:1.55rem;font-weight:700;color:#212529;line-height:1.1;}
.kpi-sub{font-size:.72rem;color:#6c757d;margin-top:3px;}
.chart-row{display:grid;gap:14px;margin-bottom:14px;}
.chart-row.col2{grid-template-columns:1fr 1fr;}
.chart-row.col3{grid-template-columns:1fr 1fr 1fr;}
@media(max-width:900px){.chart-row.col2,.chart-row.col3{grid-template-columns:1fr;}}
.chart-card{background:#fff;border-radius:8px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.08);}
.chart-title{font-size:.78rem;font-weight:600;color:#495057;margin-bottom:8px;text-transform:uppercase;letter-spacing:.3px;}
.filter-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;align-items:flex-end;}
.filter-group label{display:block;font-size:.72rem;font-weight:600;color:#6c757d;margin-bottom:4px;}
.filter-select,.filter-input{border:1px solid #ced4da;border-radius:6px;padding:6px 10px;font-size:.82rem;background:#fff;color:#212529;min-width:130px;}
.filter-input{min-width:180px;}
.tbl-wrap{overflow-x:auto;max-height:460px;overflow-y:auto;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.06);}
table.data-table{width:100%;border-collapse:collapse;font-size:.8rem;background:#fff;}
table.data-table th{position:sticky;top:0;background:#f8f9fa;font-weight:600;padding:9px 12px;text-align:left;border-bottom:2px solid #dee2e6;white-space:nowrap;cursor:pointer;z-index:1;}
table.data-table th:hover{background:#e9ecef;}
table.data-table td{padding:8px 12px;border-bottom:1px solid #f0f0f0;white-space:nowrap;}
table.data-table tr:hover td{background:#f8f9fa;}
table.data-table .right{text-align:right;}
table.data-table tr.area-row td{background:#e8f0fe;font-weight:700;color:#1a3a5c;}
table.data-table tr.grand-total-row td{background:#1a3a5c;color:#fff;font-weight:700;}
.clickable{color:#0d6efd;text-decoration:underline;cursor:pointer;}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.72rem;font-weight:600;}
.badge-active{background:#d1e7dd;color:#0f5132;}
.badge-inactive{background:#f8d7da;color:#842029;}
.badge-nt{background:#cfe2ff;color:#084298;}
.badge-host{background:#d1e7dd;color:#0f5132;}
.badge-remote{background:#fff3cd;color:#664d03;}
.badge-y{background:#d1e7dd;color:#0f5132;}
.badge-n{background:#f8d7da;color:#842029;}
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;}
@media(max-width:700px){.info-grid{grid-template-columns:1fr;}}
.info-card{background:#fff;border-radius:8px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.08);}
.info-card h4{font-size:.82rem;font-weight:700;color:#1a3a5c;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #dee2e6;text-transform:uppercase;letter-spacing:.3px;}
.info-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #f0f0f0;font-size:.8rem;}
.info-row:last-child{border-bottom:none;}
.info-key{color:#6c757d;font-weight:500;}
.info-val{color:#212529;font-weight:600;text-align:right;}
.lookup-section{margin-bottom:14px;}
.lookup-input-row{display:flex;gap:10px;margin-bottom:18px;align-items:center;position:relative;}
.lookup-input{border:1px solid #ced4da;border-radius:6px;padding:8px 14px;font-size:.9rem;width:320px;}
.lookup-btn{background:#0d6efd;color:#fff;border:none;border-radius:6px;padding:8px 20px;font-size:.85rem;cursor:pointer;font-weight:600;}
.lookup-btn:hover{background:#0b5ed7;}
.ac-dropdown{position:absolute;top:100%;left:0;width:320px;background:#fff;border:1px solid #ced4da;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.12);z-index:100;max-height:260px;overflow-y:auto;display:none;}
.ac-item{padding:8px 14px;cursor:pointer;font-size:.82rem;border-bottom:1px solid #f0f0f0;}
.ac-item:last-child{border-bottom:none;}
.ac-item:hover,.ac-item.ac-active{background:#e8f0fe;}
.ac-clli{font-weight:700;color:#0d6efd;}
.ac-name{color:#6c757d;margin-left:8px;}
#lookup-result{display:none;}
.caveat{background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:10px 14px;font-size:.8rem;color:#664d03;margin-bottom:12px;}
.tbl-caption{font-size:.75rem;color:#6c757d;margin-top:6px;}
</style>
</head>
<body>
<div class="hdr">
  <div>
    <h1>ILEC Switch Consolidation Dashboard</h1>
    <div class="sub">Switch Decom Summary &middot; Snapshot: __SNAP_DATE__</div>
  </div>
</div>

<div class="tabs">
  <button class="tab-btn active" data-tab="tab-summary">Summary</button>
  <button class="tab-btn" data-tab="tab-recon">Circuit Reconciliation</button>
  <button class="tab-btn" data-tab="tab-g5">G5 Migration</button>
  <button class="tab-btn" data-tab="tab-idlc">IDLC Inventory</button>
  <button class="tab-btn" data-tab="tab-savings">Savings</button>
  <button class="tab-btn" data-tab="tab-switches">Switch Inventory</button>
  <button class="tab-btn" data-tab="tab-deps">Dependencies</button>
  <button class="tab-btn" data-tab="tab-lookup">Site Lookup</button>
</div>

<!-- ═══════════════════════════════════════════════════════ SUMMARY -->
<div id="tab-summary" class="tab-content active"><div class="page">
  <div class="section-title">Program Overview</div>
  <div class="kpi-row-5" id="sum-kpi-row"></div>

  <div class="chart-row col2">
    <div class="chart-card">
      <div class="chart-title">CLLI Status</div>
      <div id="chart-status-donut" style="height:260px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Circuits by Area &amp; Match Category</div>
      <div id="chart-area-bar" style="height:260px;"></div>
    </div>
  </div>

  <div class="section-title">Circuit Reconciliation by State</div>
  <div class="tbl-wrap">
    <table class="data-table">
      <thead><tr>
        <th>Area</th><th>State</th>
        <th class="right">Matched</th><th class="right">Unmatched</th>
        <th class="right">LFACS Only</th><th class="right">SW OS Only</th>
        <th class="right">Total</th>
      </tr></thead>
      <tbody>__PIVOT_HTML__</tbody>
    </table>
  </div>
</div></div>

<!-- ═══════════════════════════════════════════════════════ CIRCUIT RECONCILIATION -->
<div id="tab-recon" class="tab-content"><div class="page">
  <div class="section-title">Circuit Match Category</div>
  <div class="kpi-row-4" id="recon-kpi-row"></div>

  <div class="chart-row col2">
    <div class="chart-card">
      <div class="chart-title">Match Category by State</div>
      <div id="chart-recon-state" style="height:340px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Match Category by Switch Type</div>
      <div id="chart-recon-type" style="height:340px;"></div>
    </div>
  </div>

  <div class="section-title">Switch-Level Reconciliation</div>
  <div class="filter-row">
    <div class="filter-group"><label>Area</label>
      <select class="filter-select" id="recon-f-area"><option value="">All Areas</option></select></div>
    <div class="filter-group"><label>State</label>
      <select class="filter-select" id="recon-f-state"><option value="">All States</option></select></div>
    <div class="filter-group"><label>Switch Type</label>
      <select class="filter-select" id="recon-f-type"><option value="">All Types</option></select></div>
    <div class="filter-group"><label>Search CLLI</label>
      <input class="filter-input" id="recon-f-id" placeholder="CLLI..."></div>
  </div>
  <div class="tbl-wrap">
    <table class="data-table" id="recon-tbl">
      <thead><tr>
        <th>SWITCH CLLI</th><th>Switch Name</th><th>State</th><th>Type</th>
        <th class="right">Matched</th><th class="right">Unmatched</th>
        <th class="right">LFACS Only</th><th class="right">SW OS Only</th>
        <th class="right">Total</th>
      </tr></thead>
      <tbody id="recon-tbl-body"></tbody>
    </table>
  </div>
  <div class="tbl-caption" id="recon-caption"></div>
</div></div>

<!-- ═══════════════════════════════════════════════════════ G5 MIGRATION -->
<div id="tab-g5" class="tab-content"><div class="page">
  <div class="section-title">G5 Migration Eligibility</div>
  <div class="kpi-row" id="g5-kpi-row"></div>

  <div class="chart-row col3">
    <div class="chart-card">
      <div class="chart-title">G5 Eligibility (Circuits)</div>
      <div id="chart-g5-donut" style="height:260px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">G5 Migratable Circuits by State</div>
      <div id="chart-g5-state" style="height:260px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">G5 Circuits by Switch Type</div>
      <div id="chart-g5-type" style="height:260px;"></div>
    </div>
  </div>

  <div class="section-title">Switch-Level G5 Detail</div>
  <div class="filter-row">
    <div class="filter-group"><label>State</label>
      <select class="filter-select" id="g5-f-state"><option value="">All States</option></select></div>
    <div class="filter-group"><label>G5 Eligible</label>
      <select class="filter-select" id="g5-f-elig">
        <option value="">All</option><option value="Y">Y - Migratable</option><option value="N">N - Ineligible</option>
      </select></div>
    <div class="filter-group"><label>Search CLLI</label>
      <input class="filter-input" id="g5-f-id" placeholder="CLLI..."></div>
  </div>
  <div class="tbl-wrap">
    <table class="data-table" id="g5-tbl">
      <thead><tr>
        <th>SWITCH CLLI</th><th>Switch Name</th><th>State</th><th>Type</th>
        <th class="right">Total Circuits</th><th class="right">G5 Migratable</th>
        <th class="right">G5 Ineligible</th><th class="right">G5 Needed</th>
      </tr></thead>
      <tbody id="g5-tbl-body"></tbody>
    </table>
  </div>
  <div class="tbl-caption" id="g5-caption"></div>
</div></div>

<!-- ═══════════════════════════════════════════════════════ IDLC INVENTORY -->
<div id="tab-idlc" class="tab-content"><div class="page">
  <div class="section-title">IDLC &amp; Circuit Type Inventory</div>
  <div class="kpi-row-4" id="idlc-kpi-row"></div>

  <div class="chart-row col2">
    <div class="chart-card">
      <div class="chart-title">Circuit Type Split</div>
      <div id="chart-idlc-donut" style="height:280px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">IDLC Systems by State</div>
      <div id="chart-idlc-state" style="height:280px;"></div>
    </div>
  </div>

  <div class="section-title">Switch-Level IDLC Detail</div>
  <div class="filter-row">
    <div class="filter-group"><label>State</label>
      <select class="filter-select" id="idlc-f-state"><option value="">All States</option></select></div>
    <div class="filter-group"><label>Search CLLI</label>
      <input class="filter-input" id="idlc-f-id" placeholder="CLLI..."></div>
  </div>
  <div class="tbl-wrap">
    <table class="data-table">
      <thead><tr>
        <th>SWITCH CLLI</th><th>Switch Name</th><th>State</th><th>Type</th>
        <th class="right">IDLC Systems</th><th class="right">Total Circuits</th>
      </tr></thead>
      <tbody id="idlc-tbl-body"></tbody>
    </table>
  </div>
  <div class="tbl-caption" id="idlc-caption"></div>
</div></div>

<!-- ═══════════════════════════════════════════════════════ SAVINGS -->
<div id="tab-savings" class="tab-content"><div class="page">
  <div class="section-title">Annual Power Savings</div>
  <div class="caveat" id="savings-caveat"></div>
  <div class="kpi-row" id="savings-kpi-row"></div>
  <div class="chart-card" style="margin-bottom:14px;">
    <div class="chart-title">Top Switches by Annual Savings</div>
    <div id="chart-savings-bar" style="height:380px;"></div>
  </div>
  <div class="filter-row">
    <div class="filter-group"><label>State</label>
      <select class="filter-select" id="sav-f-state"><option value="">All States</option></select></div>
    <div class="filter-group"><label>Search CLLI / Name</label>
      <input class="filter-input" id="sav-f-id" placeholder="CLLI or name..."></div>
  </div>
  <div class="tbl-wrap">
    <table class="data-table">
      <thead><tr>
        <th>SWITCH CLLI</th><th>Switch Name</th><th>State</th><th>Area</th>
        <th>Decom Plan</th><th class="right">Est. Annual Savings ($)</th><th class="right">Annual Savings ($)</th>
      </tr></thead>
      <tbody id="savings-tbl-body"></tbody>
    </table>
  </div>
  <div class="tbl-caption" id="savings-caption"></div>
</div></div>

<!-- ═══════════════════════════════════════════════════════ SWITCH INVENTORY -->
<div id="tab-switches" class="tab-content"><div class="page">
  <div class="section-title">Switch Inventory</div>
  <div class="kpi-row-4" id="sw-kpi-row"></div>
  <div class="chart-row col2">
    <div class="chart-card">
      <div class="chart-title">Switch Count by Type</div>
      <div id="chart-sw-type" style="height:300px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Host vs Remote</div>
      <div id="chart-sw-role" style="height:300px;"></div>
    </div>
  </div>
  <div class="filter-row">
    <div class="filter-group"><label>Area</label>
      <select class="filter-select" id="sw-f-area"><option value="">All Areas</option></select></div>
    <div class="filter-group"><label>State</label>
      <select class="filter-select" id="sw-f-state"><option value="">All States</option></select></div>
    <div class="filter-group"><label>Status</label>
      <select class="filter-select" id="sw-f-status"><option value="">All Statuses</option></select></div>
    <div class="filter-group"><label>Type</label>
      <select class="filter-select" id="sw-f-type"><option value="">All Types</option></select></div>
    <div class="filter-group"><label>Search CLLI</label>
      <input class="filter-input" id="sw-f-id" placeholder="CLLI or name..."></div>
  </div>
  <div class="tbl-wrap">
    <table class="data-table">
      <thead><tr>
        <th>SWITCH CLLI</th><th>Switch Name</th><th>State</th><th>Area</th>
        <th>Type</th><th>Status</th><th>Role</th>
        <th class="right">Circuits</th><th>Decom Plan</th><th>Proposed Cutover</th>
      </tr></thead>
      <tbody id="sw-tbl-body"></tbody>
    </table>
  </div>
  <div class="tbl-caption" id="sw-caption"></div>
</div></div>

<!-- ═══════════════════════════════════════════════════════ DEPENDENCIES -->
<div id="tab-deps" class="tab-content"><div class="page">
  <div class="section-title">Host &rarr; Remote Dependencies</div>
  <div class="kpi-row" id="deps-kpi-row"></div>

  <div class="section-title">Remote Switches</div>
  <div class="filter-row">
    <div class="filter-group"><label>State</label>
      <select class="filter-select" id="dep-f-state"><option value="">All States</option></select></div>
    <div class="filter-group"><label>Type</label>
      <select class="filter-select" id="dep-f-type"><option value="">All Types</option></select></div>
    <div class="filter-group"><label>Search</label>
      <input class="filter-input" id="dep-f-id" placeholder="Remote or host CLLI..."></div>
  </div>
  <div class="tbl-wrap">
    <table class="data-table">
      <thead><tr>
        <th>Remote CLLI</th><th>Remote Name</th><th>State</th><th>Type</th>
        <th>Role</th><th>Host CLLI</th>
      </tr></thead>
      <tbody id="dep-tbl-body"></tbody>
    </table>
  </div>
  <div class="tbl-caption" id="dep-caption"></div>

  <div class="section-title" style="margin-top:20px;">Host Switches with Remotes</div>
  <div class="tbl-wrap">
    <table class="data-table">
      <thead><tr>
        <th>Host CLLI</th><th>Host Name</th><th>State</th><th>Status</th>
        <th class="right">Remote Count</th>
      </tr></thead>
      <tbody id="host-tbl-body"></tbody>
    </table>
  </div>
</div></div>

<!-- ═══════════════════════════════════════════════════════ SITE LOOKUP -->
<div id="tab-lookup" class="tab-content"><div class="page">
  <div class="section-title">Site Lookup</div>
  <div class="lookup-input-row">
    <input class="lookup-input" id="lookup-q" placeholder="Type CLLI or switch name..." autocomplete="off">
    <button class="lookup-btn" id="lookup-btn">Search</button>
    <div class="ac-dropdown" id="ac-dropdown"></div>
  </div>
  <div id="lookup-result">
    <div class="info-grid">
      <div class="info-card">
        <h4>Switch Details</h4>
        <div id="lookup-switch-card"></div>
      </div>
      <div class="info-card">
        <h4>Circuit Summary</h4>
        <div id="lookup-circuit-card"></div>
      </div>
    </div>
    <div class="section-title">Match Category Breakdown</div>
    <div class="tbl-wrap" style="margin-bottom:14px;">
      <table class="data-table">
        <thead><tr><th>Match Category</th><th class="right">Circuits</th></tr></thead>
        <tbody id="lookup-match-body"></tbody>
      </table>
    </div>
    <div class="section-title">Circuit Type Breakdown</div>
    <div class="tbl-wrap">
      <table class="data-table">
        <thead><tr><th>Circuit Type</th><th class="right">Circuits</th></tr></thead>
        <tbody id="lookup-ckt-body"></tbody>
      </table>
    </div>
  </div>
  <div id="lookup-notfound" style="display:none;color:#dc3545;padding:16px 0;font-weight:600;">
    Switch CLLI not found in dataset.
  </div>
</div></div>

__PLOTLY_SCRIPT__
<script>
const DATA = __DATA_JSON__;
const CFG  = {responsive:true,displayModeBar:false};
const LB   = {paper_bgcolor:"#fff",plot_bgcolor:"#fff",margin:{t:10,b:10,l:10,r:10}};
const S    = DATA.summary;

const MATCH_CATS   = ["cable pair matched","cable pair unmatched","circuits in lfacs only","wtns in switch os only"];
const MATCH_LABELS = ["Matched","Unmatched","LFACS Only","SW OS Only"];
const MATCH_COLORS = ["#198754","#fd7e14","#0d6efd","#dc3545"];
const CKT_COLORS   = {"Copper":"#8B4513","OLT-FTTP":"#0d6efd","PG - Integrated":"#198754"};

function fmt(n){
  if(n===null||n===undefined||n==="")return "—";
  const x=parseFloat(n);
  if(isNaN(x))return String(n);
  return x.toLocaleString();
}
function fmtDollar(n){
  const x=parseFloat(n);
  if(isNaN(x)||x===0)return "—";
  if(x>=1e6)return "$"+(x/1e6).toFixed(1)+"M";
  return "$"+x.toLocaleString(undefined,{minimumFractionDigits:0,maximumFractionDigits:0});
}
function statusBadge(s){
  if(!s)return "";
  const lc=s.toLowerCase();
  if(lc.includes("active")&&!lc.includes("in"))return '<span class="badge badge-active">'+s+"</span>";
  return '<span class="badge badge-inactive">'+s+"</span>";
}
function roleBadge(r){
  if(!r)return "";
  if(r==="Host or Base switch")return '<span class="badge badge-host">Host</span>';
  return '<span class="badge badge-remote">Remote</span>';
}

/* ── Tab switching ── */
const _inited={};
document.querySelectorAll(".tab-btn").forEach(btn=>{
  btn.addEventListener("click",function(){
    const id=this.dataset.tab;
    document.querySelectorAll(".tab-content").forEach(t=>t.classList.remove("active"));
    document.querySelectorAll(".tab-btn").forEach(b=>b.classList.remove("active"));
    document.getElementById(id).classList.add("active");
    this.classList.add("active");
    if(!_inited[id]){_inited[id]=true; initTab(id);}
  });
});

function initTab(id){
  if(id==="tab-recon")   initRecon();
  else if(id==="tab-g5") initG5();
  else if(id==="tab-idlc")    initIDLC();
  else if(id==="tab-savings") initSavings();
  else if(id==="tab-switches")initSwitches();
  else if(id==="tab-deps")    initDeps();
}

/* ── SUMMARY ── */
function initSummary(){
  const kpi=[
    {label:"Total Switches",  val:fmt(S.total_switches), sub:"CLLIs",             cls:"c-blue"},
    {label:"Total Circuits",  val:fmt(S.total_circuits), sub:"Circuit records",   cls:"c-green"},
    {label:"Match Rate",      val:S.match_rate+"%",      sub:"Cable pair matched",cls:"c-teal"},
    {label:"G5 Migratable",   val:S.g5_pct+"%",          sub:"of circuits",       cls:"c-orange"},
    {label:"Decom Plan (Y)",  val:fmt(S.decom_y),         sub:"switches",          cls:"c-purple"},
  ];
  const row=document.getElementById("sum-kpi-row");
  kpi.forEach(k=>{
    row.innerHTML+='<div class="kpi-card '+k.cls+'"><div class="kpi-label">'+k.label+'</div>'
      +'<div class="kpi-value">'+k.val+'</div><div class="kpi-sub">'+k.sub+'</div></div>';
  });

  // Status donut
  const sc=S.status_counts;
  const slabels=Object.keys(sc), svals=Object.values(sc);
  const scols=["#198754","#fd7e14","#0d6efd","#dc3545","#6f42c1","#20c997"];
  Plotly.newPlot("chart-status-donut",[{
    type:"pie",hole:.45,labels:slabels,values:svals,
    marker:{colors:scols.slice(0,slabels.length)},
    textinfo:"label+percent",hovertemplate:"%{label}: %{value:,}<extra></extra>"
  }],Object.assign({},LB,{showlegend:true,legend:{orientation:"v",x:1,y:.5}}),CFG);

  // Area bar
  const areas=[...new Set(DATA.match_by_state.map(r=>{
    const sw=DATA.switches;
    const idx=sw.state.indexOf(r.state);
    return idx>=0?sw.area[idx]:"";
  }))].filter(Boolean);
  const areaData={};
  DATA.match_by_state.forEach(r=>{
    const swS=DATA.switches;
    const idx=swS.state.indexOf(r.state);
    const area=idx>=0?swS.area[idx]:"Unknown";
    if(!areaData[area])areaData[area]={};
    MATCH_CATS.forEach(cat=>{areaData[area][cat]=(areaData[area][cat]||0)+(r[cat]||0);});
  });
  const areaLabels=Object.keys(areaData);
  const areaTraces=MATCH_CATS.map((cat,i)=>({
    name:MATCH_LABELS[i],type:"bar",
    x:areaLabels,y:areaLabels.map(a=>areaData[a][cat]||0),
    marker:{color:MATCH_COLORS[i]},
    hovertemplate:MATCH_LABELS[i]+": %{y:,}<extra>%{x}</extra>"
  }));
  Plotly.newPlot("chart-area-bar",areaTraces,
    Object.assign({},LB,{barmode:"stack",legend:{orientation:"h",y:-0.15}}),CFG);
}

/* ── CIRCUIT RECONCILIATION ── */
function initRecon(){
  // KPI row
  const unmatched=S.total_circuits-S.matched;
  const lfacs=DATA.match_by_state.reduce((a,r)=>a+(r["circuits in lfacs only"]||0),0);
  const sw_only=DATA.match_by_state.reduce((a,r)=>a+(r["wtns in switch os only"]||0),0);
  const kpis=[
    {label:"Matched",    val:fmt(S.matched),   sub:"cable pair matched", cls:"c-green"},
    {label:"Unmatched",  val:fmt(unmatched),   sub:"cable pair unmatched",cls:"c-orange"},
    {label:"LFACS Only", val:fmt(lfacs),       sub:"not in switch OS",   cls:"c-blue"},
    {label:"SW OS Only", val:fmt(sw_only),     sub:"not in LFACS",       cls:"c-red"},
  ];
  const row=document.getElementById("recon-kpi-row");
  kpis.forEach(k=>{
    row.innerHTML+='<div class="kpi-card '+k.cls+'"><div class="kpi-label">'+k.label+'</div>'
      +'<div class="kpi-value">'+k.val+'</div><div class="kpi-sub">'+k.sub+'</div></div>';
  });

  // Match by state chart (horizontal stacked)
  const states=DATA.match_by_state.map(r=>r.state);
  const stateTraces=MATCH_CATS.map((cat,i)=>({
    name:MATCH_LABELS[i],type:"bar",orientation:"h",
    y:states,x:DATA.match_by_state.map(r=>r[cat]||0),
    marker:{color:MATCH_COLORS[i]},
    hovertemplate:MATCH_LABELS[i]+": %{x:,}<extra>%{y}</extra>"
  }));
  Plotly.newPlot("chart-recon-state",stateTraces,
    Object.assign({},LB,{barmode:"stack",margin:{t:10,b:30,l:80,r:10},
    legend:{orientation:"h",y:-0.12}}),CFG);

  // Match by type chart
  const types=DATA.match_by_type.map(r=>r.sw_type);
  const typeTraces=MATCH_CATS.map((cat,i)=>({
    name:MATCH_LABELS[i],type:"bar",orientation:"h",
    y:types,x:DATA.match_by_type.map(r=>r[cat]||0),
    marker:{color:MATCH_COLORS[i]},
    hovertemplate:MATCH_LABELS[i]+": %{x:,}<extra>%{y}</extra>"
  }));
  Plotly.newPlot("chart-recon-type",typeTraces,
    Object.assign({},LB,{barmode:"stack",margin:{t:10,b:30,l:130,r:10},
    legend:{orientation:"h",y:-0.12}}),CFG);

  // Populate filters
  const SM=DATA.sw_match;
  populateSelect("recon-f-area", [...new Set(SM.area.filter(Boolean))].sort());
  populateSelect("recon-f-state",[...new Set(SM.state.filter(Boolean))].sort());
  populateSelect("recon-f-type", [...new Set(SM.sw_type.filter(Boolean))].sort());
  document.getElementById("recon-f-area").addEventListener("change",renderReconTable);
  document.getElementById("recon-f-state").addEventListener("change",renderReconTable);
  document.getElementById("recon-f-type").addEventListener("change",renderReconTable);
  document.getElementById("recon-f-id").addEventListener("input",renderReconTable);
  renderReconTable();
}

function renderReconTable(){
  const fArea  =document.getElementById("recon-f-area").value;
  const fState =document.getElementById("recon-f-state").value;
  const fType  =document.getElementById("recon-f-type").value;
  const fId    =document.getElementById("recon-f-id").value.toLowerCase();
  const SM=DATA.sw_match;
  const n=SM.SWITCH_CLLI.length;
  const parts=[];let count=0;
  for(let i=0;i<n;i++){
    if(fArea  && SM.area[i]!==fArea)continue;
    if(fState && SM.state[i]!==fState)continue;
    if(fType  && SM.sw_type[i]!==fType)continue;
    if(fId    && !String(SM.SWITCH_CLLI[i]).toLowerCase().includes(fId))continue;
    count++;
    const matched=SM["cable pair matched"][i]||0;
    const unmatched=SM["cable pair unmatched"][i]||0;
    const lfacs=SM["circuits in lfacs only"][i]||0;
    const sw_only=SM["wtns in switch os only"][i]||0;
    const total=SM.recon_total[i]||0;
    parts.push('<tr><td><span class="clickable" data-clli="'+SM.SWITCH_CLLI[i]+'">'+SM.SWITCH_CLLI[i]+'</span></td>'
      +'<td>'+SM.switch_name[i]+'</td><td>'+SM.state[i]+'</td><td>'+SM.sw_type[i]+'</td>'
      +'<td class="right">'+fmt(matched)+'</td><td class="right">'+fmt(unmatched)+'</td>'
      +'<td class="right">'+fmt(lfacs)+'</td><td class="right">'+fmt(sw_only)+'</td>'
      +'<td class="right"><strong>'+fmt(total)+'</strong></td></tr>');
  }
  document.getElementById("recon-tbl-body").innerHTML=parts.join("");
  document.getElementById("recon-caption").textContent=count.toLocaleString()+" switches";
  document.querySelectorAll("#recon-tbl-body .clickable").forEach(el=>{
    el.addEventListener("click",function(){gotoLookup(this.dataset.clli);});
  });
}

/* ── G5 MIGRATION ── */
function initG5(){
  const g5_inelig=S.total_circuits-S.g5_y;
  const kpis=[
    {label:"G5 Migratable",  val:fmt(S.g5_y),      sub:"circuits (Y)", cls:"c-green"},
    {label:"G5 Ineligible",  val:fmt(g5_inelig),    sub:"circuits (N)", cls:"c-red"},
    {label:"G5 Migratable %",val:S.g5_pct+"%",      sub:"of all circuits",cls:"c-teal"},
  ];
  const row=document.getElementById("g5-kpi-row");
  kpis.forEach(k=>{
    row.innerHTML+='<div class="kpi-card '+k.cls+'"><div class="kpi-label">'+k.label+'</div>'
      +'<div class="kpi-value">'+k.val+'</div><div class="kpi-sub">'+k.sub+'</div></div>';
  });

  // Donut
  Plotly.newPlot("chart-g5-donut",[{
    type:"pie",hole:.45,labels:["Migratable","Ineligible"],
    values:[S.g5_y,S.total_circuits-S.g5_y],
    marker:{colors:["#198754","#dc3545"]},
    textinfo:"label+percent",hovertemplate:"%{label}: %{value:,}<extra></extra>"
  }],Object.assign({},LB,{showlegend:true}),CFG);

  // G5 by state
  const gStates=DATA.g5_by_state.map(r=>r.state);
  Plotly.newPlot("chart-g5-state",[
    {name:"Migratable",type:"bar",x:gStates,y:DATA.g5_by_state.map(r=>r.migratable||0),
     marker:{color:"#198754"},hovertemplate:"Migratable: %{y:,}<extra>%{x}</extra>"},
    {name:"Ineligible", type:"bar",x:gStates,y:DATA.g5_by_state.map(r=>r.ineligible||0),
     marker:{color:"#dc3545"},hovertemplate:"Ineligible: %{y:,}<extra>%{x}</extra>"},
  ],Object.assign({},LB,{barmode:"stack",legend:{orientation:"h",y:-0.15}}),CFG);

  // G5 by switch type
  const gTypes=DATA.g5_by_type.slice(0,10).map(r=>r.sw_type);
  Plotly.newPlot("chart-g5-type",[
    {name:"Migratable",type:"bar",x:gTypes,y:DATA.g5_by_type.slice(0,10).map(r=>r.migratable||0),
     marker:{color:"#198754"},hovertemplate:"Migratable: %{y:,}<extra>%{x}</extra>"},
    {name:"Ineligible", type:"bar",x:gTypes,y:DATA.g5_by_type.slice(0,10).map(r=>r.ineligible||0),
     marker:{color:"#dc3545"},hovertemplate:"Ineligible: %{y:,}<extra>%{x}</extra>"},
  ],Object.assign({},LB,{barmode:"stack",legend:{orientation:"h",y:-0.15},
    xaxis:{tickangle:-30}}),CFG);

  // Populate filters
  const SW=DATA.switches;
  populateSelect("g5-f-state",[...new Set(SW.state.filter(Boolean))].sort());
  document.getElementById("g5-f-state").addEventListener("change",renderG5Table);
  document.getElementById("g5-f-elig").addEventListener("change",renderG5Table);
  document.getElementById("g5-f-id").addEventListener("input",renderG5Table);
  renderG5Table();
}

function renderG5Table(){
  const fState=document.getElementById("g5-f-state").value;
  const fElig =document.getElementById("g5-f-elig").value;
  const fId   =document.getElementById("g5-f-id").value.toLowerCase();
  const SW=DATA.switches;
  const n=SW.SWITCH_CLLI.length;
  const parts=[];let count=0;
  for(let i=0;i<n;i++){
    if(fState && SW.state[i]!==fState)continue;
    if(fId    && !String(SW.SWITCH_CLLI[i]).toLowerCase().includes(fId))continue;
    const mig=parseInt(SW.g5_mig[i])||0;
    const total=parseInt(SW.circuits[i])||0;
    const inelig=total-mig;
    if(fElig==="Y"&&mig===0)continue;
    if(fElig==="N"&&inelig===0)continue;
    count++;
    parts.push('<tr><td><span class="clickable" data-clli="'+SW.SWITCH_CLLI[i]+'">'+SW.SWITCH_CLLI[i]+'</span></td>'
      +'<td>'+SW.switch_name[i]+'</td><td>'+SW.state[i]+'</td><td>'+SW.sw_type[i]+'</td>'
      +'<td class="right">'+fmt(total)+'</td><td class="right">'+fmt(mig)+'</td>'
      +'<td class="right">'+fmt(inelig)+'</td><td class="right">'+fmt(SW.g5_needed[i])+'</td></tr>');
  }
  document.getElementById("g5-tbl-body").innerHTML=parts.join("");
  document.getElementById("g5-caption").textContent=count.toLocaleString()+" switches";
  document.querySelectorAll("#g5-tbl-body .clickable").forEach(el=>{
    el.addEventListener("click",function(){gotoLookup(this.dataset.clli);});
  });
}

/* ── IDLC INVENTORY ── */
function initIDLC(){
  const cktT=DATA.ckt_type_totals;
  const copper=cktT["Copper"]||0, fttp=cktT["OLT-FTTP"]||0, pg=cktT["PG - Integrated"]||0;
  const kpis=[
    {label:"Total IDLC Systems", val:fmt(S.total_idlc),     sub:"across all switches", cls:"c-blue"},
    {label:"Copper Circuits",    val:fmt(copper),            sub:"circuit records",     cls:"c-orange"},
    {label:"OLT-FTTP Circuits",  val:fmt(fttp),              sub:"circuit records",     cls:"c-teal"},
    {label:"PG-Integrated",      val:fmt(pg),                sub:"circuit records",     cls:"c-green"},
  ];
  const row=document.getElementById("idlc-kpi-row");
  kpis.forEach(k=>{
    row.innerHTML+='<div class="kpi-card '+k.cls+'"><div class="kpi-label">'+k.label+'</div>'
      +'<div class="kpi-value">'+k.val+'</div><div class="kpi-sub">'+k.sub+'</div></div>';
  });

  // Donut
  const cktLabels=Object.keys(cktT), cktVals=Object.values(cktT);
  const cktCols=cktLabels.map(l=>CKT_COLORS[l]||"#6c757d");
  Plotly.newPlot("chart-idlc-donut",[{
    type:"pie",hole:.45,labels:cktLabels,values:cktVals,
    marker:{colors:cktCols},textinfo:"label+percent",
    hovertemplate:"%{label}: %{value:,}<extra></extra>"
  }],Object.assign({},LB,{showlegend:true}),CFG);

  // IDLC by state
  const idlcStates=DATA.idlc_by_state.map(r=>r.state);
  Plotly.newPlot("chart-idlc-state",[{
    type:"bar",x:idlcStates,y:DATA.idlc_by_state.map(r=>r.idlc_systems||0),
    marker:{color:"#0d6efd"},hovertemplate:"IDLC Systems: %{y:,}<extra>%{x}</extra>"
  }],Object.assign({},LB),CFG);

  // Filters
  const SW=DATA.switches;
  populateSelect("idlc-f-state",[...new Set(SW.state.filter(Boolean))].sort());
  document.getElementById("idlc-f-state").addEventListener("change",renderIDLCTable);
  document.getElementById("idlc-f-id").addEventListener("input",renderIDLCTable);
  renderIDLCTable();
}

function renderIDLCTable(){
  const fState=document.getElementById("idlc-f-state").value;
  const fId   =document.getElementById("idlc-f-id").value.toLowerCase();
  const SW=DATA.switches;
  const n=SW.SWITCH_CLLI.length;
  const parts=[];let count=0;
  for(let i=0;i<n;i++){
    if(fState && SW.state[i]!==fState)continue;
    if(fId    && !String(SW.SWITCH_CLLI[i]).toLowerCase().includes(fId))continue;
    count++;
    parts.push('<tr><td><span class="clickable" data-clli="'+SW.SWITCH_CLLI[i]+'">'+SW.SWITCH_CLLI[i]+'</span></td>'
      +'<td>'+SW.switch_name[i]+'</td><td>'+SW.state[i]+'</td><td>'+SW.sw_type[i]+'</td>'
      +'<td class="right">'+fmt(SW.idlc_systems[i])+'</td>'
      +'<td class="right">'+fmt(SW.circuits[i])+'</td></tr>');
  }
  document.getElementById("idlc-tbl-body").innerHTML=parts.join("");
  document.getElementById("idlc-caption").textContent=count.toLocaleString()+" switches";
  document.querySelectorAll("#idlc-tbl-body .clickable").forEach(el=>{
    el.addEventListener("click",function(){gotoLookup(this.dataset.clli);});
  });
}

/* ── SAVINGS ── */
function initSavings(){
  document.getElementById("savings-caveat").textContent=
    "Est. Annual Power Savings available for "+S.est_savings_pop+" switches; ANNUAL_POWER_SAVINGS available for "+S.savings_pop+" of "+S.total_switches+" switches.";
  const kpis=[
    {label:"Total Est. Annual Savings", val:fmtDollar(S.total_est_savings), sub:"("+S.est_savings_pop+" switches)", cls:"c-green"},
    {label:"Switches with Est. Savings",val:fmt(S.est_savings_pop),          sub:"of "+fmt(S.total_switches),       cls:"c-blue"},
    {label:"Avg Est. per Switch",       val:fmtDollar(S.est_savings_pop>0?S.total_est_savings/S.est_savings_pop:0),sub:"where available",cls:"c-orange"},
    {label:"Total Annual Savings",      val:fmtDollar(S.total_savings),      sub:"("+S.savings_pop+" switches)",    cls:"c-teal"},
  ];
  const row=document.getElementById("savings-kpi-row");
  row.className="kpi-row-4";
  kpis.forEach(k=>{
    row.innerHTML+='<div class="kpi-card '+k.cls+'"><div class="kpi-label">'+k.label+'</div>'
      +'<div class="kpi-value">'+k.val+'</div><div class="kpi-sub">'+k.sub+'</div></div>';
  });

  const SV=DATA.savings;
  const top=Math.min(SV.SWITCH_CLLI.length,25);
  const savLabels=SV.SWITCH_CLLI.slice(0,top);
  const estVals  =SV.est_savings.slice(0,top).map(v=>parseFloat(v)||0);
  const annVals  =SV.annual_savings.slice(0,top).map(v=>parseFloat(v)||0);
  Plotly.newPlot("chart-savings-bar",[
    {name:"Est. Annual Power Savings",type:"bar",x:savLabels,y:estVals,
     marker:{color:"#198754"},hovertemplate:"%{x}<br>Est: $%{y:,.0f}<extra></extra>"},
    {name:"Annual Power Savings",     type:"bar",x:savLabels,y:annVals,
     marker:{color:"#0d6efd"},hovertemplate:"%{x}<br>Annual: $%{y:,.0f}<extra></extra>"},
  ],Object.assign({},LB,{barmode:"group",xaxis:{tickangle:-45},yaxis:{tickformat:"$,.0f"},
    legend:{orientation:"h",y:-0.2}}),CFG);

  // Populate state filter
  const SV=DATA.savings;
  populateSelect("sav-f-state",[...new Set(SV.state.filter(Boolean))].sort());
  document.getElementById("sav-f-state").addEventListener("change",renderSavingsTable);
  document.getElementById("sav-f-id").addEventListener("input",renderSavingsTable);
  renderSavingsTable();
}

function renderSavingsTable(){
  const fState=document.getElementById("sav-f-state").value;
  const fId   =document.getElementById("sav-f-id").value.toLowerCase();
  const SV=DATA.savings;
  const n=SV.SWITCH_CLLI.length;
  const parts=[];let count=0;
  for(let i=0;i<n;i++){
    if(fState && SV.state[i]!==fState)continue;
    if(fId    && !String(SV.SWITCH_CLLI[i]).toLowerCase().includes(fId)
             && !String(SV.switch_name[i]).toLowerCase().includes(fId))continue;
    count++;
    parts.push('<tr><td><span class="clickable" data-clli="'+SV.SWITCH_CLLI[i]+'">'+SV.SWITCH_CLLI[i]+'</span></td>'
      +'<td>'+SV.switch_name[i]+'</td><td>'+SV.state[i]+'</td><td>'+SV.area[i]+'</td>'
      +'<td>'+SV.decom_plan[i]+'</td>'
      +'<td class="right">'+fmtDollar(SV.est_savings[i])+'</td>'
      +'<td class="right">'+fmtDollar(SV.annual_savings[i])+'</td></tr>');
  }
  document.getElementById("savings-tbl-body").innerHTML=parts.join("");
  document.getElementById("savings-caption").textContent=count.toLocaleString()+" switches";
  document.querySelectorAll("#savings-tbl-body .clickable").forEach(el=>{
    el.addEventListener("click",function(){gotoLookup(this.dataset.clli);});
  });
}

/* ── SWITCH INVENTORY ── */
function initSwitches(){
  const SW=DATA.switches;
  const ntActive   =SW.clli_status.filter(s=>s==="NT-Active").length;
  const nonNtActive=SW.clli_status.filter(s=>s==="Non-NT-Active").length;
  const nonNtInact =SW.clli_status.filter(s=>s==="Non-NT-InActive").length;
  const kpis=[
    {label:"Total Switches",    val:fmt(S.total_switches), sub:"unique CLLIs",      cls:"c-blue"},
    {label:"NT Active",         val:fmt(ntActive),          sub:"switches",          cls:"c-green"},
    {label:"Non-NT Active",     val:fmt(nonNtActive),       sub:"switches",          cls:"c-orange"},
    {label:"Non-NT InActive",   val:fmt(nonNtInact),        sub:"switches",          cls:"c-red"},
  ];
  const row=document.getElementById("sw-kpi-row");
  kpis.forEach(k=>{
    row.innerHTML+='<div class="kpi-card '+k.cls+'"><div class="kpi-label">'+k.label+'</div>'
      +'<div class="kpi-value">'+k.val+'</div><div class="kpi-sub">'+k.sub+'</div></div>';
  });

  // Switch type bar
  const typeCounts={};
  SW.sw_type.forEach(t=>{if(t)typeCounts[t]=(typeCounts[t]||0)+1;});
  const tEntries=Object.entries(typeCounts).sort((a,b)=>b[1]-a[1]);
  Plotly.newPlot("chart-sw-type",[{
    type:"bar",orientation:"h",y:tEntries.map(e=>e[0]),x:tEntries.map(e=>e[1]),
    marker:{color:"#0d6efd"},hovertemplate:"%{y}: %{x:,}<extra></extra>"
  }],Object.assign({},LB,{margin:{t:10,b:30,l:150,r:10}}),CFG);

  // Host vs Remote donut
  const hostCnt =SW.host_remote.filter(r=>r==="Host or Base switch").length;
  const remCnt  =SW.host_remote.filter(r=>r.includes("Remote")).length;
  const altCnt  =SW.host_remote.filter(r=>r==="Alternate CLLI").length;
  Plotly.newPlot("chart-sw-role",[{
    type:"pie",hole:.45,
    labels:["Host","Remote","Alternate"],values:[hostCnt,remCnt,altCnt],
    marker:{colors:["#198754","#fd7e14","#6f42c1"]},
    textinfo:"label+value",hovertemplate:"%{label}: %{value:,}<extra></extra>"
  }],Object.assign({},LB,{showlegend:true}),CFG);

  // Filters
  populateSelect("sw-f-area",  [...new Set(SW.area.filter(Boolean))].sort());
  populateSelect("sw-f-state", [...new Set(SW.state.filter(Boolean))].sort());
  populateSelect("sw-f-status",[...new Set(SW.clli_status.filter(Boolean))].sort());
  populateSelect("sw-f-type",  [...new Set(SW.sw_type.filter(Boolean))].sort());
  ["sw-f-area","sw-f-state","sw-f-status","sw-f-type"].forEach(id=>{
    document.getElementById(id).addEventListener("change",renderSwitchTable);
  });
  document.getElementById("sw-f-id").addEventListener("input",renderSwitchTable);
  renderSwitchTable();
}

function renderSwitchTable(){
  const fArea  =document.getElementById("sw-f-area").value;
  const fState =document.getElementById("sw-f-state").value;
  const fStatus=document.getElementById("sw-f-status").value;
  const fType  =document.getElementById("sw-f-type").value;
  const fId    =document.getElementById("sw-f-id").value.toLowerCase();
  const SW=DATA.switches;
  const n=SW.SWITCH_CLLI.length;
  const parts=[];let count=0;
  for(let i=0;i<n;i++){
    if(fArea   && SW.area[i]!==fArea)continue;
    if(fState  && SW.state[i]!==fState)continue;
    if(fStatus && SW.clli_status[i]!==fStatus)continue;
    if(fType   && SW.sw_type[i]!==fType)continue;
    if(fId     && !String(SW.SWITCH_CLLI[i]).toLowerCase().includes(fId)
               && !String(SW.switch_name[i]).toLowerCase().includes(fId))continue;
    count++;
    const decom=SW.decom_plan[i]==="Y"?'<span class="badge badge-y">Y</span>':'<span class="badge badge-n">'+(SW.decom_plan[i]||"N")+'</span>';
    parts.push('<tr><td><span class="clickable" data-clli="'+SW.SWITCH_CLLI[i]+'">'+SW.SWITCH_CLLI[i]+'</span></td>'
      +'<td>'+SW.switch_name[i]+'</td><td>'+SW.state[i]+'</td><td>'+SW.area[i]+'</td>'
      +'<td>'+SW.sw_type[i]+'</td><td>'+statusBadge(SW.clli_status[i])+'</td>'
      +'<td>'+roleBadge(SW.host_remote[i])+'</td>'
      +'<td class="right">'+fmt(SW.circuits[i])+'</td>'
      +'<td>'+decom+'</td><td>'+(SW.proposed_cutover[i]||"—")+'</td></tr>');
  }
  document.getElementById("sw-tbl-body").innerHTML=parts.join("");
  document.getElementById("sw-caption").textContent=count.toLocaleString()+" switches";
  document.querySelectorAll("#sw-tbl-body .clickable").forEach(el=>{
    el.addEventListener("click",function(){gotoLookup(this.dataset.clli);});
  });
}

/* ── DEPENDENCIES ── */
function initDeps(){
  const nonSurv=DATA.deps.filter(r=>r.survivable==="Non-Survivable Remote Switch").length;
  const kpis=[
    {label:"Host Switches",      val:fmt(S.hosts),   sub:"Host or Base",            cls:"c-blue"},
    {label:"Survivable Remotes", val:fmt(S.remotes-nonSurv), sub:"Survivable Remote",cls:"c-green"},
    {label:"Non-Survivable",     val:fmt(nonSurv),   sub:"Non-Survivable Remote",   cls:"c-red"},
  ];
  const row=document.getElementById("deps-kpi-row");
  kpis.forEach(k=>{
    row.innerHTML+='<div class="kpi-card '+k.cls+'"><div class="kpi-label">'+k.label+'</div>'
      +'<div class="kpi-value">'+k.val+'</div><div class="kpi-sub">'+k.sub+'</div></div>';
  });

  // Filters
  const states=[...new Set(DATA.deps.map(r=>r.remote_state).filter(Boolean))].sort();
  const types =[...new Set(DATA.deps.map(r=>r.remote_type).filter(Boolean))].sort();
  populateSelect("dep-f-state",states);
  populateSelect("dep-f-type", types);
  document.getElementById("dep-f-state").addEventListener("change",renderDepsTable);
  document.getElementById("dep-f-type").addEventListener("change",renderDepsTable);
  document.getElementById("dep-f-id").addEventListener("input",renderDepsTable);
  renderDepsTable();

  // Host table
  const hParts=[];
  DATA.host_summary.forEach(h=>{
    hParts.push('<tr><td><span class="clickable" data-clli="'+h.host_clli+'">'+h.host_clli+'</span></td>'
      +'<td>'+(h.host_name||"")+'</td><td>'+(h.host_state||"")+'</td>'
      +'<td>'+statusBadge(h.host_status)+'</td>'
      +'<td class="right">'+h.remote_count+'</td></tr>');
  });
  document.getElementById("host-tbl-body").innerHTML=hParts.join("");
  document.querySelectorAll("#host-tbl-body .clickable").forEach(el=>{
    el.addEventListener("click",function(){gotoLookup(this.dataset.clli);});
  });
}

function renderDepsTable(){
  const fState=document.getElementById("dep-f-state").value;
  const fType =document.getElementById("dep-f-type").value;
  const fId   =document.getElementById("dep-f-id").value.toLowerCase();
  const parts=[];let count=0;
  DATA.deps.forEach(r=>{
    if(fState && r.remote_state!==fState)return;
    if(fType  && r.remote_type!==fType)return;
    if(fId    && !r.remote_clli.toLowerCase().includes(fId)
             && !r.host_clli.toLowerCase().includes(fId))return;
    count++;
    const surv=r.survivable.includes("Non-Survivable")?"Non-Surv":"Survivable";
    parts.push('<tr>'
      +'<td><span class="clickable" data-clli="'+r.remote_clli+'">'+r.remote_clli+'</span></td>'
      +'<td>'+(r.remote_name||"")+'</td><td>'+r.remote_state+'</td><td>'+r.remote_type+'</td>'
      +'<td>'+surv+'</td>'
      +'<td><span class="clickable" data-clli="'+r.host_clli+'">'+r.host_clli+'</span></td></tr>');
  });
  document.getElementById("dep-tbl-body").innerHTML=parts.join("");
  document.getElementById("dep-caption").textContent=count.toLocaleString()+" remotes";
  document.querySelectorAll("#dep-tbl-body .clickable").forEach(el=>{
    el.addEventListener("click",function(){gotoLookup(this.dataset.clli);});
  });
}

/* ── SITE LOOKUP + AUTOCOMPLETE ── */
(function(){
  const inp=document.getElementById("lookup-q");
  const dd =document.getElementById("ac-dropdown");
  const SW =DATA.switches;
  let acIdx=-1;

  inp.addEventListener("input",function(){
    const val=this.value.trim().toUpperCase();
    dd.innerHTML=""; acIdx=-1;
    if(!val){dd.style.display="none";return;}
    const matches=[];
    for(let i=0;i<SW.SWITCH_CLLI.length;i++){
      const clli=String(SW.SWITCH_CLLI[i]).toUpperCase();
      const name=String(SW.switch_name[i]).toUpperCase();
      if(clli.includes(val)||name.includes(val)){
        matches.push({clli:SW.SWITCH_CLLI[i],name:SW.switch_name[i]});
        if(matches.length>=12)break;
      }
    }
    if(!matches.length){dd.style.display="none";return;}
    matches.forEach(function(m,i){
      const div=document.createElement("div");
      div.className="ac-item";
      div.innerHTML='<span class="ac-clli">'+m.clli+'</span><span class="ac-name">'+m.name+'</span>';
      div.addEventListener("mousedown",function(e){
        e.preventDefault();
        inp.value=m.clli;
        dd.style.display="none";
        doLookup();
      });
      dd.appendChild(div);
    });
    dd.style.display="block";
  });

  inp.addEventListener("keydown",function(e){
    const items=dd.querySelectorAll(".ac-item");
    if(e.key==="ArrowDown"){
      e.preventDefault();
      acIdx=Math.min(acIdx+1,items.length-1);
      items.forEach(function(el,i){el.classList.toggle("ac-active",i===acIdx);});
    } else if(e.key==="ArrowUp"){
      e.preventDefault();
      acIdx=Math.max(acIdx-1,0);
      items.forEach(function(el,i){el.classList.toggle("ac-active",i===acIdx);});
    } else if(e.key==="Enter"){
      if(acIdx>=0&&items[acIdx]){
        inp.value=items[acIdx].querySelector(".ac-clli").textContent;
        dd.style.display="none"; acIdx=-1;
      }
      doLookup();
    } else if(e.key==="Escape"){
      dd.style.display="none"; acIdx=-1;
    }
  });

  document.addEventListener("click",function(e){
    if(!inp.contains(e.target)&&!dd.contains(e.target))dd.style.display="none";
  });
})();

document.getElementById("lookup-btn").addEventListener("click",doLookup);

function doLookup(){
  const q=document.getElementById("lookup-q").value.trim().toUpperCase();
  document.getElementById("ac-dropdown").style.display="none";
  document.getElementById("lookup-result").style.display="none";
  document.getElementById("lookup-notfound").style.display="none";
  if(!q)return;
  const SW=DATA.switches;
  const idx=SW.SWITCH_CLLI.indexOf(q);
  if(idx<0){
    // try partial match — show first result
    const pi=SW.SWITCH_CLLI.findIndex(function(c){return String(c).toUpperCase().includes(q);});
    if(pi<0){document.getElementById("lookup-notfound").style.display="block";return;}
    document.getElementById("lookup-q").value=SW.SWITCH_CLLI[pi];
    doLookup(); return;
  }

  // Switch card
  const rows=[
    ["Switch Name",      SW.switch_name[idx]||"—"],
    ["Switch Type",      SW.sw_type[idx]||"—"],
    ["CLLI Status",      SW.clli_status[idx]||"—"],
    ["State",            SW.state[idx]||"—"],
    ["Area",             SW.area[idx]||"—"],
    ["Region",           SW.region[idx]||"—"],
    ["Role",             SW.host_remote[idx]||"—"],
    ["Host CLLI",        SW.host_clli[idx]||"—"],
    ["Decom Plan",       SW.decom_plan[idx]||"—"],
    ["Proposed Cutover", SW.proposed_cutover[idx]||"—"],
  ];
  document.getElementById("lookup-switch-card").innerHTML=
    rows.map(r=>'<div class="info-row"><span class="info-key">'+r[0]+'</span><span class="info-val">'+r[1]+'</span></div>').join("");

  // Circuit summary card
  const matchInfo=DATA.sw_match_dict[q]||{};
  const matched  =matchInfo["cable pair matched"]||0;
  const unmatched=matchInfo["cable pair unmatched"]||0;
  const lfacs    =matchInfo["circuits in lfacs only"]||0;
  const sw_only  =matchInfo["wtns in switch os only"]||0;
  const cRows=[
    ["Total Circuits",   fmt(SW.circuits[idx])],
    ["Matched",          fmt(matched)],
    ["Unmatched",        fmt(unmatched)],
    ["LFACS Only",       fmt(lfacs)],
    ["SW OS Only",       fmt(sw_only)],
    ["G5 Migratable",   fmt(SW.g5_mig[idx])],
    ["G5 Needed",        fmt(SW.g5_needed[idx])],
    ["IDLC Systems",     fmt(SW.idlc_systems[idx])],
    ["Est. Annual Savings", fmtDollar(SW.est_savings[idx])],
    ["Annual Savings",      fmtDollar(SW.annual_savings[idx])],
  ];
  document.getElementById("lookup-circuit-card").innerHTML=
    cRows.map(r=>'<div class="info-row"><span class="info-key">'+r[0]+'</span><span class="info-val">'+r[1]+'</span></div>').join("");

  // Match category table
  const mParts=[];
  Object.entries(matchInfo).sort((a,b)=>b[1]-a[1]).forEach(([cat,cnt])=>{
    mParts.push('<tr><td>'+cat+'</td><td class="right">'+fmt(cnt)+'</td></tr>');
  });
  document.getElementById("lookup-match-body").innerHTML=mParts.length?mParts.join(""):"<tr><td colspan=2>No data</td></tr>";

  // Circuit type table
  const cktInfo=DATA.sw_ckt_dict[q]||{};
  const ctParts=[];
  Object.entries(cktInfo).sort((a,b)=>b[1]-a[1]).forEach(([ct,cnt])=>{
    ctParts.push('<tr><td>'+ct+'</td><td class="right">'+fmt(cnt)+'</td></tr>');
  });
  document.getElementById("lookup-ckt-body").innerHTML=ctParts.length?ctParts.join(""):"<tr><td colspan=2>No data</td></tr>";

  document.getElementById("lookup-result").style.display="block";
}

/* ── Navigate to Site Lookup ── */
function gotoLookup(clli){
  document.querySelectorAll(".tab-content").forEach(t=>t.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b=>b.classList.remove("active"));
  document.getElementById("tab-lookup").classList.add("active");
  document.querySelector('[data-tab="tab-lookup"]').classList.add("active");
  document.getElementById("lookup-q").value=clli;
  doLookup();
  window.scrollTo(0,0);
}

/* ── Utility: populate select ── */
function populateSelect(id, vals){
  const el=document.getElementById(id);
  vals.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;el.appendChild(o);});
}

/* ── Init on load ── */
document.addEventListener("DOMContentLoaded",function(){
  _inited["tab-summary"]=true;
  initSummary();
});
</script>
</body>
</html>"""

# ── Substitute placeholders ────────────────────────────────────────────────
# Remove the duplicate plotly script placeholder (keep only first <script> block)
HTML = HTML.replace("__PLOTLY_SCRIPT__\n<script>", "<script>", 1)
HTML = HTML.replace("__PLOTLY_SCRIPT__", plotly_script, 1)
HTML = HTML.replace("__DATA_JSON__", data_json)
HTML = HTML.replace("__SNAP_DATE__", snap_date_fmt)
HTML = HTML.replace("__PIVOT_HTML__", pivot_html_content)

# ── Write output ───────────────────────────────────────────────────────────
OUTPUT.write_text(HTML, encoding="utf-8")
print(f"\nOutput: {OUTPUT}")
print(f"File size: {OUTPUT.stat().st_size/1024/1024:.1f} MB")
print("Done!")
