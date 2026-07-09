from app.email_comm.enums import EmailProviderEnum
from app.email_comm.exceptions import UnsupportedProviderError
from app.email_comm.models import EmailAccount
from app.email_comm.providers.base import EmailProviderClient, RawEmailMessage
from app.email_comm.providers.gmail import GmailClient
from app.email_comm.providers.imap import ImapClientWrapper
from app.email_comm.providers.outlook import OutlookClient


def build_client(account: EmailAccount, *, access_token: str, refresh_token: str | None = None, imap_password: str | None = None) -> EmailProviderClient:
    """Factory that builds the right provider client for an EmailAccount.
    Callers are responsible for decrypting tokens/passwords beforehand via
    app.core.security before passing them in.
    """
    if account.provider == EmailProviderEnum.GMAIL:
        return GmailClient(access_token=access_token, refresh_token=refresh_token, email_address=account.email_address)
    if account.provider == EmailProviderEnum.OUTLOOK:
        return OutlookClient(access_token=access_token, refresh_token=refresh_token, email_address=account.email_address)
    if account.provider == EmailProviderEnum.IMAP:
        return ImapClientWrapper(
            host=account.imap_host,
            port=account.imap_port or 993,
            use_ssl=account.imap_use_ssl,
            email_address=account.email_address,
            password=imap_password or "",
        )
    raise UnsupportedProviderError(account.provider.value)


__all__ = ["build_client", "EmailProviderClient", "RawEmailMessage", "GmailClient", "OutlookClient", "ImapClientWrapper"]
