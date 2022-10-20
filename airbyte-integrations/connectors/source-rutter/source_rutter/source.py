#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#

from __future__ import annotations

from abc import ABC
import base64
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Dict

import requests
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth import BasicHttpAuthenticator, TokenAuthenticator
from airbyte_cdk.models import SyncMode


class RutterStream(HttpStream, ABC):

    url_base = "https://production.rutterapi.com/"

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        return None

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        return None

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json

class Connections(RutterStream):

    primary_key = "id"

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
        stream = Connections(authenticator=self.authenticator)
        for record in stream.read_records(sync_mode=SyncMode.full_refresh):
            yield {"access_token": record["access_token"]}

class Orders(ConnectionsRelatedStream):

    primary_key = "id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "orders"

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        next_page_token = response.json().get("next_cursor")

        if next_page_token:
            next_page_starting_after = response.json().get("next_cursor")
            return next_page_starting_after
        else:
            return None

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = {"access_token":stream_slice["access_token"], "cursor":next_page_token, "expand":"transactions"}
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("orders", [])

class Customers(ConnectionsRelatedStream):

    primary_key = "id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "customers"

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        next_page_token = response.json().get("next_cursor")

        if next_page_token:
            next_page_starting_after = response.json().get("next_cursor")
            return next_page_starting_after
        else:
            return None

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = {"access_token":stream_slice["access_token"]}
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("customers", [])

class Products(ConnectionsRelatedStream):

    primary_key = "id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "products"

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        next_page_token = response.json().get("next_cursor")

        if next_page_token:
            next_page_starting_after = response.json().get("next_cursor")
            return next_page_starting_after
        else:
            return None

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None, **kwargs
    ) -> MutableMapping[str, Any]:
        
        params = {"access_token":stream_slice["access_token"]}
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("products", [])

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
        streams = [
            Connections(**full_refresh_stream_kwargs),
            Orders(**full_refresh_stream_kwargs),
            Customers(**full_refresh_stream_kwargs),
            Products(**full_refresh_stream_kwargs),
        ]        
        return streams


