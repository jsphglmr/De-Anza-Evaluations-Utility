# De Anza C-ID Lookup

A small desktop app to look up C-ID course equivalencies for De Anza College. Pick a department and course; the table shows equivalent courses at De Anza and other schools.

## Run it

Requires [UV](https://docs.astral.sh/uv/) and a file named **`cid.csv`** in the same folder as the app.

```bash
cd eval_gui
uv sync
uv run python course_equivalency_app_dpg.py
```

## Data

Put **`cid.csv`** in the project directory. It must be a CSV with these columns (exact names):

- `C-ID #`
- `C-ID Descriptor`
- `Institution`
- `Local Course Title(s)`
- `Local Dept. Name & Number`

If the file is missing or the format is wrong, the app will show an error when it starts.

This application has been developed for internal use by De Anza Evaluations.