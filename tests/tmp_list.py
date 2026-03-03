with open(r"d:\\Personal_Files\\Projects\\Github\\Local-project\\modules\\llm.py", encoding="utf-8") as f:
    for i, line in enumerate(f, start=1):
        if 20 <= i <= 60:
            print(f"{i:03}: {line.rstrip()}")
