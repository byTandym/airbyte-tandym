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


class RutterStream(HttpStream, ABC):
    url_base = "https://production.rutterapi.com/"
    primary_key = "id"
    limit = 50
    resource_name = ""

    def __init__(
        self, 
        access_token: str, 
        start_date: str = None, 
        **kwargs):
        
        super().__init__(**kwargs)
        self.access_token = access_token
        self.start_date = start_date

    def path(
        self, **kwargs) -> str:
        return self.resource_name

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        next_page_token = response.json().get("next_cursor")
        if next_page_token:
            return {"cursor":next_page_token}
        else:
            return None

    def request_params(
        self, 
        stream_state: Mapping[str, Any], 
        stream_slice: Mapping[str, any] = None, 
        next_page_token: Mapping[str, Any] = None, 
        ) -> MutableMapping[str, Any]:
        
        params = {"limit": self.limit, "force_fetch": "true", "access_token": self.access_token, "updated_at_min": int(pendulum.parse(self.start_date).timestamp()) * 1000}
        if next_page_token:
            params.update(next_page_token)
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get(self.resource_name, [])
class IncrementalRutterStream(RutterStream, ABC):
    
    @property
    def cursor_field(self) -> str:
        return "updated_at"

    def get_updated_state(
        self, 
        current_stream_state: MutableMapping[str, Any], 
        latest_record: Mapping[str, Any]
        ) -> Mapping[str, Any]:
        
        current_stream_state = current_stream_state or {}

        current_stream_state_date = current_stream_state.get(self.cursor_field, self.start_date)
        latest_record_date = latest_record.get(self.cursor_field, self.start_date)

        return {self.cursor_field: max(current_stream_state_date, latest_record_date)}

    def request_params(
        self, 
        stream_state: Mapping[str, Any], 
        stream_slice: Mapping[str, any] = None, 
        next_page_token: Mapping[str, Any] = None
        ) -> MutableMapping[str, Any]:
        
        params = super().request_params(stream_state=stream_state, stream_slice=stream_slice, next_page_token=next_page_token)
        if self.cursor_field in stream_state:
            params["updated_at_min"] = int(pendulum.parse(stream_state[self.cursor_field]).timestamp()) * 1000
            #params["updated_at[gte]"] = stream_state[self.cursor_field]
        return params
class Connections(RutterStream):
    resource_name = "connections"
class Orders(IncrementalRutterStream):
    resource_name = "orders"
    cursor_field = "updated_at"

    def request_params(
        self, 
        stream_state: Mapping[str, Any], 
        stream_slice: Mapping[str, any] = None, 
        next_page_token: Mapping[str, Any] = None
        ) -> MutableMapping[str, Any]:
        
        params = super().request_params(stream_state=stream_state, stream_slice=stream_slice, next_page_token=next_page_token)
        params["expand"] = "transactions"
        return params

    def parse_response(
        self,
        response: requests.Response, 
        **kwargs
        ) -> Iterable[Mapping]:
        
        response_json = response.json()
        data = response_json.get(self.resource_name, [])
        connection = response_json['connection']
        connection['connection_id'] = connection['id']
        del connection['id']        
        
        for id in data:
            id.update(connection)
        yield from data
class Customers(IncrementalRutterStream):
    resource_name = "customers"
    cursor_field = "updated_at"
class SourceRutter(AbstractSource):
    def check_connection(self, logger, config: Mapping[str, Any]) -> Tuple[bool, any]:
        try:
            auth=BasicHttpAuthenticator(username=config["client_id"], password=config["client_secret"])
            access_token = config["access_token"]
            start_date = config["start_date"]
            orders_gen = Connections(authenticator=auth, access_token=access_token, start_date=start_date).read_records(sync_mode=SyncMode.full_refresh)
            next(orders_gen)
            return True, None
        except Exception as error:
            return False, f"Unable to connect to Rutter API with the provided credentials - {repr(error)}"

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth = BasicHttpAuthenticator(username=config["client_id"], password=config["client_secret"])
        args = {
            "authenticator": auth, 
            "access_token": config.get("access_token"),
            "start_date": config.get("start_date"),
            }
        return [
            Connections(**args),
            Orders(**args),
            Customers(**args),
        ]