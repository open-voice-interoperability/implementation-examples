from dataclasses import dataclass, field, make_dataclass
from typing import Dict, List, Optional, Union, Any, Iterator, Tuple, ClassVar, Type, get_type_hints, Set
from abc import ABC, abstractmethod
import json

class JsonSerializable(ABC):
    """Abstract base class for JSON serializable objects"""

    @abstractmethod
    def __iter__(self) -> Iterator[Any]:
        raise NotImplementedError("Subclasses must implement this method")

    def _serialize_value(self, value: Any) -> Any:
        if isinstance(value, JsonSerializableList):
            return [self._serialize_value(item) for item in value]
        elif isinstance(value, (JsonSerializableDict, JsonSerializableDataclass)):
            return {k: self._serialize_value(v) for k, v in value}
        elif isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        elif hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
            return [self._serialize_value(item) for item in value]
        return value

    @classmethod
    def _json_default(cls, obj: Any) -> Any:
        if isinstance(obj, JsonSerializable):
            return obj.__json__()
        raise TypeError(f'Object of type {obj.__class__.__name__} is not JSON serializable')

    def to_json(self, **kwargs) -> str:
        return json.dumps(self, default=self._json_default, **kwargs)

    def __repr__(self) -> str:
        return self.to_json()

    def to_file(self, filepath: str, **kwargs) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self, f, default=self._json_default, **kwargs)

    @classmethod
    def from_json(cls, json_str: str) -> 'JsonSerializable':
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_file(cls, filepath: str, **kwargs) -> 'JsonSerializable':
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f, **kwargs)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JsonSerializableDict':
        if isinstance(data, cls):
            return data
        if isinstance(data, dict):
            return cls(**data)
        raise TypeError(f"Cannot create {cls.__name__} from {type(data)}")

    def __json__(self):
        return list(self)

class JsonSerializableDict(JsonSerializable):
    """Base class for JSON serializable objects that serialize to dictionaries"""

    def __init__(self, *args, **kwargs):
        self._data = {}
        if args and isinstance(args[0], dict):
            for key, value in args[0].items():
                self.__setitem__(key, value)
        for key, value in kwargs.items():
            self.__setitem__(key, value)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        for key, value in self._data.items():
            if isinstance(value, JsonSerializableList):
                yield key, [self._serialize_value(item) for item in value]
            elif isinstance(value, (JsonSerializableDict, JsonSerializableDataclass)):
                yield key, {k: self._serialize_value(v) for k, v in value}
            elif isinstance(value, list):
                yield key, [self._serialize_value(item) for item in value]
            elif isinstance(value, dict):
                yield key, {k: self._serialize_value(v) for k, v in value.items()}
            else:
                yield key, value

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def update(self, other: Dict[str, Any]) -> None:
        for key, value in other.items():
            self[key] = value

    def clear(self) -> None:
        self._data.clear()

    def copy(self) -> 'JsonSerializableDict':
        return self.__class__(**self._data.copy())

    def __json__(self):
        return {k: self._serialize_value(v) for k, v in self}

class JsonSerializableList(JsonSerializable):
    """Base class for JSON serializable objects that serialize to lists"""

    def __init__(self, *args, **kwargs):
        self._items = []
        if args and isinstance(args[0], list):
            self._items = list(args[0])
        elif args:
            self._items = list(args)

    def __iter__(self) -> Iterator[Any]:
        for item in self._items:
            if isinstance(item, JsonSerializableDict) or isinstance(item, JsonSerializableDataclass):
                yield dict(item)
            elif isinstance(item, JsonSerializableList):
                yield [i for i in item.__iter__()]
            else:
                yield self._serialize_value(item)

    def append(self, item: Any) -> None:
        self._items.append(item)

    def extend(self, items: List[Any]) -> None:
        self._items.extend(items)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> Any:
        return self._items[index]

    def __contains__(self, item: Any) -> bool:
        return item in self._items

    def __json__(self):
        return [self._serialize_value(item) for item in self]

    def to_json(self, **kwargs) -> str:
        return json.dumps(list(self), **kwargs)

    def to_file(self, filepath: str, **kwargs) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(list(self), f, **kwargs)

class JsonSerializableDataclass(JsonSerializable):
    """Base class for JSON serializable objects that are dataclasses"""

    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        for field_name, field_value in self.__dataclass_fields__.items():
            if not field_name.startswith('_'):
                value = getattr(self, field_name)
                yield field_name, self._serialize_value(value)

    def __json__(self):
        return {k: self._serialize_value(v) for k, v in self}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JsonSerializableDataclass':
        if isinstance(data, cls):
            return data
        if isinstance(data, dict):
            return cls(**data)
        raise TypeError(f"Cannot create {cls.__name__} from {type(data)}")

    def copy(self) -> 'JsonSerializableDataclass':
        return self.__class__(**{k: getattr(self, k) for k in self.__dataclass_fields__ if not k.startswith('_')})


def split_kwargs(cls: Type, kwargs: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split kwargs into defined and undefined fields for a dataclass class."""
    defined_fields: Set[str] = set()
    if hasattr(cls, '__dataclass_fields__'):
        defined_fields = set(cls.__dataclass_fields__.keys())

    defined_kwargs = {field: None for field in defined_fields}
    defined_kwargs.update({k: v for k, v in kwargs.items() if k in defined_fields})

    undefined_kwargs = {k: v for k, v in kwargs.items() if k not in defined_fields}

    return defined_kwargs, undefined_kwargs
