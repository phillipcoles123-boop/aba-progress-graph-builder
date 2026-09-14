
import streamlit as st
import re, random, textwrap, zipfile, io, math
from datetime import datetime, timedelta, date
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

st.set_page_config(page_title="ABA Progress Graph Builder v2", page_icon="📈", layout="wide")

st.title("ABA Progress Graph Builder")
st.caption("Paste ABA goals → review what was extracted → generate professional progress graphs → download one ZIP.")

st.info(
    "Version 2 supports both skill-acquisition goals (for example, % accuracy) "
    "and behavior-reduction goals (for example, instances per hour)."
)

with st.expander("Supported measurement types"):
    st.markdown("""
- **Percent / accuracy:** `55%`, `80% accuracy`
- **Rate:** `10 instances per hour`, `4 instances per day`
- **Frequency / count:** `6 instances`, `3 times`
- **Duration:** `5 minutes`, `30 seconds`
- **Latency:** `20 seconds`, `2 minutes`

You can correct anything the app extracts before creating the graphs.
""")

top1, top2, top3 = st.columns([1.2, 1, 1])
with top1:
    client_name = st.text_input("Client name", value="Emma")
with top2:
    current_date = st.date_input("Current / reassessment date", value=date.today())
with top3:
    points_per_graph = st.slider("Data points per graph", 35, 40, 38)

raw_text = st.text_area(
    "Paste treatment-plan information here",
    height=360,
    placeholder="""Paste directly from your treatment plan.

Example behavior-reduction row:
Non-compliance
Emma will decrease the rate in which she engages in non-compliance.
The target behavior will be considered mastered when it occurs at a rate of fewer than 2 instances per hour for 4 consecutive weeks.
10 instances per hour as of 02/18/2025
12 instances per hour
03/2027

Example skill-acquisition row:
Cooperation
Emma will comply with directions given by the therapist within 30 seconds of the instruction being provided.
80% accuracy over 5 consecutive sessions
0%
02/18/2026
55%
03/2027
"""
)

# ---------- Parsing helpers ----------

HEADER_PHRASES = [
    "target behavior", "behavioral objective", "mastery criteria", "baseline data",
    "baseline data/ date", "baseline data / date", "current level", "current",
    "target date", "short term behavioral objective", "communication domain area",
    "communication behaviors targeted for increase"
]

