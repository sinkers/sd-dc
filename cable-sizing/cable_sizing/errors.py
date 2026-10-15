"""Exceptions. Every failure mode is explicit; nothing degrades to a default."""


class CableCalcError(Exception):
    """Base for all errors raised by this package."""


class MissingTableData(CableCalcError):
    """A required table value is not present in the loaded data set.

    Carries enough detail that the operator knows exactly which page of the
    licensed standard still has to be transcribed.
    """

    def __init__(self, table: str, key: dict, source: str = ""):
        self.table = table
        self.key = key
        self.source = source
        detail = ", ".join(f"{k}={v!r}" for k, v in key.items())
        src = f" (standard reference: {source})" if source else ""
        super().__init__(f"No value in table {table!r} for {detail}{src}")


class InvalidDeclaration(CableCalcError):
    """Inputs are internally inconsistent, e.g. a derating applied twice."""


class OpenItem(CableCalcError):
    """A deliberately unresolved item.

    Raised where the spec records that no defensible default exists. Better a
    loud stop than a plausible number.
    """


class NoCompliantSize(CableCalcError):
    """No conductor in the candidate set satisfies every check."""

    def __init__(self, message: str, blocking: dict | None = None):
        self.blocking = blocking or {}
        super().__init__(message)


class InadmissibleFactor(CableCalcError):
    """A correction factor was requested for an influence the base rating
    column already accounts for.

    Not merely redundant: applying it double-counts. Thermal insulation contact
    and solar radiation are the two that catch people out, because both look
    like factors and are in fact base-rating columns. See M4 Rev B section 4.5.
    """
