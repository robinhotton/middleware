"""Dicts de reponses HTTP communs pour la documentation Swagger."""

R400: dict = {400: {"description": "Requete invalide"}}
R401: dict = {401: {"description": "Non authentifie"}}
R403: dict = {403: {"description": "Acces interdit"}}
R404: dict = {404: {"description": "Ressource introuvable"}}
R409: dict = {409: {"description": "Conflit"}}
R422: dict = {422: {"description": "Erreur de validation"}}
R429: dict = {429: {"description": "Trop de requetes — reessayez plus tard"}}
