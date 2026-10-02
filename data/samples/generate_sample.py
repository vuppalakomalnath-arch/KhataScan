"""Script to generate a synthetic ledger image for testing and demos."""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path


def generate_synthetic_ledger(output_path: str = "data/samples/sample_ledger_1.png"):
    width, height = 1200, 1600
    img = Image.new("RGB", (width, height), color="#FFFDF7")  # Khata notebook paper color
    draw = ImageDraw.Draw(img)

    # Draw ruled lines
    margin_top = 180
    row_height = 80
    margin_left = 60
    margin_right = width - 60

    # Draw header line
    draw.line([(margin_left, 120), (margin_right, 120)], fill="#B0C4DE", width=3)
    draw.line([(margin_left, 130), (margin_right, 130)], fill="#E67E22", width=2)

    # Draw title
    draw.text((margin_left + 20, 50), "SRI RAMESH GENERAL STORE - KHATA BOOK", fill="#2C3E50")
    draw.text((margin_left + 20, 85), "Date: 02/10/2026", fill="#555555")

    # Column headers
    headers = ["Date", "Customer Name", "Description", "Type", "Amount (Rs)"]
    col_x = [margin_left + 10, margin_left + 160, margin_left + 460, margin_left + 780, margin_left + 950]
    for x, h in zip(col_x, headers):
        draw.text((x, 145), h, fill="#1B4F72")

    # Draw horizontal rules
    for y in range(margin_top, height - 150, row_height):
        draw.line([(margin_left, y), (margin_right, y)], fill="#D5D8DC", width=1)

    # Vertical separators
    for x in [margin_left + 140, margin_left + 440, margin_left + 760, margin_left + 930]:
        draw.line([(x, 130), (x, height - 150)], fill="#EAEDED", width=1)

    # Sample rows (8 rows)
    rows = [
        ("02/10", "Ramesh Kumar", "Rice 10kg, Dal 2kg", "Credit", "1250"),
        ("02/10", "Suresh Raina", "Cooking Oil 2L", "Credit", "350"),
        ("02/10", "Mahesh Babu", "Monthly Udhaar clearance", "Payment", "2000"),
        ("02/10", "Kiran Sharma", "Sugar 5kg, Tea powder", "Credit", "450"),
        ("02/10", "Venkatesh Rao", "Soap, Detergent box", "Credit", "220"),
        ("02/10", "Ganesh Gowda", "Snacks, Biscuits", "Credit", "180"),
        ("02/10", "Naresh Patel", "Partial Cash Payment", "Payment", "500"),
        ("02/10", "Lakshmi Devi", "Atta 10kg, Spices", "Credit", "850"),
    ]

    for idx, (dt, name, desc, ttype, amt) in enumerate(rows):
        y = margin_top + (idx * row_height) + 25
        draw.text((col_x[0], y), dt, fill="#17202A")
        draw.text((col_x[1], y), name, fill="#1A5276")
        draw.text((col_x[2], y), desc, fill="#2E4053")
        draw.text((col_x[3], y), ttype, fill="#78281F" if ttype == "Credit" else "#145A32")
        draw.text((col_x[4], y), amt, fill="#17202A")

    # Grand total box
    # Total credit sum = 1250 + 350 + 450 + 220 + 180 + 850 = 3300
    draw.line([(margin_left, height - 150), (margin_right, height - 150)], fill="#2C3E50", width=2)
    draw.text((margin_left + 650, height - 120), "Total Credit Amount: Rs. 3300", fill="#78281F")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    print(f"Synthetic ledger saved to {output_path}")


if __name__ == "__main__":
    generate_synthetic_ledger()
