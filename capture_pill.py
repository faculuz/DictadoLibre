import sys
from PySide6.QtWidgets import QApplication
from DictadoLibre import Pill, APP_QSS, app_font

app = QApplication(sys.argv)
app.setStyleSheet(APP_QSS)
# Just use default font if app_font needs more context
# app.setFont(app_font())

pill = Pill()
pill.show()

pill.on_state("grabando", "dictado")
pill.grab().save("pill_grabando.png")

pill.on_state("procesando", "formal")
pill.grab().save("pill_procesando.png")

print("Saved.")