def clean_text(s: str) -> str:
    s = s.replace("&#x20;", " ").replace("\u00a0", " ")
    s = re.sub(r"\r", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def strip_headers(s: str) -> str:
    out = s
    for h in HEADER_PHRASES:
        out = re.sub(re.escape(h), " ", out, flags=re.I)
    out = re.sub(r"\|+", " ", out)
    out = re.sub(r"-{3,}", " ", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()

def parse_date_string(s):
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None

def concise_name(objective, fallback="Program"):
    x = objective.lower()

    # behavior reduction
    m = re.search(r"engages? in ([^.]+)", x)
    if m and any(k in x for k in ["decrease", "reduce", "fewer", "rate"]):
        phrase = m.group(1)
        phrase = re.sub(r"\b(the|a|an)\b", " ", phrase)
        phrase = re.sub(r"\s+", " ", phrase).strip(" .")
        return phrase.title()[:55]

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

    # skill acquisition
    if "comply" in x or ("directions" in x and "30 seconds" in x):
        return "Task Completion"
    if "attention" in x and "name" in x:
        return "Requesting Attention"
    if "wh" in x or "request for information" in x or "request information" in x:
        return "Requesting Information"
    if "one-step" in x or "one step" in x:
        return "Following One-Step Directions"
    if "greet" in x:
        return "Responding to Greetings"
    if "wait" in x:
        return "Waiting"
    if "transition" in x:
        return "Transitioning"
    if "request" in x:
        return "Functional Communication"
    return fallback

MEASURE_PATTERNS = [
    # percent
    ("percent", re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%", re.I)),
    # rate
    ("rate", re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:instances?|times?)\s*(?:per|/)\s*(?P<period>hour|hr|day|session|week|minute|min)", re.I)),
    # duration / latency
    ("duration", re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<period>seconds?|secs?|minutes?|mins?)", re.I)),
    # raw count
    ("count", re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:instances?|times?)\b", re.I)),
]

def normalize_unit(kind, period=None):
    if kind == "percent":
        return "%", "Accuracy (%)"
    if kind == "rate":
        p = (period or "hour").lower()
        mapping = {"hr":"hour", "min":"minute"}
        p = mapping.get(p, p)
        return f"instances/{p}", f"Rate (instances/{p})"
    if kind == "duration":
        p = (period or "seconds").lower()
        p = {"secs":"seconds","sec":"seconds","mins":"minutes","min":"minutes"}.get(p, p)
        if p.endswith("s"):
            p = p
        return p, f"Duration ({p})"
    return "instances", "Frequency (instances)"

def find_measurements(s):
    found = []
    for kind, pat in MEASURE_PATTERNS:
        for m in pat.finditer(s):
            # avoid double counting rate as count by checking spans later
            found.append({
                "kind": kind,
                "value": float(m.group("value")),
                "period": m.groupdict().get("period"),
                "span": m.span(),
                "text": m.group(0)
            })
    # Prefer more specific matches when spans overlap
    priority = {"rate":4, "percent":4, "duration":3, "count":2}
    found.sort(key=lambda x: (x["span"][0], -priority[x["kind"]], -(x["span"][1]-x["span"][0])))
    kept = []
    for f in found:
        if any(not (f["span"][1] <= k["span"][0] or f["span"][0] >= k["span"][1]) for k in kept):
            continue
        kept.append(f)
    kept.sort(key=lambda x: x["span"][0])
    return kept

def extract_mastery(chunk):
    # Capture a likely mastery sentence first
    mastery_sentence = ""
    mastery_patterns = [
        r"([^.]*(?:mastered|mastery)[^.]*\.)",
        r"([^.]*(?:accuracy\s+over|consecutive\s+sessions|consecutive\s+weeks|consecutive\s+months)[^.]*\.)"
    ]
    for p in mastery_patterns:
        m = re.search(p, chunk, re.I)
        if m:
            mastery_sentence = m.group(1).strip()
            break

    search_text = mastery_sentence if mastery_sentence else chunk[:350]
    ms = find_measurements(search_text)
    if ms:
        m = ms[0]
        unit, ylabel = normalize_unit(m["kind"], m["period"])
        comparator = "<" if re.search(r"fewer than|less than|below|under", search_text, re.I) else ">="
        return m["value"], unit, ylabel, comparator, mastery_sentence

    return None, None, None, None, mastery_sentence

def infer_domain(preceding_text, objective, target_name):
    # Use nearest short phrase before the objective when it looks like a domain/target
    tail = preceding_text[-140:]
    tail = re.sub(r"\s+", " ", tail).strip()
    if tail:
        # remove month/year or date scraps
        tail = re.sub(r"\b\d{1,2}/\d{4}\b", " ", tail)
        tail = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ", tail)
        tail = re.sub(r"\s+", " ", tail).strip()
        words = tail.split()
        candidate = " ".join(words[-4:]).strip()
        if candidate and not re.search(r"\d", candidate):
            # behavior labels become "Behavior Reduction"
            if any(k in objective.lower() for k in ["decrease", "reduce", "fewer", "rate"]):
                return "Behavior Reduction"
    if any(k in objective.lower() for k in ["decrease", "reduce", "rate"]):
        return "Behavior Reduction"
    return "Communication"

def parse_programs(text, client):
    text = clean_text(text)
    simplified = strip_headers(text)

    # Find every objective beginning with the client name + "will"
    name_pat = re.escape(client.strip()) if client.strip() else r"[A-Z][A-Za-z'-]+"
    obj_pat = re.compile(rf"(?i)\b{name_pat}\s+will\b.*?(?:\.|(?=\s+\d+(?:\.\d+)?\s*%))")
    matches = list(obj_pat.finditer(simplified))

    programs = []
    if not matches:
        return programs

    for i, m in enumerate(matches):
        chunk_start = m.start()
        chunk_end = matches[i+1].start() if i+1 < len(matches) else len(simplified)
        chunk = simplified[chunk_start:chunk_end].strip()
        objective = re.sub(r"\s+", " ", m.group(0)).strip()
        if not objective.endswith("."):
            objective += "."

        pre = simplified[max(0, chunk_start-180):chunk_start]
        target = concise_name(objective, fallback=f"Goal {i+1}")
        domain = infer_domain(pre, objective, target)

        mastery_value, mastery_unit, ylabel, comparator, mastery_sentence = extract_mastery(chunk)

        # Remove the mastery sentence before finding baseline/current measurements
        remainder = chunk
        if mastery_sentence:
            remainder = remainder.replace(mastery_sentence, " ")

        measurements = find_measurements(remainder)

        # Keep measurements compatible with mastery type when possible
        if mastery_unit == "%":
            compatible = [x for x in measurements if x["kind"] == "percent"]
        elif mastery_unit and mastery_unit.startswith("instances/"):
            compatible = [x for x in measurements if x["kind"] == "rate"]
        elif mastery_unit in ("seconds", "second", "minutes", "minute"):
            compatible = [x for x in measurements if x["kind"] == "duration"]
        elif mastery_unit == "instances":
            compatible = [x for x in measurements if x["kind"] == "count"]
        else:
            compatible = measurements

        if len(compatible) < 2:
            # fallback: use any remaining measurements
            compatible = measurements

        baseline = compatible[0]["value"] if len(compatible) >= 1 else None
        current = compatible[1]["value"] if len(compatible) >= 2 else None

        # If mastery could not be extracted, infer unit from baseline/current
        if mastery_value is None and compatible:
            unit, ylabel = normalize_unit(compatible[0]["kind"], compatible[0]["period"])
            mastery_unit = unit
            comparator = ">="
        elif mastery_unit is None and compatible:
            mastery_unit, ylabel = normalize_unit(compatible[0]["kind"], compatible[0]["period"])

        # Baseline date: first full date in chunk
        date_match = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", chunk)
        baseline_date = parse_date_string(date_match.group(0)) if date_match else None

        # target date month/year
        target_match = re.findall(r"\b(?:0?[1-9]|1[0-2])/\d{4}\b", chunk)
        target_date = target_match[-1] if target_match else ""

        if baseline is not None and current is not None and baseline_date is not None:
            programs.append({
                "Domain": domain,
                "Program Name": target,
                "Objective": objective,
                "Mastery": mastery_value if mastery_value is not None else "",
                "Mastery Comparator": comparator or ">=",
                "Unit": mastery_unit or "",
                "Y-Axis Label": ylabel or "Value",
                "Baseline": baseline,
                "Baseline Date": baseline_date.strftime("%m/%d/%Y"),
                "Current": current,
                "Target Date": target_date,
            })

    return programs

def friendly_number(x):
    x = float(x)
    return int(x) if x.is_integer() else round(x, 2)

def is_reduction_goal(row):
    objective = str(row["Objective"]).lower()
    # Objective language has priority
    if any(k in objective for k in ["decrease", "reduce", "fewer", "less than"]):
        return True
    return row.get("Mastery Comparator") == "<"

def generate_dates(start_dt, end_dt, n, seed):
    rng = random.Random(seed)
    span = (end_dt - start_dt).days
    if span <= 1:
        return [start_dt, end_dt]
    n = min(n, span + 1)

    # Guarantee broad monthly coverage by sampling across the whole period
    interior_needed = n - 2
    if interior_needed <= 0:
        return [start_dt, end_dt]

    all_days = list(range(1, span))
    picks = set()

    # Month buckets
    cursor = date(start_dt.year, start_dt.month, 1)
    end_month = date(end_dt.year, end_dt.month, 1)
    buckets = []
    while cursor <= end_month:
        if cursor.month == 12:
            nxt = date(cursor.year + 1, 1, 1)
        else:
            nxt = date(cursor.year, cursor.month + 1, 1)
        a = max(start_dt.date(), cursor)
        b = min(end_dt.date(), nxt - timedelta(days=1))
        valid = [(datetime.combine(a, datetime.min.time()) - start_dt).days + j
                 for j in range((b-a).days + 1)]
        valid = [d for d in valid if 0 < d < span]
        if valid:
            buckets.append(valid)
        cursor = nxt

    # At least one interior point per month where possible
    for bucket in buckets:
        if len(picks) < interior_needed:
            picks.add(rng.choice(bucket))

    remaining = [d for d in all_days if d not in picks]
    need = interior_needed - len(picks)
    if need > 0:
        picks.update(rng.sample(remaining, need))

    return [start_dt] + [start_dt + timedelta(days=d) for d in sorted(picks)] + [end_dt]

def generate_values(n, baseline, current, mastery, comparator, reduction, seed):
    rng = random.Random(seed)
    vals = [float(baseline)]
    delta = float(current) - float(baseline)

    for i in range(1, n-1):
        p = i / (n-1)
        target = float(baseline) + delta * (p**0.85)

        # Scale variability to the data magnitude
        mag = max(abs(baseline), abs(current), abs(mastery) if mastery not in ("", None) else 0, 1)
        step = max(mag * 0.08, 0.5)
        noise = rng.uniform(-step, step)
        v = target + noise

        r = rng.random()
        if i > 2 and r < 0.12:
            v = vals[-1]  # plateau
        elif i > 2 and r < 0.24:
            # temporary move against the observed baseline->current direction
            against = -1 if delta >= 0 else 1
            v = vals[-1] + against * rng.uniform(step*0.5, step*1.4)
        elif i > 2 and r < 0.38:
            # recovery in the observed direction
            direction = 1 if delta >= 0 else -1
            v = vals[-1] + direction * rng.uniform(step*0.5, step*1.4)

        v = max(0, v)

        # Prevent wildly implausible overshoot
        ceiling = max(float(baseline), float(current), float(mastery) if mastery not in ("", None) else 0) + mag*0.25
        v = min(v, ceiling)

        vals.append(v)

    vals.append(float(current))

    # Round by scale
    if max(vals) <= 20:
        vals = [round(v, 1) for v in vals]
    else:
        vals = [round(v) for v in vals]
    vals[0] = friendly_number(baseline)
    vals[-1] = friendly_number(current)
    return vals

def mastery_label(row):
    m = friendly_number(row["Mastery"]) if row["Mastery"] != "" else ""
    comp = row["Mastery Comparator"]
    unit = row["Unit"]
    if unit == "%":
        return f"Mastery Criteria: {m}% Accuracy"
    if comp == "<":
        return f"Mastery Criteria: <{m} {unit}"
    return f"Mastery Criteria: {m} {unit}"

def graph_bytes(row, goal_num, end_dt, n_points):
    start_dt = parse_date_string(str(row["Baseline Date"]))
    if start_dt is None:
        raise ValueError("Invalid baseline date.")
    if end_dt <= start_dt:
        raise ValueError("Current/reassessment date must be after the baseline date.")

    reduction = is_reduction_goal(row)
    dates = generate_dates(start_dt, end_dt, n_points, 1000 + goal_num*97)
    vals = generate_values(
        len(dates),
        float(row["Baseline"]),
        float(row["Current"]),
        float(row["Mastery"]) if row["Mastery"] != "" else 0,
        row["Mastery Comparator"],
        reduction,
        2000 + goal_num*131
    )

    fig, ax = plt.subplots(figsize=(22, 10), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.plot(dates, vals, marker="o", linewidth=2.2, markersize=5.7, color="#4472C4")

    # Mastery line
    mastery = float(row["Mastery"]) if row["Mastery"] != "" else None
    if mastery is not None:
        ax.axhline(mastery, linestyle="--", linewidth=2, color="#00A651")

    # Y-axis
    unit = str(row["Unit"])
    if unit == "%":
        ymin, ymax = 0, 100
        yticks = list(range(0, 101, 10))
    else:
        all_reference = [float(row["Baseline"]), float(row["Current"])]
        if mastery is not None:
            all_reference.append(mastery)
        max_ref = max(all_reference + vals)
        ymax = max(5, math.ceil(max_ref * 1.25))
        # round to a clean scale
        if ymax <= 10:
            ymax = math.ceil(ymax)
            step = 1
        elif ymax <= 20:
            ymax = int(math.ceil(ymax / 2) * 2)
            step = 2
        elif ymax <= 50:
            ymax = int(math.ceil(ymax / 5) * 5)
            step = 5
        else:
            ymax = int(math.ceil(ymax / 10) * 10)
            step = 10
        ymin = 0
        yticks = list(range(0, int(ymax)+1, step))

    ax.set_ylim(ymin, ymax)
    ax.set_yticks(yticks)
    ax.set_ylabel(str(row["Y-Axis Label"]), fontsize=12, fontweight="bold")
    ax.set_xlabel("Session Date", fontsize=12, fontweight="bold")
    ax.set_xlim(start_dt, end_dt)
    ax.grid(True, color="#D9D9D9", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # CRITICAL: one visible X-axis label per data point
    ax.set_xticks(dates)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d/%Y"))
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right", fontsize=7.1)

    if mastery is not None:
        offset = (ymax-ymin)*0.02
        ax.text(
            end_dt - timedelta(days=max(1, (end_dt-start_dt).days//120)),
            mastery + offset,
            mastery_label(row),
            ha="right", va="bottom",
            fontsize=10.5, fontweight="bold", color="#008C3A"
        )

    domain = str(row["Domain"]).strip() or ("Behavior Reduction" if reduction else "Skill Acquisition")
    short = str(row["Program Name"]).strip() or f"Goal {goal_num}"
    fig.suptitle(f"{domain} Goal #{goal_num}: {short}", fontsize=20, fontweight="bold", y=0.97)
    subtitle = "\n".join(textwrap.wrap(str(row["Objective"]), width=120))
    ax.set_title(subtitle, fontsize=12.2, pad=18)
    plt.subplots_adjust(top=0.84, bottom=0.30, left=0.07, right=0.98)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return dates, vals, short, buf.getvalue()

# ---------- UI workflow ----------

if "parsed_df" not in st.session_state:
    st.session_state.parsed_df = None

c1, c2 = st.columns([1, 1])
with c1:
    parse_clicked = st.button("1) Read My Goals", type="primary", use_container_width=True)
with c2:
    clear_clicked = st.button("Clear", use_container_width=True)

if clear_clicked:
    st.session_state.parsed_df = None
    st.rerun()

if parse_clicked:
    if not raw_text.strip():
        st.error("Paste the treatment-plan information first.")
    elif not client_name.strip():
        st.error("Enter the client name first.")
    else:
        parsed = parse_programs(raw_text, client_name)
        if not parsed:
            st.error(
                "I couldn't reliably identify the goals yet. "
                "Make sure each objective includes the client name followed by 'will', plus baseline/current data."
            )
        else:
            st.session_state.parsed_df = pd.DataFrame(parsed)
            st.success(f"Found {len(parsed)} goal(s). Review them below before creating graphs.")

if st.session_state.parsed_df is not None:
    st.subheader("Review extracted goals")
    st.caption("You can click any cell and correct it before generating the graphs.")

    edited_df = st.data_editor(
        st.session_state.parsed_df,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "Objective": st.column_config.TextColumn("Objective", width="large"),
            "Domain": st.column_config.TextColumn("Domain"),
            "Program Name": st.column_config.TextColumn("Program Name"),
            "Mastery": st.column_config.NumberColumn("Mastery"),
            "Baseline": st.column_config.NumberColumn("Baseline"),
            "Current": st.column_config.NumberColumn("Current"),
            "Baseline Date": st.column_config.TextColumn("Baseline Date"),
            "Target Date": st.column_config.TextColumn("Target Date"),
        }
    )

    st.session_state.parsed_df = edited_df

    generate = st.button("2) Create ABA Progress Graphs", type="primary", use_container_width=True)

    if generate:
        end_dt = datetime.combine(current_date, datetime.min.time())
        zip_buffer = io.BytesIO()
        success_count = 0

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, row in edited_df.iterrows():
                goal_num = idx + 1
                try:
                    dates, vals, short, png = graph_bytes(row, goal_num, end_dt, points_per_graph)
                    safe_short = re.sub(r"[^A-Za-z0-9_]+", "_", short.replace(" ", "_")).strip("_")
                    safe_client = re.sub(r"[^A-Za-z0-9_]+", "_", client_name.replace(" ", "_")).strip("_")
                    fn = f"{safe_client}_Goal_{goal_num:02d}_{safe_short}.png"
                    zf.writestr(fn, png)
                    success_count += 1

                    with st.expander(f"Goal #{goal_num}: {short}", expanded=(goal_num == 1)):
                        st.image(png, use_container_width=True)
                        st.caption(
                            f"{len(dates)} dates = {len(vals)} data points • "
                            f"Baseline {friendly_number(row['Baseline'])} {row['Unit']} on {dates[0].strftime('%m/%d/%Y')} • "
                            f"Current {friendly_number(row['Current'])} {row['Unit']} on {dates[-1].strftime('%m/%d/%Y')}"
                        )
                except Exception as e:
                    st.error(f"Goal #{goal_num} could not be created: {e}")

        zip_buffer.seek(0)

        if success_count:
            st.success(f"Created {success_count} graph(s).")
            safe_client = re.sub(r"[^A-Za-z0-9_]+", "_", client_name.replace(" ", "_")).strip("_")
            st.download_button(
                "Download All Graphs as ZIP",
                data=zip_buffer.getvalue(),
                file_name=f"{safe_client}_ABA_Progress_Graphs.zip",
                mime="application/zip",
                use_container_width=True
            )

st.divider()
st.caption(
    "Privacy note: only use identifiable client information in a hosting environment your organization has approved for protected health information."
)
