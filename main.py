"""
ARC374 Final Project – Interactive Hotel Floor Plan Generator
Team: Chaemin Lim, Joshua Song, Ahania Soni

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
