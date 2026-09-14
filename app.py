
import streamlit as st
import re, random, textwrap, zipfile, io, math
from datetime import datetime, timedelta, date
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

st.set_page_config(page_title="ABA Progress Graph Builder v3", page_icon="📈", layout="wide")

st.title("ABA Progress Graph Builder")
st.caption("Paste ABA treatment-plan goals, review/edit what was found, then generate all progress graphs in one ZIP.")

st.info(
    "Version 3 improves goal detection and lets you edit the START DATE for every program before graphing."
)

top1, top2, top3 = st.columns([1.2, 1, 1])
with top1:
    client_name = st.text_input("Client / subject name", value="Emma")
with top2:
    current_date = st.date_input("Current / reassessment date", value=date.today())
with top3:
    points_per_graph = st.slider("Data points per graph", 35, 40, 38)

raw_text = st.text_area(
    "Paste treatment-plan information here",
    height=380,
    placeholder="""Paste directly from Word/PDF.

Example:

Parent/Caregiver Training  Parent/Caregiver will demonstrate the ability to assess problem behaviors to correctly identify the function. 80% accuracy in treatment fidelity checks across 5 consecutive sessions 0% 02/18/2026 20% 03/2027

Parent/Caregiver Training  Parent/Caregiver will utilize proactive and reactive behavioral strategies for maladaptive behavior. 80% accuracy in treatment fidelity across 5 consecutive sessions 0% 02/18/2026 45% 03/2027
"""
)

# -------------------- helpers --------------------

def clean_text(s):
    s = s.replace("&#x20;", " ").replace("\u00a0", " ")
    s = re.sub(r"\r", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def parse_date_string(s):
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except:
            pass
    return None

def to_date(v):
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    dt = parse_date_string(v)
    return dt.date() if dt else None

def normalize_domain(text, objective):
    t = text.strip(" :-")
    if t:
        # common prefixes
        known = [
            "Parent/Caregiver Training", "Caregiver Training", "Communication",
            "Expressive Communication", "Receptive Communication", "Cooperation",
            "Social", "Social Skills", "Adaptive", "Behavior Reduction"
        ]
        for k in known:
            if k.lower() in t.lower():
                return k
    if "parent/caregiver" in objective.lower() or "caregiver" in objective.lower():
        return "Parent/Caregiver Training"
    if any(k in objective.lower() for k in ["decrease", "reduce the rate", "fewer than"]):
        return "Behavior Reduction"
    return "Communication"

def concise_name(objective):
    x = objective.lower()
    # parent training
    if "assess problem behaviors" in x or "identify the function" in x:
        return "Identifying Behavior Function"
    if "proactive and reactive" in x:
        return "Behavioral Strategies"
    if "prompt hierarchy" in x:
        return "Prompt Hierarchy"
    if "toileting schedule" in x or "toilet training" in x:
        return "Toileting Support"

    # reduction
    if "non-compliance" in x or "noncompliance" in x:
        return "Non-Compliance"
    if "tantrum" in x:
        return "Tantrums"
    if "aggress" in x:
        return "Aggression"
    if "self-injur" in x or "sib" in x:
        return "Self-Injurious Behavior"
    if "elop" in x:
        return "Elopement"

    # acquisition
    if "comply" in x or ("directions" in x and "30 seconds" in x):
        return "Task Completion"
    if "attention" in x and "name" in x:
        return "Requesting Attention"
    if "wh" in x or "request for information" in x:
        return "Requesting Information"
    if "one-step" in x or "one step" in x:
        return "Following One-Step Directions"
    if "greet" in x:
        return "Responding to Greetings"
    if "request" in x:
        return "Functional Communication"
    return "Skill Acquisition"

def extract_measurements(block):
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", block):
        out.append(("percent", float(m.group(1)), m.start(), m.group(0)))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:instances?|times?)\s*(?:per|/)\s*(hour|hr|day|session|week|minute|min)", block, re.I):
        out.append(("rate", float(m.group(1)), m.start(), m.group(0), m.group(2).lower()))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?)", block, re.I):
        out.append(("duration", float(m.group(1)), m.start(), m.group(0), m.group(2).lower()))
    out.sort(key=lambda z: z[2])
    return out

