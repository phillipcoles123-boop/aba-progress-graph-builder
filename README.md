
# ABA Progress Graph Builder v2

Version 2 supports both skill-acquisition and behavior-reduction goals.

## New in v2
- Reads percent/accuracy goals
- Reads rate goals such as "instances per hour"
- Reads frequency/count goals
- Reads duration/latency goals
- Shows extracted fields in an editable review table before graphing
- Creates upward, downward, or worsening trends based on the actual baseline/current values
- Uses one visible X-axis date for every data point
- Creates a ZIP of all completed graphs

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Update an existing Streamlit Cloud app

Replace your current `app.py` and `requirements.txt` in GitHub with the files from this package.
Streamlit Cloud should redeploy automatically after the GitHub commit.
