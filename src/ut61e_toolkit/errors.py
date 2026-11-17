"""Errors that are safe to report through the CLI and agent tools."""


class DMMError(Exception):
    code = "dmm_error"


class ProtocolError(DMMError):
    code = "protocol_error"


class ConnectionError(DMMError):
    code = "connection_error"


class ReadTimeout(DMMError):
    code = "read_timeout"


class ReplayError(DMMError):
    code = "replay_error"