def parse_one_block(block):
    block = re.sub(r"\s+", " ", block).strip()
    if not block:
        return None

    # Detect objective: choose sentence/segment with " will " but avoid "will be considered mastered".
    candidates = []
    for m in re.finditer(r"([A-Za-z][A-Za-z/ &'-]{0,50}\s+will\s+.*?)(?=(?:\s+\d+(?:\.\d+)?\s*%|\s+The target behavior|\s+Mastery|\s+\d+(?:\.\d+)?\s+instances?\s+per|\s+\d{1,2}/\d{1,2}/\d{4}|$))", block, re.I):
        txt = m.group(1).strip(" .")
        if "will be considered mastered" not in txt.lower() and len(txt.split()) >= 5:
            candidates.append((m.start(), txt))

    # Fallback: sentence that contains "will"
    if not candidates:
        sentences = re.split(r"(?<=[.!?])\s+", block)
        pos = 0
        for s in sentences:
            if re.search(r"\bwill\b", s, re.I) and "will be considered mastered" not in s.lower():
                candidates.append((block.find(s, pos), s.strip(" .")))
                break
            pos += len(s) + 1

    if not candidates:
        return None

    obj_start, objective = candidates[0]
    objective = objective.strip()
    if not objective.endswith("."):
        objective += "."

    prefix = block[:obj_start].strip()
    domain = normalize_domain(prefix, objective)
    program_name = concise_name(objective)

    # Mastery: percent or rate closest after objective
    post = block[obj_start + len(candidates[0][1]):]

    mastery = None
    unit = None
    ylabel = None
    comparator = ">="

    # Prefer "fewer than X instances per ..."
    m = re.search(r"(?:fewer than|less than|under|below)\s+(\d+(?:\.\d+)?)\s*(instances?|times?)\s*(?:per|/)\s*(hour|hr|day|session|week|minute|min)", post, re.I)
    if m:
        mastery = float(m.group(1))
        per = {"hr":"hour","min":"minute"}.get(m.group(3).lower(), m.group(3).lower())
        unit = f"instances/{per}"
        ylabel = f"Rate (instances/{per})"
        comparator = "<"
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:accuracy|treatment fidelity)?", post, re.I)
        if m:
            mastery = float(m.group(1))
            unit = "%"
            ylabel = "Accuracy (%)"
            comparator = ">="

    # Remove mastery phrase region heuristically before baseline/current extraction
    work = post
    if mastery is not None:
        if unit == "%":
            first = re.search(r"(\d+(?:\.\d+)?)\s*%", work)
            if first:
                work = work[:first.start()] + work[first.end():]
        else:
            first = re.search(r"(?:(?:fewer than|less than|under|below)\s+)?\d+(?:\.\d+)?\s*(?:instances?|times?)\s*(?:per|/)\s*(?:hour|hr|day|session|week|minute|min)", work, re.I)
            if first:
                work = work[:first.start()] + work[first.end():]

    # Find baseline date
    dm = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", block)
    baseline_dt = parse_date_string(dm.group(0)) if dm else None

    # Find target month/year
    target_matches = re.findall(r"\b(?:0?[1-9]|1[0-2])/\d{4}\b", block)
    target_date = target_matches[-1] if target_matches else ""

    # Measurements after mastery
    measurements = extract_measurements(work)

    if unit == "%":
        vals = [x[1] for x in measurements if x[0] == "percent"]
    elif unit and unit.startswith("instances/"):
        vals = [x[1] for x in measurements if x[0] == "rate"]
    else:
        vals = [x[1] for x in measurements]

    # Last-resort percent extraction from whole block excluding first mastery %
    if len(vals) < 2 and unit == "%":
        allp = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", block)]
        if mastery is not None and allp and abs(allp[0] - mastery) < 1e-9:
            allp = allp[1:]
        vals = allp

    # Last-resort rate extraction
    if len(vals) < 2 and unit and unit.startswith("instances/"):
        allr = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:instances?|times?)\s*(?:per|/)\s*(?:hour|hr|day|session|week|minute|min)", block, re.I)]
        # remove mastery first if matching
        if mastery is not None and allr and abs(allr[0] - mastery) < 1e-9:
            allr = allr[1:]
        vals = allr

    if len(vals) < 2 or baseline_dt is None:
        return None

    baseline, current = vals[0], vals[1]

    if mastery is None:
        # infer measurement from baseline/current
        if re.search(r"\d+(?:\.\d+)?\s*%", block):
            mastery, unit, ylabel, comparator = 80.0, "%", "Accuracy (%)", ">="
        else:
            unit, ylabel, comparator = "Value", "Value", ">="

    return {
        "Domain": domain,
        "Program Name": program_name,
        "Objective": objective,
        "Mastery": mastery,
        "Comparator": comparator,
        "Unit": unit,
        "Y-Axis Label": ylabel,
        "Baseline": baseline,
        "Start Date": baseline_dt.date(),
        "Current": current,
        "Target Date": target_date
    }

