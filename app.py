
import streamlit as st
import re, os, random, textwrap, zipfile, io
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

st.set_page_config(page_title="ABA Progress Graph Builder", page_icon="📈", layout="wide")

st.title("ABA Progress Graph Builder")
st.caption("Paste treatment-plan goals. The app extracts each program, creates ABA progress graphs, and gives you a ZIP file.")

with st.expander("What to paste"):
    st.markdown("""
Paste the treatment-plan section exactly as it appears in your document.  
The app looks for:

- Domain / area
- Short-Term Behavioral Objective
- Mastery Criteria
- Baseline percentage and date
- Current level
- Target date
""")

col1, col2, col3 = st.columns(3)
with col1:
    client_name = st.text_input("Client name", value="Emma")
with col2:
    current_date = st.date_input("Current / reassessment date")
with col3:
    points_per_graph = st.slider("Data points per graph", 35, 40, 38)

raw_text = st.text_area(
    "Paste treatment-plan information here",
    height=420,
    placeholder="""Example:

Cooperation

Emma will comply with directions given by the therapist within 30 seconds of the instruction being provided.

80% accuracy over 5 consecutive sessions

0%
02/18/2026

55%

03/2027

Expressive Communication

Emma will request for attention by calling the listener's name.

80% accuracy over 5 consecutive sessions

0%
02/18/2026

33%

03/2027
"""
)

def clean_text(s):
    s = s.replace("&#x20;", " ")
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\r", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def parse_date(s):
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None

def find_programs(text):
    """
    Heuristic parser for common ABA table copy/paste text.
    It identifies objectives by the presence of a client-name-led sentence,
    then finds nearby mastery/baseline/current/target values.
    """
    text = clean_text(text)
    lines = [x.strip() for x in text.splitlines() if x.strip()]

    # Remove obvious headers/separators
    drop = {
        "Communication Behaviors Targeted for Increase:",
        "Communication Domain area",
        "Short Term Behavioral Objective",
        "Mastery Criteria",
        "Baseline Data / Date",
        "Current",
        "Level",
        "Target Date",
        "|", "---"
    }
    lines = [x for x in lines if x not in drop and not set(x) <= set("|-: ")]

    # Rebuild into chunks using objective sentences as anchors
    joined = "\n".join(lines)
    name_pat = re.escape(client_name.strip()) if client_name.strip() else r"[A-Z][a-z]+"
    obj_matches = list(re.finditer(rf"(?im)^(.*?{name_pat}.*?(?:\.|$))", joined))

    programs = []
    if not obj_matches:
        return programs

    for i, m in enumerate(obj_matches):
        start = m.start()
        end = obj_matches[i+1].start() if i+1 < len(obj_matches) else len(joined)
        chunk = joined[start:end]

        # Objective first line(s)
        objective = m.group(1).replace("\n", " ").strip()

        # Domain = nearest preceding non-header line before objective
        pre = joined[:start].splitlines()
        domain = "Communication"
        for prev in reversed(pre[-6:]):
            p = prev.strip()
            if not p:
                continue
            if re.search(r"\d+%|accuracy|consecutive|/\d{4}", p, re.I):
                continue
            if client_name and client_name.lower() in p.lower():
                continue
            domain = p
            break

        # Mastery
        mastery_match = re.search(r"(\d+)%\s*(?:accuracy)?(?:.*?consecutive sessions)?", chunk, re.I | re.S)
        mastery = int(mastery_match.group(1)) if mastery_match else 80

        # Percentages
        percents = [int(x) for x in re.findall(r"(?<!\d)(\d{1,3})\s*%", chunk)]
        # First percent is usually mastery, then baseline, then current
        baseline = 0
        current = None
        if len(percents) >= 3:
            baseline = percents[1]
            current = percents[2]
        elif len(percents) == 2:
            baseline = percents[0] if percents[0] != mastery else 0
            current = percents[1]

        # Dates
        dates = re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", chunk)
        baseline_date = parse_date(dates[0]) if dates else None

        # Target month/year
        target = None
        t = re.search(r"\b(0?[1-9]|1[0-2])/\d{4}\b", chunk)
        if t:
            target = t.group(0)

        if current is not None and baseline_date:
            programs.append({
                "domain": domain,
                "objective": objective,
                "mastery": mastery,
                "baseline": baseline,
                "baseline_date": baseline_date,
                "current": current,
                "target": target or ""
            })

    return programs

def concise_program_name(obj):
    x = obj.lower()
    if "comply" in x or "directions" in x and "30 seconds" in x:
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
    return "Skill Acquisition"

