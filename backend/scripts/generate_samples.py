"""Generate realistic sample receipts for demos.

Usage:  python scripts/generate_samples.py  ->  writes files to ./samples

PDFs get a real text layer (readable by every provider, including the offline
mock); the PNG is image-only and needs a vision model (Ollama/Claude).
"""

from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "samples"
TODAY = date.today()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).strftime("%d/%m/%Y")


RECEIPTS: dict[str, list[str]] = {
    "indigo_flight.pdf": [
        "IndiGo Airlines", "Tax Invoice / Boarding Pass", f"Invoice No: 6E-INV-88213", f"Date: {d(9)}",
        "PNR: QX7T2L   Flight 6E-5327  BOM -> BLR", "Passenger: Aarav Sharma",
        "Base Fare            Rs. 5,420.00", "Airport Fee          Rs. 610.00", "IGST 5%              Rs. 301.50",
        "Total Amount         Rs. 6,331.50", "Paid via: Corporate Card", "City: Mumbai",
    ],
    "taj_hotel_invoice.pdf": [
        "Taj MG Road Bengaluru", "Hotel Invoice", "Invoice No: TAJ-BLR-44109", f"Date: {d(7)}",
        "Guest: Aarav Sharma   Room 1207   2 nights", "Room Charges 2 x 7,800     15,600.00",
        "CGST 6%                    936.00", "SGST 6%                    936.00",
        "Grand Total INR 17,472.00", "Payment Mode: Credit Card", "City: Bengaluru",
    ],
    "uber_ride.pdf": [
        "Uber India", "Trip receipt", f"Date: {d(8)}", "Pickup: Kempegowda Airport  Drop: MG Road",
        "Trip fare         Rs 742.30", "Tolls             Rs 85.00", "Total             Rs 827.30",
        "Paid by: UPI", "City: Bengaluru",
    ],
    "uber_ride_copy.pdf": [
        "Uber India", "Trip receipt", f"Date: {d(8)}", "Pickup: Kempegowda Airport  Drop: MG Road",
        "Trip fare         Rs 742.30", "Tolls             Rs 85.00", "Total             Rs 827.30",
        "Paid by: UPI", "City: Bengaluru",
    ],
    "client_dinner.pdf": [
        "Toit Brewpub Indiranagar", "Bill No: TB-20931", f"Date: {d(7)}",
        "Paneer Tikka                  420.00", "Butter Chicken                560.00",
        "Craft Beer (2)                780.00", "Sub Total                    1,760.00",
        "GST 5%                         88.00", "Total Amount Rs. 1,848.00", "City: Bengaluru",
    ],
    "jiofiber_broadband_bill.pdf": [
        "JioFiber", "Broadband Bill / Tax Invoice", "Invoice No: JF-2026-771203", f"Date: {d(5)}",
        "Plan: 300 Mbps Unlimited   Billing period: Sep 2026", "Plan charges           999.00",
        "CGST 9%                   89.91", "SGST 9%                   89.91", "Total Amount Rs. 1,178.82",
        "Payment Mode: UPI", "City: Mumbai",
    ],
    "indian_oil_bike_fuel.pdf": [
        "Indian Oil - Shree Sai Fuels", "Fuel Receipt", "Bill No: IOC-55821", f"Date: {d(3)}",
        "Vehicle: Two Wheeler (Activa)  MH-02-AB-1234", "Petrol 3.20 L x 104.21     333.47",
        "Total Amount Rs. 333.47", "Paid by: Card", "City: Mumbai",
    ],
    "apollo_pharmacy_bill.pdf": [
        "Apollo Pharmacy", "Cash Memo", "Bill No: APL-90311", f"Date: {d(4)}",
        "Paracetamol 650mg x 2     64.00", "Vitamin D3 Sachet x 4     220.00",
        "Total Amount Rs. 284.00", "Payment Mode: UPI", "City: Mumbai",
    ],
    "starbucks_coffee.pdf": [
        "Starbucks Coffee", "Order No: SB-7781", f"Date: {d(6)}", "Caffe Latte Grande    310.00",
        "Croissant             180.00", "Total ₹ 490.00", "Payment Method: Card",
    ],
}


def write_text_pdf(path: Path, lines: list[str]) -> None:
    """Minimal single-page PDF with a Helvetica text layer (no extra deps)."""
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("₹", "Rs.")

    body = ["BT", "/F1 12 Tf", "14 TL", "60 780 Td"]
    for i, line in enumerate(lines):
        body.append(f"/F1 {16 if i == 0 else 11} Tf ({esc(line)}) Tj T*")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))


def write_photo_receipt(path: Path) -> None:
    lines = ["CHAI POINT", "Koramangala, Bengaluru", f"Date: {d(6)}", "", "Masala Chai x2     120.00",
             "Veg Sandwich       150.00", "", "TOTAL         Rs. 270.00", "", "Thank you!"]
    image = Image.new("RGB", (420, 560), (250, 248, 240))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("Courier New.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    for i, line in enumerate(lines):
        draw.text((30, 30 + i * 44), line, fill=(30, 30, 30), font=font)
    image.rotate(2, expand=True, fillcolor=(200, 200, 200)).save(path)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, lines in RECEIPTS.items():
        write_text_pdf(OUT / name, lines)
    write_photo_receipt(OUT / "chai_point_photo.png")
    print(f"Wrote {len(RECEIPTS) + 1} sample receipts to {OUT}")


if __name__ == "__main__":
    main()