def parse_programs(text):
    text = clean_text(text)

    # Strongest strategy: split on blank lines. Copy/pasted rows typically preserve blank lines.
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]

    parsed = []
    for b in blocks:
        row = parse_one_block(b)
        if row:
            parsed.append(row)

    # Fallback if blank-line splitting did not find enough:
    # identify starts of objective-containing chunks.
    if len(parsed) <= 1:
        flat = re.sub(r"\n+", " ", text)
        # start markers: domain-like text followed by a subject + will
        starts = [m.start() for m in re.finditer(r"(?i)(?:Parent/Caregiver Training|Caregiver Training|Communication|Expressive Communication|Receptive Communication|Cooperation|Social(?: Skills)?|Adaptive|Behavior Reduction)?\s*[A-Za-z/ &'-]{2,50}\s+will\s+", flat)]
        if starts:
            starts = sorted(set(starts))
            parsed = []
            for i, s in enumerate(starts):
                e = starts[i+1] if i+1 < len(starts) else len(flat)
                row = parse_one_block(flat[s:e])
                if row:
                    parsed.append(row)

    return parsed

def fmt_num(x):
    x = float(x)
    return int(x) if x.is_integer() else round(x, 2)

def is_reduction(row):
    obj = str(row["Objective"]).lower()
    return row["Comparator"] == "<" or any(k in obj for k in ["decrease", "reduce", "fewer than", "less than"])

def generate_dates(start_dt, end_dt, n, seed):
    rng = random.Random(seed)
    span = (end_dt - start_dt).days
    if span <= 1:
        return [start_dt, end_dt]
    n = min(n, span + 1)
    picks = sorted(rng.sample(range(1, span), n-2)) if n > 2 else []
    return [start_dt] + [start_dt + timedelta(days=d) for d in picks] + [end_dt]

