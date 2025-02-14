from functools import partial
from promise import is_thenable, Promise
from sqlalchemy.orm.query import Query

from graphene.relay import Connection, ConnectionField
from graphene.relay.connection import PageInfo
from graphql_relay.connection.arrayconnection import connection_from_list_slice

from .utils import get_query, sort_argument_for_model


class UnsortedSQLAlchemyConnectionField(ConnectionField):
    @property
    def type(self):
        from .types import SQLAlchemyObjectType

        _type = super(ConnectionField, self).type
        if issubclass(_type, Connection):
            return _type
        assert issubclass(_type, SQLAlchemyObjectType), (
            "SQLALchemyConnectionField only accepts SQLAlchemyObjectType types, not {}"
        ).format(_type.__name__)
        assert _type._meta.connection, "The type {} doesn't have a connection".format(
            _type.__name__
        )
        return _type._meta.connection

    @property
    def model(self):
        return self.type._meta.node._meta.model

    @classmethod
    def get_query(cls, model, info, sort=None, **args):
        query = get_query(model, info.context)
        if sort is not None:
            if isinstance(sort, str):
                query = query.order_by(sort.value)
            else:
                query = query.order_by(*(col.value for col in sort))
        return query

    @classmethod
    def get_count(cls, query, model, info, **args):
        if isinstance(query, Query):
            _len = query.count()
        else:
            _len = len(query)
        return _len

    @classmethod
    def resolve_connection(cls, connection_type, model, info, args, resolved):
        if resolved is None:
            resolved = cls.get_query(model, info, **args)
        _len = cls.get_count(resolved, model, info, **args)
        connection = connection_from_list_slice(
            resolved,
            args,
            slice_start=0,
            list_length=_len,
            list_slice_length=_len,
            connection_type=connection_type,
            pageinfo_type=PageInfo,
            edge_type=connection_type.Edge,
        )
        connection.iterable = resolved
        connection.length = _len
        return connection

    @classmethod
    def connection_resolver(cls, resolver, connection_type, model, root, info, **args):
        resolved = resolver(root, info, **args)

        on_resolve = partial(cls.resolve_connection, connection_type, model, info, args)
        if is_thenable(resolved):
            return Promise.resolve(resolved).then(on_resolve)

        return on_resolve(resolved)

    def get_resolver(self, parent_resolver):
        return partial(self.connection_resolver, parent_resolver, self.type, self.model)


class SQLAlchemyConnectionField(UnsortedSQLAlchemyConnectionField):
    def __init__(self, type, *args, **kwargs):
        if "sort" not in kwargs and issubclass(type, Connection):
            # Let super class raise if type is not a Connection
            try:
                model = type.Edge.node._type._meta.model
                kwargs.setdefault("sort", sort_argument_for_model(model))
            except Exception:
                raise Exception(
                    'Cannot create sort argument for {}. A model is required. Set the "sort" argument'
                    " to None to disabling the creation of the sort query argument".format(
                        type.__name__
                    )
                )
        elif "sort" in kwargs and kwargs["sort"] is None:
            del kwargs["sort"]
        super(SQLAlchemyConnectionField, self).__init__(type, *args, **kwargs)


__connectionFactory = UnsortedSQLAlchemyConnectionField


def createConnectionField(_type):
    return __connectionFactory(_type)


def registerConnectionFieldFactory(factoryMethod):
    global __connectionFactory
    __connectionFactory = factoryMethod


def unregisterConnectionFieldFactory():
    global __connectionFactory
    __connectionFactory = UnsortedSQLAlchemyConnectionField
