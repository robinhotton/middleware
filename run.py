"""Script de lancement pour IDE et debug.

Lit HOST et PORT depuis les settings (.env) et lance uvicorn avec hot-reload.
Equivalent de 'make run' mais utilisable directement depuis un IDE (PyCharm, VS Code).

Usage :
    python run.py
"""

if __name__ == "__main__":
    import uvicorn

    from src.conf.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
