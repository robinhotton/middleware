"""Service d'envoi de mails transactionnels."""

from fastapi_mail import FastMail, MessageSchema, MessageType


class EmailService:
    """Envoie les mails transactionnels de l'application en texte brut."""

    def __init__(self, mail: FastMail, from_name: str, base_url: str, api_prefix: str):
        self.mail = mail
        self.from_name = from_name
        self._base_url = base_url
        self._api_prefix = api_prefix

    def _verification_url(self, token: str) -> str:
        return f"{self._base_url}{self._api_prefix}/auth/verify-email?token={token}"

    def _reset_url(self, token: str) -> str:
        return f"{self._base_url}{self._api_prefix}/auth/confirm-reset?token={token}"

    async def send_verification_link(self, to: str, token: str) -> None:
        """Mail de verification d'email envoye apres inscription."""
        body = (
            f"Bienvenue sur {self.from_name} !\n\n"
            "Pour activer votre compte, cliquez sur le lien ci-dessous :\n"
            f"{self._verification_url(token)}\n\n"
            "Ce lien est valable 10 minutes. "
            "Si vous n'etes pas a l'origine de cette inscription, "
            "ignorez cet email.\n\n"
            "A bientot,\n"
            f"L'equipe {self.from_name}"
        )
        message = MessageSchema(
            subject=f"Activez votre compte {self.from_name}",
            recipients=[to],
            body=body,
            subtype=MessageType.plain,
        )
        await self.mail.send_message(message)

    async def send_reset_link(self, to: str, token: str) -> None:
        """Mail avec le lien de reinitialisation du mot de passe."""
        body = (
            f"Bonjour,\n\n"
            "Vous avez demande la reinitialisation de votre mot de passe.\n\n"
            "Cliquez sur le lien ci-dessous pour confirmer la modification :\n"
            f"{self._reset_url(token)}\n\n"
            "Ce lien est valable 10 minutes. "
            "Si vous n'etes pas a l'origine de cette demande, "
            "ignorez cet email.\n\n"
            "Cordialement,\n"
            f"L'equipe {self.from_name}"
        )
        message = MessageSchema(
            subject="Reinitialisation de votre mot de passe",
            recipients=[to],
            body=body,
            subtype=MessageType.plain,
        )
        await self.mail.send_message(message)
