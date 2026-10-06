"""Draw the abSCADA application icon (packaging/abscada.ico) with Qt, no image editor needed.

Dark rounded square, green pilot lamp and a gauge needle: the same identity as the website.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QRadialGradient  # noqa: E402

HERE = Path(__file__).resolve().parent


def draw(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#0f1412"))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    # Gauge arc and needle
    p.setPen(QPen(QColor("#3b4741"), 14 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(48 * s, 52 * s, 160 * s, 160 * s), 210 * 16, -240 * 16)
    p.setPen(QPen(QColor("#e89a1c"), 14 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(48 * s, 52 * s, 160 * s, 160 * s), -10 * 16, -20 * 16)
    p.setPen(QPen(QColor("#ecefe9"), 10 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(128 * s, 132 * s), QPointF(178 * s, 92 * s))
    # Pilot lamp as the hub
    glow = QRadialGradient(QPointF(128 * s, 132 * s), 34 * s)
    glow.setColorAt(0, QColor(57, 245, 162, 200))
    glow.setColorAt(1, QColor(57, 245, 162, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QPointF(128 * s, 132 * s), 34 * s, 34 * s)
    p.setBrush(QColor("#39f5a2"))
    p.drawEllipse(QPointF(128 * s, 132 * s), 18 * s, 18 * s)
    p.end()
    return image


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    target = HERE / "abscada.ico"
    if not draw(256).save(str(target), "ICO"):
        raise SystemExit("Qt no pudo escribir el ICO (falta el plugin qico)")
    draw(512).save(str(HERE / "abscada.png"), "PNG")
    print(target)


if __name__ == "__main__":
    main()
