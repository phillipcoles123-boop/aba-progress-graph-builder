
# ABA Progress Graph Builder

A simple Streamlit app for turning pasted ABA treatment-plan goals into professional progress graphs.

## What it does
- Paste treatment-plan text directly from Word/PDF
- Extracts multiple objectives
- Creates one ABA graph per objective
- Uses irregular session dates
- Shows one visible date label for every data point
- Adds mastery criteria
- Packages all graphs into a ZIP file

## Run locally

1. Install Python 3.10+
2. Open Terminal in this folder
3. Run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local web address Streamlit gives you.

## Recommended workflow
1. Enter the client name
2. Choose the reassessment/current date
3. Paste the entire treatment-plan goal table
4. Click **Create ABA Progress Graphs**
5. Preview each graph
6. Download the ZIP
