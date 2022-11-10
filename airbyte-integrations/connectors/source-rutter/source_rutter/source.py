#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#

from __future__ import annotations

from abc import ABC
from datetime import datetime, time, timedelta
from pendulum import DateTime, Period
import pendulum
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Type, Union, Dict

import requests
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream, IncrementalMixin
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth import BasicHttpAuthenticator
from airbyte_cdk.models import SyncMode

date_format = "%Y-%m-%dT%H:%M:%S.%fZ"
#epoch = datetime(1970, 1, 1)

class RutterStream(HttpStream, ABC):
    url_base = "https://production.rutterapi.com/"
    primary_key = "id"
    limit = 10
    resource_name = ""

    def path(self, **kwargs) -> str:
        return self.resource_name

    @staticmethod
    def next_page_token(response: requests.Response) -> Optional[Mapping[str, Any]]:
        next_page_token = response.json().get("next_cursor")
        if next_page_token:
            return {"cursor":next_page_token}
        else:
            return None

    def request_params(
        self, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        params = {"limit": self.limit,"force_fetch": "true"}
        if next_page_token:
            params.update(next_page_token)
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get(self.resource_name, [])

    def read_slices_from_records(self, stream_class: Type[RutterStream], slice_field: str) -> Iterable[Optional[Mapping[str, Any]]]:
        stream = stream_class(authenticator=self.authenticator)
        stream_slices = stream.stream_slices(sync_mode=SyncMode.full_refresh)
        for stream_slice in stream_slices:
            for record in stream.read_records(sync_mode=SyncMode.full_refresh, stream_slice=stream_slice):
                yield {slice_field: record["access_token"]}
class IncrementalRutterStream(RutterStream, IncrementalMixin):
    start_date_filter = "updated_at_min"
    end_date_filter = "updated_at_max"
    _initial_cursor = ""
    #min_id = "1900-01-01T00:00:00.00Z"
    min_id = "2022-11-09T00:00:00.00Z"
    cursor_field = "updated_at"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cursor_value = self.min_id
        self._initial_cursor = self.state.get(self.cursor_field) or self.min_id

    @property
    def state_checkpoint_interval(self) -> int:
        return super().limit

    @property
    def state(self) -> Mapping[str, Any]:
#        return {self.cursor_field: self._cursor_value}
        if self._cursor_value:
            return {self.cursor_field: self._cursor_value}
        elif self.state.get(self.cursor_field):
            return {self.cursor_field: self.state.get(self.cursor_field)}
        else:
            return {self.cursor_field: self.min_id}

    @state.setter
    def state(self, value: Mapping[str, Any]):
        self._cursor_value = value.get(self.cursor_field)

    def request_params(self, next_page_token: Mapping[str, Any] = None, **kwargs):
        params = super().request_params(stream_state=self.state, next_page_token=next_page_token, **kwargs)
        last_stream_state = self._initial_cursor
        unix_last_stream_state = int(pendulum.parse(last_stream_state).timestamp()) * 1000
        params[self.start_date_filter] = unix_last_stream_state
        if last_stream_state:
            last_stream_filter = {self.start_date_filter: unix_last_stream_state}
            params.update(last_stream_filter)
        return params

    def parse_response(self, response: requests.Response, stream_state: Mapping[str, Any], **kwargs) -> Iterable[Mapping]:
        for record in super().parse_response(response=response, stream_state=self.state, **kwargs):
            if record[self.cursor_field] > stream_state[self.cursor_field]:
                self._cursor_value = record[self.cursor_field]
                yield record

    def read_records(self, *args, **kwargs) -> Iterable[Mapping[str, Any]]:
        for record in super().read_records(*args, **kwargs):
            if self._cursor_value:
                latest_record_date = record[self.cursor_field]
                self._cursor_value = max(self._cursor_value, latest_record_date)
            yield record
class Connections(RutterStream):
    resource_name = "connections"
class ConnectionsRelatedStream(RutterStream, ABC):    
    def stream_slices(
        self, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        yield from self.read_slices_from_records(stream_class=Connections, slice_field="access_token")

    def parse_response(self, response: requests.Response, stream_slice: Mapping[str, any] = None, stream_state: Mapping[str, any] = None, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        data = response_json.get(self.resource_name, [])
        connection = response_json['connection']
        connection['connection_id'] = connection['id']
        del connection['id']
        for id in data:
            id.update(connection)
        yield from data
class Orders(ConnectionsRelatedStream, IncrementalRutterStream):
    resource_name = "orders"

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        params = super().request_params(next_page_token=next_page_token, **kwargs)
        stream_params = {"access_token":stream_slice["access_token"], "expand":"transactions"}
#        stream_params = {"access_token":"b90ccb1f-383f-4180-bf8b-c101e42c1390"}
        params.update(stream_params)
        return params

class Customers(ConnectionsRelatedStream):
    resource_name = "customers"

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        params = {"access_token":stream_slice["access_token"]}
        return params
class Products(ConnectionsRelatedStream):
    resource_name = "products"

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        params = {"access_token":stream_slice["access_token"]}
        return params
class SourceRutter(AbstractSource):
    def check_connection(self, logger, config: Mapping[str, Any]) -> Tuple[bool, any]:
        try:
            auth=BasicHttpAuthenticator(username=config["client_id"], password=config["client_secret"])
            orders_gen = Connections(authenticator=auth).read_records(sync_mode=SyncMode.full_refresh)
            next(orders_gen)
            return True, None
        except Exception as error:
            return False, f"Unable to connect to Rutter API with the provided credentials - {repr(error)}"

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth = BasicHttpAuthenticator(username=config["client_id"], password=config["client_secret"])
        full_refresh_stream_kwargs = {"authenticator": auth}
        incremental_stream_kwargs = {"authenticator": auth}
        return [
            Connections(**full_refresh_stream_kwargs),
            Orders(**incremental_stream_kwargs),
#            Customers(**full_refresh_stream_kwargs),
#            Products(**full_refresh_stream_kwargs),
        ]