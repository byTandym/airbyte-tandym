#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#

from __future__ import annotations

from abc import ABC
import datetime
import pendulum
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Type, Union, Dict

import requests
from .utils import EagerlyCachedStreamState as stream_state_cache
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth import BasicHttpAuthenticator, TokenAuthenticator
from airbyte_cdk.models import SyncMode


class RutterStream(HttpStream, ABC):
    url_base = "https://production.rutterapi.com/"
    primary_key = "id"
    filter_field = "updated_at_min"
    limit = 50

    @staticmethod
    def next_page_token(response: requests.Response) -> Optional[Mapping[str, Any]]:
        next_page_token = response.json().get("next_cursor")
        if next_page_token:
            return next_page_token
        else:
            return None

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        params = {"limit": self.limit}
        if next_page_token:
            params.update(**next_page_token)
        else:
            params[self.filter_field] = self.default_filter_field_value
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json

    def read_slices_from_records(self, stream_class: Type[RutterStream], slice_field: str) -> Iterable[Optional[Mapping[str, Any]]]:
        stream = stream_class(authenticator=self.authenticator)
        stream_slices = stream.stream_slices(sync_mode=SyncMode.full_refresh)
        for stream_slice in stream_slices:
            for record in stream.read_records(sync_mode=SyncMode.full_refresh, stream_slice=stream_slice):
                yield {slice_field: record["access_token"]}

    @property
    def default_filter_field_value(self) -> Union[int, str]:
        # certain streams are using `since_id` field as `filter_field`, which requires to use `int` type,
        # but many other use `str` values for this, we determine what to use based on `filter_field` value
        # by default, we use the user defined `Start Date` as initial value, or 0 for `id`-dependent streams.
        return 0 if self.filter_field == "since_id" else 1666270917000

class IncrementalRutterStream(RutterStream, ABC):
    cursor_field = "updated_at"

    @property
    def state_checkpoint_interval(self) -> int:
        return super().limit

    @property
    def default_state_comparison_value(self) -> Union[int, str]:
        # certain streams are using `id` field as `cursor_field`, which requires to use `int` type,
        # but many other use `str` values for this, we determine what to use based on `cursor_field` value
        return 0 if self.cursor_field == "id" else ""

    def get_updated_state(self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        """
        Return the latest state by comparing the cursor value 
        in the latest record with the stream's most recent state object
        and returning an updated state object.
        """
        return {
            self.cursor_field: max(
                latest_record.get(self.cursor_field, self.default_state_comparison_value),
                current_stream_state.get(self.cursor_field, self.default_state_comparison_value),
            )
        }

    @stream_state_cache.cache_stream_state
    def request_params(self, stream_state: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None, **kwargs):
        params = super().request_params(stream_state=stream_state, next_page_token=next_page_token, **kwargs)
        # If there is a next page token then we should only send pagination-related parameters.
        if not next_page_token:
            if stream_state:
                params[self.filter_field] = stream_state.get(self.cursor_field)
        return params
class Connections(RutterStream):
    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "connections"
    
    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("connections", [])

class ConnectionsRelatedStream(RutterStream, ABC):    
    def stream_slices(
        self, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        yield from self.read_slices_from_records(stream_class=Connections, slice_field="access_token")

class Orders(ConnectionsRelatedStream, IncrementalRutterStream):
    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "orders"

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = {"access_token":stream_slice["access_token"], "cursor":next_page_token, "expand":"transactions"}
        return params

    def parse_response(self, response: requests.Response, stream_slice: Mapping[str, any] = None, stream_state: Mapping[str, any] = None, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        data = response_json.get("orders", [])
        connection = response_json['connection']
        connection['connection_id'] = connection['id']
        del connection['id']        
        
        for id in data:
            id.update(connection)
        yield from data
class Customers(ConnectionsRelatedStream):
    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "customers"

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = {"access_token":stream_slice["access_token"], "cursor":next_page_token}
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        data = response_json.get("customers", [])
        connection = response_json['connection']
        connection['connection_id'] = connection['id']
        del connection['id']        
        
        for id in data:
            id.update(connection)
        yield from data

class Products(ConnectionsRelatedStream):
    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "products"

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = {"access_token":stream_slice["access_token"],"cursor":next_page_token}
        return params

    def parse_response(self, response: requests.Response,stream_slice: Mapping[str, any] = None, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        data = response_json.get("products", [])
        connection = response_json['connection']
        connection['connection_id'] = connection['id']
        del connection['id']        
        
        for id in data:
            id.update(connection)
        yield from data
class SourceRutter(AbstractSource):
    @staticmethod
    def _get_authenticator(config: dict):
        auth = BasicHttpAuthenticator(username=config["client_id"], password=config["client_secret"])
        return auth

    def check_connection(self, logger, config: Mapping[str, Any]) -> Tuple[bool, any]:
        try:
            auth=self._get_authenticator(config)
            orders_gen = Connections(authenticator=auth).read_records(sync_mode=SyncMode.full_refresh)
            next(orders_gen)
            return True, None
        except Exception as error:
            return False, f"Unable to connect to Rutter API with the provided credentials - {repr(error)}"

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth = self._get_authenticator(config)
        full_refresh_stream_kwargs = {"authenticator": auth}
        incremental_stream_kwargs = {
            "authenticator": auth,
#            "updated_at": config["start_date"],
        }
        streams = [
            Connections(**full_refresh_stream_kwargs),
            Orders(**incremental_stream_kwargs),
            Customers(**full_refresh_stream_kwargs),
            Products(**full_refresh_stream_kwargs),
        ]        
        return streams