def generate_values(n, baseline, current, mastery, seed):
    rng = random.Random(seed)
    vals = [float(baseline)]
    delta = float(current) - float(baseline)
    scale = max(abs(float(baseline)), abs(float(current)), abs(float(mastery or 0)), 1)
    step = max(scale * 0.08, 0.5)

    for i in range(1, n-1):
        p = i/(n-1)
        target = float(baseline) + delta*(p**0.85)
        v = target + rng.uniform(-step, step)

        r = rng.random()
        if i > 2 and r < 0.12:
            v = vals[-1]
        elif i > 2 and r < 0.24:
            against = -1 if delta >= 0 else 1
            v = vals[-1] + against*rng.uniform(step*0.5, step*1.3)
        elif i > 2 and r < 0.38:
            direction = 1 if delta >= 0 else -1
            v = vals[-1] + direction*rng.uniform(step*0.5, step*1.3)

        v = max(0, v)
        ceiling = max(float(baseline), float(current), float(mastery or 0)) + scale*0.25
        v = min(v, ceiling)
        vals.append(v)

    vals.append(float(current))
    if max(vals) <= 20:
        vals = [round(v, 1) for v in vals]
    else:
        vals = [round(v) for v in vals]
    vals[0] = fmt_num(baseline)
    vals[-1] = fmt_num(current)
    return vals

def mastery_text(row):
    m = fmt_num(row["Mastery"])
    if row["Unit"] == "%":
        return f"Mastery Criteria: {m}% Accuracy"
    if row["Comparator"] == "<":
        return f"Mastery Criteria: <{m} {row['Unit']}"
    return f"Mastery Criteria: {m} {row['Unit']}"