def generate_dates(start, end, n, seed):
    rng = random.Random(seed)
    span = (end - start).days
    if span <= n:
        n = max(2, span + 1)
    interior = sorted(rng.sample(range(1, span), n-2)) if n > 2 and span > 1 else []
    dates = [start] + [start + timedelta(days=d) for d in interior] + [end]
    return dates

def generate_values(n, baseline, current, mastery, seed):
    rng = random.Random(seed)
    vals = [baseline]
    for i in range(1, n-1):
        p = i/(n-1)
        target = baseline + (current-baseline)*(p**0.82)
        noise = rng.randint(-8, 8)
        v = round(target + noise)

        r = rng.random()
        if i > 2 and r < 0.12:
            v = vals[-1]                       # plateau
        elif i > 2 and r < 0.27:
            v = vals[-1] - rng.randint(4, 10) # regression
        elif i > 2 and r < 0.42:
            v = vals[-1] + rng.randint(4, 10) # recovery

        late_cap = max(current + 6, current)
        v = max(0, min(min(mastery-1, late_cap), v))
        if abs(v - vals[-1]) > 20:
            v = vals[-1] + (20 if v > vals[-1] else -20)
        vals.append(int(v))
    vals.append(current)
    return vals

def create_graph(p, goal_num, end_dt, n_points):
    start_dt = p["baseline_date"]
    if end_dt <= start_dt:
        raise ValueError("Current/reassessment date must be after baseline date.")

    dates = generate_dates(start_dt, end_dt, n_points, 1000 + goal_num*97)
    vals = generate_values(len(dates), p["baseline"], p["current"], p["mastery"], 2000 + goal_num*131)

    short = concise_program_name(p["objective"])
    title = f"{p['domain']} Goal #{goal_num}: {short}"

    fig, ax = plt.subplots(figsize=(20, 10), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.plot(dates, vals, marker="o", linewidth=2.2, markersize=5.5, color="#4472C4")
    ax.axhline(p["mastery"], linestyle="--", linewidth=2, color="#00A651")
    ax.text(end_dt - timedelta(days=max(1, (end_dt-start_dt).days//100)),
            p["mastery"] + 1.5,
            f"Mastery Criteria: {p['mastery']}% Accuracy",
            ha="right", va="bottom", fontsize=11, fontweight="bold", color="#008C3A")

    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10))
    ax.set_xlim(start_dt, end_dt)
    ax.set_ylabel("Accuracy (%)", fontsize=12, fontweight="bold")
    ax.set_xlabel("Session Date", fontsize=12, fontweight="bold")
    ax.grid(True, color="#D9D9D9", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # CRITICAL: every date gets a visible tick label
    ax.set_xticks(dates)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d/%Y"))
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right", fontsize=7.5)

    fig.suptitle(title, fontsize=20, fontweight="bold", y=0.97)
    subtitle = "\n".join(textwrap.wrap(p["objective"], width=115))
    ax.set_title(subtitle, fontsize=12.5, pad=18)
    plt.subplots_adjust(top=0.84, bottom=0.28, left=0.07, right=0.98)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return short, dates, vals, buf.getvalue()

if st.button("Create ABA Progress Graphs", type="primary", use_container_width=True):
    if not raw_text.strip():
        st.error("Paste the treatment-plan information first.")
    elif not client_name.strip():
        st.error("Enter the client name.")
    else:
        programs = find_programs(raw_text)
        if not programs:
            st.error("I couldn't reliably identify the programs. Check that each goal includes an objective, baseline date, baseline %, and current %.")
        else:
            st.success(f"Found {len(programs)} program(s).")

            end_dt = datetime.combine(current_date, datetime.min.time())
            zip_buffer = io.BytesIO()

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, p in enumerate(programs, start=1):
                    try:
                        short, dates, vals, png = create_graph(p, idx, end_dt, points_per_graph)
                        fn = f"{client_name}_Goal_{idx:02d}_{short.replace(' ', '_').replace('-', '_')}.png"
                        zf.writestr(fn, png)

                        with st.expander(f"Goal #{idx}: {short}", expanded=(idx == 1)):
                            st.image(png, use_container_width=True)
                            st.caption(
                                f"{len(dates)} session dates • "
                                f"Baseline {p['baseline']}% on {dates[0].strftime('%m/%d/%Y')} • "
                                f"Current {p['current']}% on {dates[-1].strftime('%m/%d/%Y')}"
                            )
                    except Exception as e:
                        st.error(f"Goal #{idx} could not be created: {e}")

            zip_buffer.seek(0)
            st.download_button(
                "Download All Graphs as ZIP",
                data=zip_buffer.getvalue(),
                file_name=f"{client_name}_ABA_Progress_Graphs.zip",
                mime="application/zip",
                use_container_width=True
            )
