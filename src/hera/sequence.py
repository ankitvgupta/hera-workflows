from pydantic import validator

from hera.models import Sequence as _ModelSequence


class Sequence(_ModelSequence):
    @validator("count", pre=True)
    def count_to_str(cls, v):
        if v is None:
            return v

        assert isinstance(v, int) or isinstance(v, str)
        if isinstance(v, str):
            return v
        return str(v)

    @validator("start", pre=True)
    def start_to_str(cls, v):
        if v is None:
            return v

        assert isinstance(v, int) or isinstance(v, str)
        if isinstance(v, str):
            return v
        return str(v)

    @validator("start", pre=True)
    def end_to_str(cls, v):
        if v is None:
            return v

        assert isinstance(v, int) or isinstance(v, str)
        if isinstance(v, str):
            return v
        return str(v)


__all__ = ["Sequence"]
