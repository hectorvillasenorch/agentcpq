class EmailActionError(Exception):
    pass


class EmailSendError(EmailActionError):
    pass