def make_graph(row, goal_num, end_dt, n_points):
    start_d = to_date(row["Start Date"])
    if start_d is None:
        raise ValueError("Start Date is invalid.")
    start_dt = datetime.combine(start_d, datetime.min.time())

    if end_dt <= start_dt:
        raise ValueError("Current/reassessment date must be after the program Start Date.")

    dates = generate_dates(start_dt, end_dt, n_points, 1000 + goal_num*97)
    vals = generate_values(
        len(dates),
        float(row["Baseline"]),
        float(row["Current"]),
        float(row["Mastery"]),
        2000 + goal_num*131
    )

    fig, ax = plt.subplots(figsize=(22,10), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.plot(dates, vals, color="#4472C4", marker="o", markersize=5.7, linewidth=2.2)

    mastery = float(row["Mastery"])
    ax.axhline(mastery, color="#00A651", linestyle="--", linewidth=2)

    if row["Unit"] == "%":
        ymin, ymax = 0, 100
        yticks = list(range(0,101,10))
    else:
        refs = vals + [float(row["Baseline"]), float(row["Current"]), mastery]
        ymax = max(5, math.ceil(max(refs)*1.25))
        if ymax <= 10:
            step = 1
        elif ymax <= 20:
            step = 2
        elif ymax <= 50:
            step = 5
        else:
            step = 10
        ymax = int(math.ceil(ymax/step)*step)
        ymin = 0
        yticks = list(range(0, ymax+1, step))

    ax.set_ylim(ymin, ymax)
    ax.set_yticks(yticks)
    ax.set_xlim(start_dt, end_dt)
    ax.set_ylabel(str(row["Y-Axis Label"]), fontsize=12, fontweight="bold")
    ax.set_xlabel("Session Date", fontsize=12, fontweight="bold")
    ax.grid(True, color="#D9D9D9", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # One visible date label per point
    ax.set_xticks(dates)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d/%Y"))
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right", fontsize=7.0)

    offset = (ymax-ymin)*0.02
    ax.text(end_dt - timedelta(days=max(1,(end_dt-start_dt).days//120)),
            mastery + offset,
            mastery_text(row),
            ha="right", va="bottom", fontsize=10.5,
            fontweight="bold", color="#008C3A")

    fig.suptitle(
        f"{row['Domain']} Goal #{goal_num}: {row['Program Name']}",
        fontsize=20, fontweight="bold", y=0.97
    )
    ax.set_title(
        "\n".join(textwrap.wrap(str(row["Objective"]), width=120)),
        fontsize=12.2, pad=18
    )
    plt.subplots_adjust(top=0.84, bottom=0.30, left=0.07, right=0.98)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return dates, vals, buf.getvalue()

# -------------------- UI --------------------

if "goal_df" not in st.session_state:
    st.session_state.goal_df = None

left, right = st.columns(2)
with left:
    read_clicked = st.button("1) Read My Goals", type="primary", use_container_width=True)
with right:
    clear_clicked = st.button("Clear", use_container_width=True)

if clear_clicked:
    st.session_state.goal_df = None
    st.rerun()

if read_clicked:
    if not raw_text.strip():
        st.error("Paste the treatment-plan information first.")
    else:
        rows = parse_programs(raw_text)
        if not rows:
            st.error("No goals were detected. Try keeping a blank line between each treatment-plan row.")
        else:
            st.session_state.goal_df = pd.DataFrame(rows)
            st.success(f"Found {len(rows)} goal(s). Review and edit them below.")

if st.session_state.goal_df is not None:
    st.subheader("Review extracted goals")
    st.caption(
        "Every field below is editable. You can change the Start Date for each program independently before creating graphs."
    )

    edited = st.data_editor(
        st.session_state.goal_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Domain": st.column_config.TextColumn("Domain"),
            "Program Name": st.column_config.TextColumn("Program Name"),
            "Objective": st.column_config.TextColumn("Objective", width="large"),
            "Mastery": st.column_config.NumberColumn("Mastery"),
            "Comparator": st.column_config.SelectboxColumn("Mastery Rule", options=[">=", "<"]),
            "Unit": st.column_config.TextColumn("Unit"),
            "Y-Axis Label": st.column_config.TextColumn("Y-Axis Label"),
            "Baseline": st.column_config.NumberColumn("Baseline"),
            "Start Date": st.column_config.DateColumn("Start Date", format="MM/DD/YYYY"),
            "Current": st.column_config.NumberColumn("Current"),
            "Target Date": st.column_config.TextColumn("Target Date"),
        }
    )
    st.session_state.goal_df = edited

    st.markdown("**Tip:** If one goal started later than the others, simply click its **Start Date** cell and choose the correct date.")

    if st.button("2) Create ABA Progress Graphs", type="primary", use_container_width=True):
        end_dt = datetime.combine(current_date, datetime.min.time())
        zbuf = io.BytesIO()
        success = 0

        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, row in edited.iterrows():
                goal_num = idx + 1
                try:
                    dates, vals, png = make_graph(row, goal_num, end_dt, points_per_graph)

                    safe_client = re.sub(r"[^A-Za-z0-9_]+", "_", client_name.replace(" ","_")).strip("_") or "Client"
                    safe_program = re.sub(r"[^A-Za-z0-9_]+", "_", str(row["Program Name"]).replace(" ","_")).strip("_")
                    fn = f"{safe_client}_Goal_{goal_num:02d}_{safe_program}.png"
                    zf.writestr(fn, png)
                    success += 1

                    with st.expander(f"Goal #{goal_num}: {row['Program Name']}", expanded=(goal_num == 1)):
                        st.image(png, use_container_width=True)
                        st.caption(
                            f"{len(dates)} dates = {len(vals)} data points • "
                            f"Start {dates[0].strftime('%m/%d/%Y')} • "
                            f"End {dates[-1].strftime('%m/%d/%Y')} • "
                            f"Baseline {fmt_num(row['Baseline'])} • Current {fmt_num(row['Current'])}"
                        )
                except Exception as e:
                    st.error(f"Goal #{goal_num} could not be created: {e}")

        zbuf.seek(0)
        if success:
            st.success(f"Created {success} graph(s).")
            safe_client = re.sub(r"[^A-Za-z0-9_]+", "_", client_name.replace(" ","_")).strip("_") or "Client"
            st.download_button(
                "Download All Graphs as ZIP",
                data=zbuf.getvalue(),
                file_name=f"{safe_client}_ABA_Progress_Graphs.zip",
                mime="application/zip",
                use_container_width=True
            )

st.divider()
st.caption("Use identifiable client information only in a hosting environment approved by your organization for protected health information.")
