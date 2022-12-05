import asyncio
from asyncio import Future
from enum import Enum
from functools import partial
from typing import Any, Dict, Sequence, Tuple, Type

from pvaccess import Channel as PvaChannel
from pvaccess import PVA, PvObject, ScalarType
from bluesky.protocols import Descriptor, Dtype, Reading
from epicscorelibs.ca import dbr

from ._channel import Channel, Monitor, ReadingValueCallback
from .core import NotConnected, T


dbr_to_dtype: Dict[ScalarType, Dtype] = {
    ScalarType.STRING: "string",
    ScalarType.SHORT: "integer",
    ScalarType.FLOAT: "number",
#    dbr.DBR_ENUM: "integer",
#    ScalarType.CHAR: "string",
    ScalarType.LONG: "integer",
    ScalarType.DOUBLE: "number",
#    dbr.DBR_ENUM_STR: "string",
#    dbr.DBR_CHAR_BYTES: "string",
#    dbr.DBR_CHAR_UNICODE: "string",
#    dbr.DBR_CHAR_STR: "string",
}

#'BOOLEAN', 'BYTE', 'FLOAT', 'INT', 'SHORT', 'UBYTE', 'UINT', 'ULONG', 'USHORT'

class PvaValueConverter:
    async def validate(self, pv: str):
        ...

    def to_pva(self, value):
        ...

    def from_pva(self, value):
        ...


class NullConverter(PvaValueConverter):
    def to_pva(self, value):
        return value

    def from_pva(self, value):
        return value


#class EnumConverter(CaValueConverter):
#    def __init__(self, enum_cls: Type[Enum]) -> None:
#        self.enum_cls = enum_cls
#
#    async def validate(self, pv: str):
#        value = await caget(pv, format=FORMAT_CTRL)
#        assert hasattr(value, "enums"), f"{pv} is not an enum"
#        unrecognized = set(v.value for v in self.enum_cls) - set(value.enums)
#        assert not unrecognized, f"Enum strings {unrecognized} not in {value.enums}"
#
#    def to_ca(self, value: Enum):
#        return value.value
#
#    def from_ca(self, value: AugmentedValue):
#        return self.enum_cls(value)


def make_pva_descriptor(source: str, desc: dict, value: PvObject) -> Descriptor:
    try:
        dtype = dbr_to_dtype[desc['value']]
        shape = []
    except (KeyError, TypeError):
        assert isinstance(
            desc['value'], list            
        ), f"Can't get dtype for {value} with datatype {desc['value']}"
        dtype = "array"
        shape = [len(value['value'])]
    return dict(source=source, dtype=dtype, shape=shape)

#def make_ca_reading(
#    value: AugmentedValue, converter: CaValueConverter
#) -> Tuple[Reading, Any]:
#    conv_value = converter.from_ca(value)
#    return (
#        dict(
#            value=conv_value,
#            timestamp=value.timestamp,
#            alarm_severity=-1 if value.severity > 2 else value.severity,
#        ),
#        conv_value,
#    )

def make_ca_reading(
    value: PvObject, converter: PvaValueConverter
) -> Tuple[Reading, Any]:
    conv_value = converter.from_pva(value)
    return (
        dict(
            value=conv_value,
            timestamp=value.timestamp,
            alarm_severity=-1 if value.severity > 2 else value.severity,
        ),
        conv_value,
    )


class ChannelPva(Channel[T]):
    converter: PvaValueConverter

    def __init__(self, pv: str, datatype: Type[T]):
        super().__init__(pv, datatype)
        self._converter = NullConverter()
        self.pva_datatype: type = datatype
        self._channel = None
#        if issubclass(datatype, Enum):
#            self.converter = EnumConverter(datatype)
#            self.ca_datatype = str

    @property
    def source(self) -> str:
        return f"pva://{self.pv}"

    async def connect(self):
        try:
            self._channel = PvaChannel(self.pv)
            await self._converter.validate(self.pv)
        except CancelledError:
            raise NotConnected(self.source)

    async def put(self, value: T, wait=True):
        put_method = partial(self.blocking_put, self._converter.to_pva(value))
        loop = asyncio.get_running_loop()
        if wait:
            await loop.run_in_executor(None, put_method)
        else:
            loop.run_in_executor(None, put_method)

    async def get_descriptor(self) -> Descriptor:
        loop = asyncio.get_running_loop()
        desc, value = await loop.run_in_executor(None, self.blocking_introspect)
        return make_pva_descriptor(self.source, desc, value)

    async def get_reading(self) -> Reading:
        loop = asyncio.get_running_loop()
        value = await loop.run_in_executor(None, self.blocking_get_reading)
        return make_ca_reading(value, self._converter)[0]

    async def get_value(self) -> T:
        loop = asyncio.get_running_loop()
        value = await loop.run_in_executor(None, self.blocking_get)
        return self._converter.from_pva(value)

    def monitor_reading_value(self, callback: ReadingValueCallback[T]) -> Monitor:
        return self.channel.monitor(
            lambda v: callback(*make_ca_reading(v, self._converter)),
            requestDescriptor='field(value,alarm,timestamp)'
        )

    def blocking_introspect(self):
        desc = self._channel.getIntrospectionDict()
        value = self._channel.get(requestDescriptor='field(value)')
        return (desc, value)

    def blocking_put(self, value):
        self._channel.put(value)

    def blocking_get(self):
        result = self._channel.get(requestDescriptor='field(value)')
        return result

    def blocking_get_reading(self):
        result = self._channel.get(requestDescriptor='field(value,alarm,timestamp)')
        return result
    