"""
ARC374 Final Project – Interactive Hotel Floor Plan Generator
Team: Chaemin Lim, Joshua Song, Ahania Soni

Entry point. Run with:
    python main.py

Requirements:
    pip install pillow
    (tkinter is bundled with standard Python installations)
claude
Optional (for LLM prompt mode):
    pip install anthropic
    Set env var ANTHROPIC_API_KEY=<your key>
"""

import tkinter as tk
from app import HotelApp


def main():
    root = tk.Tk()
    root.title("Hotel Floor Plan Generator")
    root.resizable(True, True)
    app = HotelApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
