def safe_csv(value):
    """Stop spreadsheet apps from running a cell as a formula (CSV injection)."""
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text
