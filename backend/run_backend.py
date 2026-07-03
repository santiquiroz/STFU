"""Entry point para el binario empaquetado (PyInstaller)."""
import uvicorn

from stfu.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_config=None)
