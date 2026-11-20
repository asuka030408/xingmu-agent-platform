"""Errors that the HTTP boundary can show without exposing provider internals."""


class AgentError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status
